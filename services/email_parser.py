"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

Pulls Gmail's forwarding confirmation link out of an email. Adapted from autopilot
`helpers/email_helper.py` (`decode_email_body`, `extract_confirmation_url_from_html`).
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Both formats Google has used for the forwarding verification link.
CONFIRMATION_URL_PATTERN = re.compile(
    r"https://(?:mail\.google\.com|mail-settings\.google\.com)/mail/vf-[^\s\"'<>]+"
)


def decode_email_body(payload: dict) -> Optional[dict]:
    """
    Decode the body of a Gmail `format=full` payload, preferring text/html over text/plain.

    Returns {"mime_type": ..., "body": ...} or None when the email has no decodable body.
    """
    body_data = payload.get("body", {}).get("data", "")
    if body_data:
        try:
            return {
                "mime_type": payload.get("mimeType"),
                "body": base64.urlsafe_b64decode(body_data).decode("utf-8"),
            }
        except Exception as exc:
            logger.warning("⚠️ Could not decode email part (%s): %s", payload.get("mimeType"), exc)

    decoded_parts = [decode_email_body(part) for part in payload.get("parts", [])]
    decoded_parts = [part for part in decoded_parts if part]

    # Two passes so text/html wins even when text/plain comes first in the email.
    for mime_type in ("text/html", "text/plain"):
        for part in decoded_parts:
            if part.get("mime_type") == mime_type:
                return part
    return decoded_parts[0] if decoded_parts else None


def extract_confirmation_url(decoded: Optional[dict]) -> str:
    """Return the first forwarding confirmation link in the decoded email body, or ""."""
    if not decoded or not decoded.get("body"):
        return ""

    body = decoded["body"]
    candidates: list[str] = []
    if decoded.get("mime_type") == "text/html":
        soup = BeautifulSoup(body, "html.parser")
        # Link targets first: the visible text can be wrapped or shortened, the href never is.
        candidates.extend(anchor["href"] for anchor in soup.find_all("a", href=True))
        candidates.append(soup.get_text(separator=" ", strip=True))
    else:
        candidates.append(body)

    for candidate in candidates:
        match = CONFIRMATION_URL_PATTERN.search(candidate)
        if match:
            return match.group(0).rstrip(".,;)")
    return ""
