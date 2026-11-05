"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

AWS Lambda entry point for job type 15 (EMAIL_FORWARD_CONFIRMATION).

It replaces autopilot's RF task `Complete Email Forward Confirmation` (shared/common.robot):
1. Search the helpdesk inbox for Gmail's forwarding confirmation email from the last
   FORWARD_EMAIL_LOOKBACK_HOURS (default 24). If none is there yet, poll every POLL_INTERVAL_SEC
   (default 2s) for up to POLL_TIMEOUT_SEC (default 60s).
2. Open the confirmation link and submit Confirm automatically (services/forward_confirmer.py).
3. Send the job 15 callback to jigsaw-api (`{event.apiLink}/Charts/handleemailforwarding`) exactly once,
   plus a Slack alert on failure.

The handler never raises, so async invokes don't retry and send a second callback.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from config.settings import Settings
from services.callback_service import (
    CallbackErrorCode,
    account_email,
    build_callback_body,
    send_callback,
)
from services.email_parser import decode_email_body, extract_confirmation_url
from services.forward_confirmer import ConfirmResult, confirm
from services.gmail_service import (
    GmailApiError,
    GmailService,
    build_forwarding_query,
)
from services.slack_service import send_slack_alert
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

# Portals with an EMAIL_FORWARD_CONFIRMATION flow in autopilot `shared/constants.py` MARKETPLACE_FLOWS.
SUPPORTED_PORTALS = frozenset(
    {
        "Zepto",
        "Blinkit Marketplace",
        "Blinkit B2B",
        "Blinkit Ads",
        "Swiggy Instamart",
        "Flipkart Seller",
        "Nykaa",
    }
)

# A user who re-added the forwarding address has several confirmation emails; only the newest few
# are worth trying, newest first.
MAX_MESSAGES_PER_POLL = 3

NOT_FOUND_RAW_ERROR = "No confirmation URL found"


@dataclass(frozen=True)
class Outcome:
    success: bool
    error_code: Optional[CallbackErrorCode] = None
    raw_error: str = ""


def load_event(event, settings: Settings, s3_client=None) -> dict:
    """
    Accept the event the way autopilot `main.py:load_environment_config` does: the event itself,
    the `job_details` JSON string Batch receives, or a `{"key": ...}` pointer to it in S3.
    """
    if isinstance(event, str):
        event = json.loads(event)
    if isinstance(event, dict) and isinstance(event.get("job_details"), str):
        event = json.loads(event["job_details"])
    if not isinstance(event, dict):
        raise ValueError(f"Unsupported event type: {type(event).__name__}")

    if "key" in event and "job" not in event:
        if not settings.s3_bucket:
            raise ValueError(f"No S3 bucket configured for environment {settings.environment!r}")
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        logger.info("📦 Fetching job details from s3://%s/%s", settings.s3_bucket, event["key"])
        obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=event["key"])
        event = json.loads(obj["Body"].read())

    return {**event, "environment": settings.environment}


def _confirm_from_messages(
    gmail: GmailService,
    message_ids: list[str],
    confirmer: Callable[[str], ConfirmResult],
) -> Optional[Outcome]:
    """Try the newest emails in turn. Returns None when none of them held a confirmation link."""
    failures = []
    for message_id in message_ids[:MAX_MESSAGES_PER_POLL]:
        try:
            payload = gmail.get_payload(message_id)
        except GmailApiError as exc:
            logger.warning("⚠️ Could not read email %s: %s", message_id, exc)
            continue

        url = extract_confirmation_url(decode_email_body(payload))
        if not url:
            logger.warning("⚠️ Email %s has no confirmation link", message_id)
            continue

        logger.info("🔗 Confirmation link found in email %s", message_id)
        result = confirmer(url)
        if result.success:
            return Outcome(True)
        logger.warning("⚠️ Confirming via email %s failed: %s", message_id, result.detail)
        failures.append(result.detail)

    if failures:
        return Outcome(False, CallbackErrorCode.FORWARD_CONFIRM_FAILED, "; ".join(failures))
    return None


