"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com
"""

from urllib.parse import parse_qs

import responses

from services.forward_confirmer import confirm
from tests.conftest import CONFIRM_URL

CONFIRM_PAGE = """
<html><body><table><tr><td>
  <p>seller@example.com has requested to automatically forward mail to helpdesk@clickmerito.com.</p>
  <form method="POST" action="/mail/uf-%5BANGjdJ8%5D-abc123">
    <input type="hidden" name="token" value="tok-1">
    <input type="hidden" name="at" value="at-2">
    <input type="submit" name="confirm" value="Confirm">
  </form>
  <form method="POST" action="/mail/cancel"><input type="submit" value="Cancel"></form>
</td></tr></table></body></html>
"""
SUCCESS_PAGE = "<html><body><table><tr><td>Confirmation Success!</td></tr></table></body></html>"
POST_URL = "https://mail-settings.google.com/mail/uf-%5BANGjdJ8%5D-abc123"


@responses.activate
def test_submits_confirm_form_and_reports_success():
    responses.get(CONFIRM_URL, body=CONFIRM_PAGE)
    responses.post(POST_URL, body=SUCCESS_PAGE)

    result = confirm(CONFIRM_URL)

    assert result.success
    post = responses.calls[1].request
    assert post.method == "POST"
    assert parse_qs(post.body) == {"token": ["tok-1"], "at": ["at-2"], "confirm": ["Confirm"]}


@responses.activate
def test_already_confirmed_page_counts_as_success():
    responses.get(CONFIRM_URL, body="<p>This forwarding address has already been confirmed.</p>")
    assert confirm(CONFIRM_URL).success
    assert len(responses.calls) == 1


@responses.activate
def test_missing_confirm_button_fails():
    responses.get(CONFIRM_URL, body="<p>This link has expired.</p>")
    result = confirm(CONFIRM_URL)
    assert not result.success
    assert "Confirm button not found" in result.detail


@responses.activate
def test_post_without_success_text_fails():
    responses.get(CONFIRM_URL, body=CONFIRM_PAGE)
    responses.post(POST_URL, body="<p>Something went wrong</p>")
    result = confirm(CONFIRM_URL)
    assert not result.success
    assert "did not report success" in result.detail


@responses.activate
def test_http_error_fails_without_raising():
    responses.get(CONFIRM_URL, status=500)
    result = confirm(CONFIRM_URL)
    assert not result.success
    assert "request failed" in result.detail
