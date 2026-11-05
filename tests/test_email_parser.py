"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com
"""

from services.email_parser import decode_email_body, extract_confirmation_url
from tests.conftest import CONFIRM_URL, b64, confirmation_payload


def test_html_part_is_preferred_and_link_extracted():
    decoded = decode_email_body(confirmation_payload())
    assert decoded["mime_type"] == "text/html"
    assert extract_confirmation_url(decoded) == CONFIRM_URL


def test_plain_text_only_email():
    payload = {"mimeType": "text/plain", "body": {"data": b64(f"click:\n{CONFIRM_URL}.\n")}}
    assert extract_confirmation_url(decode_email_body(payload)) == CONFIRM_URL


def test_old_mail_google_com_format():
    url = "https://mail.google.com/mail/vf-%5BXYZ%5D-def456"
    payload = {"mimeType": "text/plain", "body": {"data": b64(f"Confirm: {url}")}}
    assert extract_confirmation_url(decode_email_body(payload)) == url


def test_no_link_returns_empty():
    payload = {"mimeType": "text/html", "body": {"data": b64("<p>hello</p>")}}
    assert extract_confirmation_url(decode_email_body(payload)) == ""
    assert extract_confirmation_url(None) == ""
