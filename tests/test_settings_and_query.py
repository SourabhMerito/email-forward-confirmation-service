"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com
"""

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import Settings
from services.gmail_service import build_forwarding_query

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def test_lookback_defaults_to_24_hours():
    assert Settings.from_env({}).lookback_hours == 24


def test_lookback_can_be_overridden():
    assert Settings.from_env({"FORWARD_EMAIL_LOOKBACK_HOURS": "48"}).lookback_hours == 48


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_invalid_lookback_falls_back_to_24_hours(raw):
    assert Settings.from_env({"FORWARD_EMAIL_LOOKBACK_HOURS": raw}).lookback_hours == 24


def test_poll_defaults_are_every_2s_for_60s():
    settings = Settings.from_env({})
    assert (settings.poll_interval_sec, settings.poll_timeout_sec) == (2, 60)


def test_s3_bucket_follows_environment():
    assert Settings.from_env({"ENVIRONMENT": "beta"}).s3_bucket == "meritoapp"
    assert Settings.from_env({"ENVIRONMENT": "dev"}).s3_bucket == "uploadfiles-jigsaw"


def test_query_uses_quoted_subject_anywhere_and_lookback_window():
    query = build_forwarding_query("helpdesk@clickmerito.com", "seller@example.com", 24, now=NOW)
    after = int((NOW - timedelta(hours=24)).timestamp())
    assert query == (
        "from:forwarding-noreply@google.com to:helpdesk@clickmerito.com "
        'subject:"Receive Mail from seller@example.com" '
        f"after:{after} in:anywhere"
    )


def test_query_window_follows_lookback_setting():
    query = build_forwarding_query("helpdesk@clickmerito.com", "seller@example.com", 48, now=NOW)
    assert f"after:{int((NOW - timedelta(hours=48)).timestamp())}" in query
