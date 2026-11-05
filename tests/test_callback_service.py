"""
Author: Sourabh Patil
Email: sourabh.patil@clickmerito.com
"""

import json

import responses

from services.callback_service import CallbackErrorCode, build_callback_body, send_callback


def test_success_body_matches_autopilot_job_15_body(event):
    body = build_callback_body(event, success=True, helpdesk_email="helpdesk@clickmerito.com")
    assert body == {
        "jobType": 15,
        "jobId": "job-1",
        "connectionId": "conn-1",
        "companyId": 1234,
        "accountId": "seller@example.com",
        "authMethod": "email_otp",
        "integrationPartner": {"id": "ip-zepto", "name": "Zepto"},
        "extraParams": {},
        "userId": 56,
        "errorCode": None,
        "errorMessage": "",
        "rawError": "",
        "isEmailForwarded": True,
        "emailForwardError": "",
        "crentialError": "",
    }


def test_not_found_body(event):
    body = build_callback_body(
        event,
        success=False,
        helpdesk_email="helpdesk@clickmerito.com",
        error_code=CallbackErrorCode.FORWARD_EMAIL_NOT_FOUND,
        raw_error="No confirmation URL found",
    )
    message = (
        "Gmail's confirmation email didn't reach helpdesk@clickmerito.com. "
        "Add it as a forwarding address again, then confirm."
    )
    assert body["isEmailForwarded"] is False
    assert body["errorCode"] == "FORWARD_EMAIL_NOT_FOUND"
    assert body["errorMessage"] == body["emailForwardError"] == body["crentialError"] == message
    assert body["rawError"] == "No confirmation URL found"


def test_account_id_prefers_top_level_customer_id(event):
    event["customer_id"] = "other@example.com"
    assert build_callback_body(event, success=True, helpdesk_email="h")["accountId"] == "other@example.com"


@responses.activate
def test_send_callback_retries_then_succeeds(event):
    responses.post("https://api.test/Charts/handleemailforwarding", status=502)
    responses.post("https://api.test/Charts/handleemailforwarding", json={"ok": True})
    body = build_callback_body(event, success=True, helpdesk_email="h")

    assert send_callback("https://api.test", body, sleep=lambda _: None)
    assert len(responses.calls) == 2
    assert json.loads(responses.calls[1].request.body) == body


@responses.activate
def test_send_callback_gives_up_after_three_attempts(event):
    responses.post("https://api.test/Charts/handleemailforwarding", status=500)
    body = build_callback_body(event, success=True, helpdesk_email="h")
    assert not send_callback("https://api.test", body, sleep=lambda _: None)
    assert len(responses.calls) == 3
