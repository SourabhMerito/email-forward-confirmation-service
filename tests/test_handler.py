"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com
"""

import io
import json

import pytest

import handler
from services.callback_service import CallbackErrorCode
from services.forward_confirmer import ConfirmResult
from services.gmail_service import GmailApiError, GmailAuthError
from tests.conftest import CONFIRM_URL, confirmation_payload


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeGmail:
    """`results` is consumed one item per search: a list of ids, or an exception to raise."""

    def __init__(self, results, payloads=None):
        self.results = list(results)
        self.payloads = payloads or {}
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        result = self.results.pop(0) if self.results else []
        if isinstance(result, Exception):
            raise result
        return result

    def get_payload(self, message_id):
        payload = self.payloads[message_id]
        if isinstance(payload, Exception):
            raise payload
        return payload


def run(event, settings, gmail, confirmer=None, fake=None):
    fake = fake or FakeClock()
    confirmer = confirmer or (lambda url: ConfirmResult(True, "confirmed"))
    return handler.confirm_email_forward(
        event, settings, gmail, confirmer=confirmer, clock=fake.clock, sleep=fake.sleep
    )


def test_confirms_on_first_poll(event, settings):
    seen = []
    gmail = FakeGmail([["m1"]], {"m1": confirmation_payload()})
    outcome = run(event, settings, gmail, confirmer=lambda url: seen.append(url) or ConfirmResult(True, "ok"))
    assert outcome.success
    assert seen == [CONFIRM_URL]
    assert len(gmail.queries) == 1


def test_waits_for_email_that_arrives_later(event, settings):
    fake = FakeClock()
    gmail = FakeGmail([[], [], ["m1"]], {"m1": confirmation_payload()})
    outcome = run(event, settings, gmail, fake=fake)
    assert outcome.success
    assert fake.sleeps == [2, 2]


def test_not_found_after_polling_every_2s_for_60s(event, settings):
    fake = FakeClock()
    gmail = FakeGmail([])
    outcome = run(event, settings, gmail, fake=fake)
    assert outcome == handler.Outcome(False, CallbackErrorCode.FORWARD_EMAIL_NOT_FOUND, "No confirmation URL found")
    assert fake.now == 60
    assert set(fake.sleeps) == {2}
    assert len(gmail.queries) == 31


def test_tries_older_email_when_newest_fails(event, settings):
    old_url = "https://mail-settings.google.com/mail/vf-%5BOLD%5D-1"
    gmail = FakeGmail([["new", "old"]], {"new": confirmation_payload(), "old": confirmation_payload(old_url)})
    outcome = run(
        event,
        settings,
        gmail,
        confirmer=lambda url: ConfirmResult(url == old_url, "expired" if url != old_url else "ok"),
    )
    assert outcome.success


def test_confirm_failure_stops_polling(event, settings):
    gmail = FakeGmail([["m1"]], {"m1": confirmation_payload()})
    outcome = run(event, settings, gmail, confirmer=lambda url: ConfirmResult(False, "expired link"))
    assert outcome == handler.Outcome(False, CallbackErrorCode.FORWARD_CONFIRM_FAILED, "expired link")
    assert len(gmail.queries) == 1


def test_gmail_errors_are_retried(event, settings):
    gmail = FakeGmail([GmailApiError("503"), ["m1"]], {"m1": confirmation_payload()})
    assert run(event, settings, gmail).success


def test_unsupported_portal(event, settings):
    event["integrationPartner"]["name"] = "Myntra"
    outcome = run(event, settings, FakeGmail([]))
    assert outcome.error_code == CallbackErrorCode.UNSUPPORTED_JOB


def test_missing_account_email(event, settings):
    event["apiConfig"] = [{}]
    assert run(event, settings, FakeGmail([])).error_code == CallbackErrorCode.TECHNICAL_ERROR


def test_load_event_accepts_job_details_string_and_s3_key(settings, event):
    assert handler.load_event({"job_details": json.dumps(event)}, settings)["job"]["id"] == "job-1"

    class FakeS3:
        def get_object(self, Bucket, Key):
            assert (Bucket, Key) == ("uploadfiles-jigsaw", "jobs/1.json")
            return {"Body": io.BytesIO(json.dumps(event).encode())}

    loaded = handler.load_event({"key": "jobs/1.json"}, settings, s3_client=FakeS3())
    assert loaded["connectionId"] == "conn-1"
    assert loaded["environment"] == "dev"


def test_callback_url_comes_from_event_api_link(event, settings):
    event["apiLink"] = "https://jigsaw.example.com/"
    assert handler.callback_base_url(event, settings) == "https://jigsaw.example.com"


def test_callback_url_falls_back_to_api_url_env(event, settings):
    assert "apiLink" not in event
    assert handler.callback_base_url(event, settings) == "https://api.test"


@pytest.fixture
def lambda_env(monkeypatch, settings):
    calls = {"callbacks": [], "urls": [], "slack": []}
    monkeypatch.setattr(handler.Settings, "from_env", classmethod(lambda cls, env=None: settings))

    def fake_send_callback(url, body):
        calls["urls"].append(url)
        calls["callbacks"].append(body)
        return True

    monkeypatch.setattr(handler, "send_callback", fake_send_callback)
    monkeypatch.setattr(handler, "send_slack_alert", lambda *args, **kwargs: calls["slack"].append(kwargs))
    return calls


def test_lambda_handler_success_sends_one_callback(monkeypatch, lambda_env, event):
    monkeypatch.setattr(handler, "confirm_email_forward", lambda *args, **kwargs: handler.Outcome(True))
    event["apiLink"] = "https://jigsaw.example.com"
    result = handler.lambda_handler(event)
    assert result["status"] == "SUCCESS"
    assert [body["isEmailForwarded"] for body in lambda_env["callbacks"]] == [True]
    assert lambda_env["urls"] == ["https://jigsaw.example.com"]
    assert lambda_env["slack"] == []


def test_lambda_handler_failure_sends_callback_and_slack(monkeypatch, lambda_env, event):
    monkeypatch.setattr(
        handler,
        "confirm_email_forward",
        lambda *args, **kwargs: handler.Outcome(False, CallbackErrorCode.FORWARD_EMAIL_NOT_FOUND, "x"),
    )
    result = handler.lambda_handler(event)
    assert result["errorCode"] == "FORWARD_EMAIL_NOT_FOUND"
    assert len(lambda_env["callbacks"]) == 1
    assert lambda_env["slack"][0]["msg_body"].endswith("confirmation email not found")


def test_lambda_handler_crash_reports_technical_error(monkeypatch, lambda_env, event):
    def boom(*args, **kwargs):
        raise GmailAuthError("invalid_grant")

    monkeypatch.setattr(handler, "confirm_email_forward", boom)
    result = handler.lambda_handler(event)
    assert result["errorCode"] == "TECHNICAL_ERROR"
    assert lambda_env["callbacks"][0]["rawError"] == "invalid_grant"


def test_lambda_handler_unreadable_event_sends_no_callback(lambda_env):
    result = handler.lambda_handler("not json")
    assert result["status"] == "FAILURE"
    assert result["callbackSent"] is False
    assert lambda_env["callbacks"] == []
