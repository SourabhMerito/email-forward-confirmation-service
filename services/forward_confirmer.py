"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com

Confirms Gmail forwarding automatically, without a browser.

This does what autopilot's RF keyword `Confirm Forwarder Verification` (shared/common.robot) does:
open the confirmation link, click the `Confirm` submit input and check for "Confirmation Success!".
The page is a plain HTML form, so it is fetched and submitted with `requests`.

Run directly against a real link to check the flow end to end:
    python -m services.forward_confirmer "https://mail-settings.google.com/mail/vf-..."
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SEC = 15
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

SUCCESS_MARKERS = ("confirmation success!",)
# Shown when the link is opened again after it was already confirmed; that is still a success.
# Check these against the real page when validating against a live link.
ALREADY_CONFIRMED_MARKERS = (
    "already been confirmed",
    "already confirmed",
    "already been verified",
    "already verified",
)


@dataclass(frozen=True)
class ConfirmResult:
    success: bool
    detail: str


def _page_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _is_confirmed(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SUCCESS_MARKERS + ALREADY_CONFIRMED_MARKERS)


def _snippet(text: str, limit: int = 200) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def _find_confirm_form(soup: BeautifulSoup):
    """Return (form, submit_input) for the form whose submit input is labelled Confirm."""
    for form in soup.find_all("form"):
        for submit in form.find_all("input", attrs={"type": "submit"}):
            if (submit.get("value") or "").strip().lower() == "confirm":
                return form, submit
    return None, None


def _form_fields(form, submit) -> dict:
    """Every named input the browser would send, plus the Confirm button that was clicked."""
    fields = {}
    for field in form.find_all("input"):
        name = field.get("name")
        if not name:
            continue
        if (field.get("type") or "").lower() in ("submit", "button", "image", "reset"):
            continue
        fields[name] = field.get("value", "")
    if submit.get("name"):
        fields[submit["name"]] = submit.get("value", "")
    return fields


def confirm(url: str, session: Optional[requests.Session] = None) -> ConfirmResult:
    """Open the confirmation link and submit its Confirm form. Never raises."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        page = session.get(url, timeout=REQUEST_TIMEOUT_SEC)
        page.raise_for_status()
        page_text = _page_text(page.text)
        if _is_confirmed(page_text):
            logger.info("✅ Forwarding was already confirmed for this link")
            return ConfirmResult(True, "already confirmed")

        soup = BeautifulSoup(page.text, "html.parser")
        form, submit = _find_confirm_form(soup)
        if form is None:
            return ConfirmResult(
                False,
                f"Confirm button not found on confirmation page (HTTP {page.status_code}): {_snippet(page_text)}",
            )

        action = urljoin(page.url, form.get("action") or page.url)
        method = (form.get("method") or "get").strip().lower()
        fields = _form_fields(form, submit)
        logger.info("📨 Submitting Confirm form (%s %s, fields=%s)", method.upper(), action, sorted(fields))
        if method == "post":
            result = session.post(action, data=fields, timeout=REQUEST_TIMEOUT_SEC)
        else:
            result = session.get(action, params=fields, timeout=REQUEST_TIMEOUT_SEC)
        result.raise_for_status()

        result_text = _page_text(result.text)
        if _is_confirmed(result_text):
            logger.info("✅ Gmail confirmed the forwarding address")
            return ConfirmResult(True, "confirmed")
        return ConfirmResult(
            False,
            f"Confirmation page did not report success (HTTP {result.status_code}): {_snippet(result_text)}",
        )
    except requests.RequestException as exc:
        return ConfirmResult(False, f"Confirmation request failed: {exc}")


if __name__ == "__main__":
    import sys

    from utils.logger import setup_logging

    setup_logging()
    if len(sys.argv) != 2:
        sys.exit("usage: python -m services.forward_confirmer <confirmation url>")
    outcome = confirm(sys.argv[1])
    print(outcome)
    sys.exit(0 if outcome.success else 1)
