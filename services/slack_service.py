"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

Failure alerts to Slack, in the same format as autopilot `backend/status_service.py`
`send_special_slack_notifications`. Uses the Web API directly so slack_sdk isn't needed.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
SLACK_CHANNEL = "#partner-alerts"
SLACK_TIMEOUT_SEC = 5


def send_slack_alert(token: str, integration_partner_name: str, company_id, msg_body: str) -> None:
    """Never raises: a failed alert must not stop the job's callback."""
    if not token:
        logger.warning("⚠️ SLACK_DATA_FETCHING_TOKEN is not set, Slack alert skipped")
        return

    message = f"`{integration_partner_name}`: For `{company_id}`, {msg_body}"
    try:
        response = requests.post(
            SLACK_POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": SLACK_CHANNEL, "text": message},
            timeout=SLACK_TIMEOUT_SEC,
        )
        data = response.json()
        if not data.get("ok"):
            logger.error("❌ Slack rejected the alert: %s", data.get("error"))
            return
        logger.info("📢 Slack alert sent to %s", SLACK_CHANNEL)
    except (requests.RequestException, ValueError) as exc:
        logger.error("❌ Could not send Slack alert: %s", exc)
