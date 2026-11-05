"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

Job 15 callback to jigsaw-api, the job-15 part of autopilot `backend/job_callback.py`.

The body must stay the same as autopilot's `build_callback_body` for job 15, since jigsaw-api's
`handleEmailForwardCallback` reads it. That includes the `crentialError` key, typo and all.
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

EMAIL_FORWARD_CONFIRMATION_JOB_TYPE = 15
CALLBACK_ROUTE = "/Charts/handleemailforwarding"
CALLBACK_TIMEOUT_SECONDS = 10
CALLBACK_ATTEMPTS = 3
CALLBACK_BACKOFF_SECONDS = 2


class CallbackErrorCode(str, Enum):
    FORWARD_EMAIL_NOT_FOUND = "FORWARD_EMAIL_NOT_FOUND"
    FORWARD_CONFIRM_FAILED = "FORWARD_CONFIRM_FAILED"
    UNSUPPORTED_JOB = "UNSUPPORTED_JOB"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"


ERROR_MESSAGES: dict[CallbackErrorCode, str] = {
    CallbackErrorCode.FORWARD_EMAIL_NOT_FOUND: (
        "Gmail's confirmation email didn't reach {helpdesk}. "
        "Add it as a forwarding address again, then confirm."
    ),
    CallbackErrorCode.FORWARD_CONFIRM_FAILED: (
        "We received Gmail's confirmation email but couldn't confirm forwarding. Please confirm again."
    ),
    CallbackErrorCode.UNSUPPORTED_JOB: "This step isn't available for {ip} yet. Please contact support.",
    CallbackErrorCode.TECHNICAL_ERROR: "Something went wrong on our side while checking {ip}. Please try again.",
}


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() in ("", "None")


def error_message_for(error_code: CallbackErrorCode, ip_name: str, helpdesk_email: str) -> str:
    return ERROR_MESSAGES[error_code].format(ip=ip_name or "the portal", helpdesk=helpdesk_email)


def account_email(event: dict) -> str:
    """The user's mailbox being forwarded, the same lookup as autopilot's `_account_id`."""
    if event.get("customer_id"):
        return event["customer_id"]
    api_config = event.get("apiConfig") or [{}]
    return (api_config[0] or {}).get("customer_id", "")


def build_callback_body(
    event: dict,
    *,
    success: bool,
    helpdesk_email: str,
    error_code: Optional[CallbackErrorCode] = None,
    raw_error: Any = "",
) -> dict:
    integration_partner = event.get("integrationPartner") or {}
    code = None if success else (error_code or CallbackErrorCode.TECHNICAL_ERROR)
    message = error_message_for(code, integration_partner.get("name", ""), helpdesk_email) if code else ""

    return {
        "jobType": EMAIL_FORWARD_CONFIRMATION_JOB_TYPE,
        "jobId": (event.get("job") or {}).get("id"),
        "connectionId": event.get("connectionId"),
        "companyId": (event.get("user") or {}).get("companyId"),
        "accountId": account_email(event),
        "authMethod": event.get("authMethod", "password"),
        "integrationPartner": integration_partner,
        "extraParams": {},
        "userId": event.get("userId", 0),
        "errorCode": code.value if code else None,
        "errorMessage": message,
        "rawError": "" if success or _is_blank(raw_error) else str(raw_error),
        "isEmailForwarded": success,
        "emailForwardError": message,
        "crentialError": message,
    }


def send_callback(api_url: str, body: dict, sleep=time.sleep) -> bool:
    """POST the callback to jigsaw-api with retries. Never raises; returns whether it was accepted."""
    if not api_url:
        logger.critical("🚨 Event has no apiLink (and API_URL is not set), job %s callback not sent", body.get("jobId"))
        return False

    url = f"{api_url}{CALLBACK_ROUTE}"
    logger.info("🧾 Callback payload for job 15: %s", json.dumps(body))
    for attempt in range(1, CALLBACK_ATTEMPTS + 1):
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=CALLBACK_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            logger.info("📬 Callback accepted (attempt %d): %s", attempt, response.text[:500])
            return True
        except requests.RequestException as exc:
            logger.error("🚨 Callback attempt %d/%d failed: %s", attempt, CALLBACK_ATTEMPTS, exc)
            if attempt < CALLBACK_ATTEMPTS:
                sleep(CALLBACK_BACKOFF_SECONDS * attempt)

    logger.critical("🚨 Job 15 callback was not delivered after %d attempts", CALLBACK_ATTEMPTS)
    return False
