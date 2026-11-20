"""Authenticated page tests: repository, identity, and client fully mocked."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

import database
import accounts
import messaging_repository as repository

CID = "11111111-1111-4111-8111-111111111111"
ROW = {"listing_id": 10, "original_listing_id": 10, "id": CID, "buyer_id": 7, "seller_id": 8, "own_profile_id": 7,
       "other_name": "Test participant", "listing_title_snapshot": "Test listing snapshot",
       "listing_price_snapshot": "20.00", "created_at": "2026-11-19T10:00:00+00:00",
       "last_message": None}
PAGE = str(Path(__file__).resolve().parents[1] / "views" / "messaging.py")


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setattr(database, "_client", MagicMock(side_effect=AssertionError("Live access forbidden")))
    user = SimpleNamespace(is_logged_in=True, to_dict=lambda: {
        "email": "test@novasbe.pt", "email_verified": True,
    })
    monkeypatch.setattr(repository.st, "user", user)
    monkeypatch.setattr(accounts, "logged_in_user", lambda: user.to_dict())
    mocks = {}
    for name, result in (("is_configured", True), ("require_access", None), ("get_inbox", [ROW]),
                         ("get_conversation_details", ROW), ("get_messages", []),
                         ("send_message", {"id": 1})):
        mocks[name] = MagicMock(return_value=result)
        monkeypatch.setattr(repository, name, mocks[name])
    return AppTest.from_file(PAGE), mocks, user


def test_navigation_and_send(ui):
    app, mocks, _ = ui
    app.run()
    assert not app.exception
    assert any(item.value == "Test listing snapshot" for item in app.text)
    app.button(key=f"chat_{CID}").click().run()
    assert not app.exception
    assert app.chat_input
    app.chat_input[0].set_value("Hello from UI").run()
    assert not app.exception
    args = mocks["send_message"].call_args.args
    assert args[:2] == (CID, "Hello from UI")
    assert len(args[2]) == 36
    next(button for button in app.button if button.label == "← Back to Inbox").click().run()
    assert not app.exception
    assert app.subheader[0].value == "Inbox"


def test_signed_out_never_calls_repository(ui):
    app, mocks, user = ui
    user.is_logged_in = False
    app.run()
    assert not app.exception
    assert "sign in" in app.info[0].value
    for mock in mocks.values():
        mock.assert_not_called()


def test_missing_configuration_and_empty_inbox(ui):
    app, mocks, _ = ui
    mocks["is_configured"].return_value = False
    app.run()
    assert "not set up" in app.info[0].value
    mocks["get_inbox"].assert_not_called()
    mocks["is_configured"].return_value = True
    mocks["get_inbox"].return_value = []
    app.run()
    assert "No conversations" in app.info[0].value
    assert not app.exception


def test_backend_error_is_sanitized(ui):
    app, mocks, _ = ui
    mocks["get_inbox"].side_effect = RuntimeError("private provider response")
    app.run()
    assert not app.exception
    assert "database setup" in app.error[0].value
    assert "private provider response" not in app.error[0].value


def test_unauthorized_chat_has_back_button_but_no_input(ui):
    app, mocks, _ = ui
    app.run()
    mocks["get_conversation_details"].side_effect = ValueError("Conversation unavailable.")
    app.button(key=f"chat_{CID}").click().run()
    assert not app.exception
    assert app.warning[0].value == "Conversation unavailable."
    assert not app.chat_input
    mocks["get_messages"].assert_not_called()
    assert any(button.label == "← Back to Inbox" for button in app.button)


def test_failed_send_retries_with_same_id_and_body(ui):
    app, mocks, _ = ui
    app.run()
    app.button(key=f"chat_{CID}").click().run()
    mocks["send_message"].side_effect = RuntimeError("network failed")
    app.chat_input[0].set_value("Keep this message").run()
    first = mocks["send_message"].call_args.args
    app.run()
    assert app.chat_input[0].disabled
    mocks["send_message"].side_effect = None
    next(button for button in app.button if button.label == "Retry message").click().run()
    assert mocks["send_message"].call_args.args == first
    assert not app.chat_input[0].disabled
    assert not app.exception


def test_account_change_clears_chat_and_pending_text(ui):
    app, _, user = ui
    app.run()
    app.session_state["messaging_selected"] = CID
    app.session_state["messaging_pending"] = {"body": "Private draft"}
    user.to_dict = lambda: {"email": "another@novasbe.pt", "email_verified": True}
    app.run()
    assert app.subheader[0].value == "Inbox"
    assert "messaging_pending" not in app.session_state
    assert not app.exception


@pytest.mark.parametrize("reason", ["Your account has been blocked.", "Finish the Welcome steps before using messages."])
def test_restricted_account_cannot_render_inbox(ui, reason):
    app, mocks, _ = ui
    mocks["require_access"].side_effect = ValueError(reason)
    app.run()
    assert not app.exception
    assert app.warning[0].value == reason
    mocks["get_inbox"].assert_not_called()
    assert not app.chat_input


def test_deleted_listing_keeps_snapshot_and_chat_input(ui):
    app, mocks, _ = ui
    deleted = {**ROW, "listing_id": None}
    mocks["get_inbox"].return_value = [deleted]
    mocks["get_conversation_details"].return_value = deleted
    app.run()
    assert any(item.value == "Listing no longer available" for item in app.caption)
    app.button(key=f"chat_{CID}").click().run()
    assert not app.exception
    assert any(item.value == "Listing no longer available" for item in app.caption)
    assert any(item.value == ROW["listing_title_snapshot"] for item in app.text)
    app.chat_input[0].set_value("Can we still meet?").run()
    assert not app.exception
    assert mocks["send_message"].call_args.args[:2] == (CID, "Can we still meet?")
