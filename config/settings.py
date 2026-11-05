"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

Settings for the email forward confirmation Lambda, read from environment variables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_HELPDESK_EMAIL = "helpdesk@clickmerito.com"
DEFAULT_LOOKBACK_HOURS = 24.0
DEFAULT_POLL_TIMEOUT_SEC = 60.0
DEFAULT_POLL_INTERVAL_SEC = 2.0

GMAIL_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE_URL = "https://www.googleapis.com/gmail/v1"

# Same buckets autopilot reads `{"key": ...}` job details from (autopilot config/config.yaml `aws`).
S3_BUCKETS = {
    "dev": "uploadfiles-jigsaw",
    "beta": "meritoapp",
}


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    """Read a positive number from the environment, falling back to `default` when missing or invalid."""
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("⚠️ %s=%r is not a number, using default %s", name, raw, default)
        return default
    if value <= 0:
        logger.warning("⚠️ %s=%r must be positive, using default %s", name, raw, default)
        return default
    return value


@dataclass(frozen=True)
class Settings:
    environment: str
    # Optional fallback only: the callback URL comes from the event's `apiLink`.
    api_url: str
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    slack_token: str
    helpdesk_email: str = DEFAULT_HELPDESK_EMAIL
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS
    poll_timeout_sec: float = DEFAULT_POLL_TIMEOUT_SEC
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC
    s3_bucket: Optional[str] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        environment = env.get("ENVIRONMENT", "dev")
        return cls(
            environment=environment,
            api_url=(env.get("API_URL") or "").rstrip("/"),
            gmail_client_id=env.get("GMAIL_CLIENT_ID", ""),
            gmail_client_secret=env.get("GMAIL_CLIENT_SECRET", ""),
            gmail_refresh_token=env.get("GMAIL_REFRESH_TOKEN", ""),
            slack_token=env.get("SLACK_DATA_FETCHING_TOKEN", ""),
            helpdesk_email=env.get("HELPDESK_EMAIL") or DEFAULT_HELPDESK_EMAIL,
            lookback_hours=_positive_float(env, "FORWARD_EMAIL_LOOKBACK_HOURS", DEFAULT_LOOKBACK_HOURS),
            poll_timeout_sec=_positive_float(env, "POLL_TIMEOUT_SEC", DEFAULT_POLL_TIMEOUT_SEC),
            poll_interval_sec=_positive_float(env, "POLL_INTERVAL_SEC", DEFAULT_POLL_INTERVAL_SEC),
            s3_bucket=env.get("S3_BUCKET") or S3_BUCKETS.get(environment),
        )