def confirm_email_forward(
    event: dict,
    settings: Settings,
    gmail: GmailService,
    confirmer: Callable[[str], ConfirmResult] = confirm,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Outcome:
    ip_name = (event.get("integrationPartner") or {}).get("name", "")
    if ip_name not in SUPPORTED_PORTALS:
        return Outcome(
            False,
            CallbackErrorCode.UNSUPPORTED_JOB,
            f"No email forward confirmation flow configured for {ip_name or 'unknown portal'}",
        )

    email = account_email(event)
    if not email:
        return Outcome(False, CallbackErrorCode.TECHNICAL_ERROR, "Event has no account email (customer_id)")

    query = build_forwarding_query(settings.helpdesk_email, email, settings.lookback_hours)
    logger.info(
        "🔍 Looking for the forwarding confirmation of %s | lookback=%sh | poll every %ss for %ss | query=%s",
        email,
        settings.lookback_hours,
        settings.poll_interval_sec,
        settings.poll_timeout_sec,
        query,
    )

    deadline = clock() + settings.poll_timeout_sec
    attempt = 0
    last_error = ""
    while True:
        attempt += 1
        try:
            message_ids = gmail.search(query)
        except GmailApiError as exc:
            # Transient: keep polling, and report it only if nothing is ever found.
            logger.warning("⚠️ Gmail search failed on attempt %d: %s", attempt, exc)
            message_ids = []
            last_error = str(exc)

        if message_ids:
            logger.info("📩 %d matching email(s) on attempt %d", len(message_ids), attempt)
            outcome = _confirm_from_messages(gmail, message_ids, confirmer)
            if outcome is not None:
                return outcome

        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleep(min(settings.poll_interval_sec, remaining))

    logger.warning("⚠️ No forwarding confirmation email found after %d attempts", attempt)
    return Outcome(False, CallbackErrorCode.FORWARD_EMAIL_NOT_FOUND, last_error or NOT_FOUND_RAW_ERROR)


def _slack_message(outcome: Outcome) -> str:
    if outcome.error_code == CallbackErrorCode.FORWARD_EMAIL_NOT_FOUND:
        return "⚠️ OTP Forwarder Confirmation failed: confirmation email not found"
    return f"⚠️ OTP Forwarder Confirmation failed: {outcome.raw_error}"


def callback_base_url(job_event: dict, settings: Settings) -> str:
    """jigsaw-api base URL from the event's `apiLink`, falling back to the optional API_URL env var."""
    return (job_event.get("apiLink") or settings.api_url or "").strip().rstrip("/")


def _report(job_event: dict, outcome: Outcome, settings: Settings) -> bool:
    """Send the callback, then the Slack alert on failure. Never raises."""
    if not job_event.get("job") and not job_event.get("connectionId"):
        logger.critical("🚨 Event could not be read, so there is no job to report back: %s", outcome)
        return False
    try:
        body = build_callback_body(
            job_event,
            success=outcome.success,
            helpdesk_email=settings.helpdesk_email,
            error_code=outcome.error_code,
            raw_error=outcome.raw_error,
        )
        sent = send_callback(callback_base_url(job_event, settings), body)
        if not outcome.success:
            send_slack_alert(
                settings.slack_token,
                integration_partner_name=(job_event.get("integrationPartner") or {}).get("name", ""),
                company_id=(job_event.get("user") or {}).get("companyId"),
                msg_body=_slack_message(outcome),
            )
        return sent
    except Exception as exc:
        logger.exception("🚨 Could not report job 15 result: %s", exc)
        return False


def lambda_handler(event, context=None) -> dict:
    setup_logging()
    started = time.monotonic()
    settings = Settings.from_env()
    job_event: dict = {}

    try:
        job_event = load_event(event, settings)
        logger.info(
            "📩 Job 15 | job=%s | connection=%s | company=%s | portal=%s | env=%s",
            (job_event.get("job") or {}).get("id"),
            job_event.get("connectionId"),
            (job_event.get("user") or {}).get("companyId"),
            (job_event.get("integrationPartner") or {}).get("name"),
            settings.environment,
        )
        gmail = GmailService(
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            refresh_token=settings.gmail_refresh_token,
        )
        outcome = confirm_email_forward(job_event, settings, gmail)
    except Exception as exc:
        logger.exception("🚨 Job 15 crashed: %s", exc)
        outcome = Outcome(False, CallbackErrorCode.TECHNICAL_ERROR, str(exc))

    callback_sent = _report(job_event, outcome, settings)
    result = {
        "status": "SUCCESS" if outcome.success else "FAILURE",
        "errorCode": outcome.error_code.value if outcome.error_code else None,
        "callbackSent": callback_sent,
        "durationMs": int((time.monotonic() - started) * 1000),
    }
    logger.info("🏁 Job 15 finished: %s", result)
    return result
