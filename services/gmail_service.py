"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

Gmail API access for the helpdesk inbox, adapted from autopilot `managers/gmail_manager.py`.

One instance is created per invocation, so the OAuth token is refreshed once and reused for
every poll. API failures raise instead of returning None, so the caller can tell "Gmail is
down" apart from "no matching email yet".
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from config.settings import GMAIL_API_BASE_URL, GMAIL_TOKEN_ENDPOINT

logger = logging.getLogger(__name__)

FORWARDING_SENDER = "forwarding-noreply@google.com"
REQUEST_TIMEOUT_SEC = 10


class GmailAuthError(Exception):
    """The OAuth refresh failed, so no Gmail call can succeed in this invocation."""


class GmailApiError(Exception):
    """A single Gmail API call failed; the next poll may succeed."""


def build_forwarding_query(
    helpdesk_email: str,
    account_email: str,
    lookback_hours: float,
    now: Optional[datetime] = None,
) -> str:
    """
    Build the Gmail search for Google's forwarding confirmation email.

    Google sends it from forwarding-noreply@google.com to the forwarding address (our helpdesk) with
    the subject "(#<code>) Gmail Forwarding Confirmation - Receive Mail from <account email>".

    - The subject is quoted, so the whole phrase must be in the subject. Unquoted, only the first word was.
    - `in:anywhere` also finds the email if a filter archived it or Gmail put it in spam.
    - `after:` is a Unix timestamp (UTC), which avoids Gmail reading YYYY/MM/DD as PST midnight.
    """
    now = now or datetime.now(timezone.utc)
    after = int((now - timedelta(hours=lookback_hours)).timestamp())
    return (
        f"from:{FORWARDING_SENDER} to:{helpdesk_email} "
        f'subject:"Receive Mail from {account_email}" '
        f"after:{after} in:anywhere"
    )


class GmailService:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        session: Optional[requests.Session] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = session or requests.Session()
        self._access_token: Optional[str] = None

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        try:
            response = self.session.post(
                GMAIL_TOKEN_ENDPOINT,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=REQUEST_TIMEOUT_SEC,
            )
            response.raise_for_status()
            self._access_token = response.json()["access_token"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise GmailAuthError(f"Gmail OAuth refresh failed: {exc}") from exc
        return self._access_token

    def _get(self, path: str, params: dict) -> dict:
        try:
            response = self.session.get(
                f"{GMAIL_API_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self._token()}"},
                params=params,
                timeout=REQUEST_TIMEOUT_SEC,
            )
            response.raise_for_status()
            return response.json()
        except GmailAuthError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise GmailApiError(f"Gmail API call {path} failed: {exc}") from exc

    def search(self, query: str) -> list[str]:
        """Return matching message ids, newest first, which is the order Gmail lists them in."""
        data = self._get("/users/me/messages", {"q": query})
        return [message["id"] for message in data.get("messages", [])]

    def get_payload(self, message_id: str) -> dict:
        """Return the MIME payload of a message (`format=full`)."""
        data = self._get(f"/users/me/messages/{message_id}", {"format": "full"})
        if "payload" not in data:
            raise GmailApiError(f"Gmail message {message_id} has no payload")
        return data["payload"]
