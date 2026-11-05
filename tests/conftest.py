"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com
"""

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings  # noqa: E402


@pytest.fixture
def settings():
    return Settings.from_env(
        {
            "ENVIRONMENT": "dev",
            "API_URL": "https://api.test",
            "GMAIL_CLIENT_ID": "cid",
            "GMAIL_CLIENT_SECRET": "secret",
            "GMAIL_REFRESH_TOKEN": "refresh",
            "SLACK_DATA_FETCHING_TOKEN": "xoxb-test",
        }
    )


@pytest.fixture
def event():
    return {
        "user": {"companyId": 1234},
        "userId": 56,
        "connectionId": "conn-1",
        "authMethod": "email_otp",
        "integrationPartner": {"id": "ip-zepto", "name": "Zepto"},
        "job": {"id": "job-1", "type": 15},
        "apiConfig": [{"customer_id": "seller@example.com", "accessToken": "pw"}],
        "environment": "dev",
    }


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


CONFIRM_URL = "https://mail-settings.google.com/mail/vf-%5BANGjdJ8%5D-abc123"


def confirmation_payload(url: str = CONFIRM_URL) -> dict:
    """A Gmail `format=full` payload shaped like Google's forwarding confirmation email."""
    plain = f"seller@example.com has requested to automatically forward mail.\n\nTo allow, click:\n{url}\n"
    html = f'<html><body><p>To allow, click the link below:</p><a href="{url}">{url}</a></body></html>'
    return {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "Subject", "value": "(#123) Gmail Forwarding Confirmation - Receive Mail from seller@example.com"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": b64(plain)}},
            {"mimeType": "text/html", "body": {"data": b64(html)}},
        ],
    }
