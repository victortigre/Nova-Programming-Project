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
ROW = {"listing_status": "active", "listing_id": 10, "original_listing_id": 10, "id": CID, "buyer_id": 7, "seller_id": 8, "own_profile_id": 7,
       "other_name": "Test participant", "listing_title_snapshot": "Test listing snapshot",
       "price_cents": 2000, "created_at": "2026-11-19T10:00:00+00:00",
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
                         ("get_conversation_details", ROW), ("get_chat_events", []),
                         ("get_offers", []), ("get_buy_now_agreement", None),
                         ("send_message", {"id": 1}), ("mark_read", None)):
        mocks[name] = MagicMock(return_value=result)
        monkeypatch.setattr(repository, name, mocks[name])
    return AppTest.from_file(PAGE), mocks, user


def test_navigation_and_send(ui):
    app, mocks, _ = ui
    app.run()
    assert not app.exception
    assert any("Test listing snapshot" in item.proto.body for item in app.get("html"))
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
    assert app.title[0].value == "Inbox"


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
    assert app.subheader[0].value == "Your inbox is empty"
    assert app.info[0].value == "Your conversations will appear here when you contact someone or receive a message or offer."
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
    mocks["get_chat_events"].assert_not_called()
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
    assert app.title[0].value == "Inbox"
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


def test_deleted_listing_keeps_inbox_snapshot_and_chat_input(ui):
    app, mocks, _ = ui
    deleted = {**ROW, "listing_id": None}
    mocks["get_inbox"].return_value = [deleted]
    mocks["get_conversation_details"].return_value = deleted
    app.run()
    assert any("Listing no longer available" in item.proto.body for item in app.get("html"))
    app.button(key=f"chat_{CID}").click().run()
    assert not app.exception
    assert any("Listing no longer available" in item.value for item in app.info)
    header = next(c for c in app.get("flex_container") if c.key == "chat-participant-header")
    assert not header.caption
    app.chat_input[0].set_value("Can we still meet?").run()
    assert not app.exception
    assert mocks["send_message"].call_args.args[:2] == (CID, "Can we still meet?")


@pytest.mark.parametrize("cents,display", [(0, "Free"), (1, "€0.01"), (1234, "€12.34"), (500000, "€5,000.00")])
def test_integer_cent_snapshots_preserved_in_offer_cards_not_name_only_header(ui, cents, display):
    app, mocks, _ = ui
    snapshot = {**ROW, "price_cents": cents, "listing_id": None}
    mocks["get_inbox"].return_value = [snapshot]
    mocks["get_conversation_details"].return_value = snapshot
    from test_offer_ui import OFFER
    mocks["get_chat_events"].return_value = [OFFER]
    app.run()
    assert not app.exception
    assert not any(item.value == display for item in app.caption)
    app.button(key=f"chat_{CID}").click().run()
    assert not app.exception
    assert any(item.value == f"Original listing price: {display}" for item in app.caption)
    assert any("Listing no longer available" in item.value for item in app.info)
    header = next(c for c in app.get("flex_container") if c.key == "chat-participant-header")
    assert not header.caption


@pytest.mark.parametrize("status", ["pending", "accepted", "declined", "superseded"])
def test_inbox_offer_only_preview(ui, status):
    app, mocks, _ = ui
    mocks["get_inbox"].return_value = [{**ROW, "last_activity": {
        "id": CID, "type": "offer", "amount_cents": 2500, "sender_id": 8,
        "status": status, "created_at": ROW["created_at"], "activity_at": ROW["created_at"],
    }}]
    app.run()
    assert not app.exception
    assert any(f"Offer: €25.00 · {status.title()}" in item.proto.body for item in app.get("html"))
    assert not any(item.value == "No messages yet" for item in app.caption)


def test_a_refused_message_does_not_lock_the_chat(ui):
    # Only spaces: the message is refused. Trying it again can't work, so
    # nothing is kept as "pending" and the next message can be typed at once.
    app, mocks, _ = ui
    app.run()
    app.button(key=f"chat_{CID}").click().run()
    mocks["send_message"].side_effect = ValueError("Write a message before sending.")
    app.chat_input[0].set_value("   ").run()
    assert any(item.value == "Write a message before sending." for item in app.warning)
    assert "messaging_pending" not in app.session_state
    app.run()
    assert not app.chat_input[0].disabled
    assert not any(button.label == "Retry message" for button in app.button)
    assert not app.exception
