"""Offer forms/cards using mocked storage; no SQL or live services."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

import database
import messaging_repository as repository
from test_contact_seller import flow
from test_messaging_ui import ui, ROW, CID

REAL_CONVERSATION_DETAILS = repository.get_conversation_details

OID = "22222222-2222-4222-8222-222222222222"
OFFER = {"id": OID, "conversation_id": CID, "sender_id": 8, "amount_cents": 1500,
         "status": "pending", "type": "offer", "note": "Could collect today",
         "created_at": "2026-11-20T10:00:00+00:00", "parent_offer_id": None}


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


@pytest.fixture
def offer_flow(flow, monkeypatch):
    records, operations = [], {}

    def action(payload):
        operation_id = payload["p_operation_id"]
        if operation_id not in operations:
            row = {"id": str(uuid4()), "conversation_id": payload["p_conversation_id"],
                   "sender_id": payload["p_actor_id"], "amount_cents": payload["p_amount_cents"],
                   "note": payload["p_note"], "status": "pending", "parent_offer_id": None,
                   "created_at": "2026-11-20T10:00:00+00:00"}
            operations[operation_id] = row
            records.append(row)
        return operations[operation_id]

    rpc = MagicMock(side_effect=action)
    monkeypatch.setattr(database, "messaging_offer_action", rpc)
    monkeypatch.setattr(database, "messaging_offers", lambda *args: list(reversed(records)))
    monkeypatch.setattr(database, "names_of", lambda ids: {7: "Test buyer", 8: "Test seller"})
    message_insert = MagicMock()
    monkeypatch.setattr(database, "messaging_insert_message", message_insert)
    return flow, records, rpc, message_insert, action


@pytest.mark.parametrize("note", [None, "My optional note"])
def test_browse_offer_opens_chat_as_card_without_text_message(offer_flow, note):
    flow, records, rpc, message_insert, _ = offer_flow
    app = flow.app.run()
    assert not app.exception
    click(app, "Make an Offer")
    app.text_input(key="messaging_offer_price_browse-10").set_value("10,50")
    if note:
        app.text_area(key="messaging_offer_note_browse-10").set_value(note)
    click(app, "Send Offer")
    assert app.chat_input
    assert app.session_state["messaging_selected"] == CID
    assert len(records) == 1 and records[0]["amount_cents"] == 1050
    assert records[0]["note"] == note
    assert any(item.value == "€10.50" for item in app.subheader)
    assert any(item.value == "Original listing price: €12.34" for item in app.caption)
    assert any(item.value == "Status: Pending" for item in app.text)
    if note:
        assert sum(item.value == note for item in app.text) == 1
    assert len(app.chat_message) == 0
    message_insert.assert_not_called()
    flow.purchase.assert_not_called()
    assert rpc.call_count == 1


def test_invalid_price_does_not_create_conversation_or_offer(offer_flow):
    flow, records, rpc, _, _ = offer_flow
    app = flow.app.run()
    click(app, "Make an Offer")
    app.text_input(key="messaging_offer_price_browse-10").set_value("0")
    click(app, "Send Offer")
    assert app.warning
    rpc.assert_not_called()
    flow.creation.assert_not_called()
    assert records == []


def test_uncertain_send_reuses_operation_id_and_creates_one_card(offer_flow):
    flow, records, rpc, _, save = offer_flow

    def save_then_timeout(payload):
        save(payload)
        raise RuntimeError("network timeout after commit")

    rpc.side_effect = save_then_timeout
    app = flow.app.run()
    click(app, "Make an Offer")
    click(app, "Send Offer")
    assert app.error
    original = rpc.call_args.args[0]
    app.run()
    assert next(button for button in app.button if button.label == "Send Offer").disabled
    rpc.side_effect = save
    click(app, "Retry offer action")
    assert rpc.call_args.args[0] == original
    assert len(records) == 1
    assert app.chat_input
    assert len([item for item in app.caption if item.value == "PRICE OFFER"]) == 1


def test_retry_recovers_committed_offer_after_listing_deletion(offer_flow):
    flow, records, rpc, _, save = offer_flow

    def save_then_timeout(payload):
        save(payload)
        raise RuntimeError("response lost")

    rpc.side_effect = save_then_timeout
    app = flow.app.run()
    click(app, "Make an Offer")
    click(app, "Send Offer")
    assert app.session_state["messaging_offer_pending"]["conversation_id"] == CID
    # Simulate arriving at Inbox after deletion. Retry must use the remembered
    # conversation rather than trying to create one for a missing listing.
    flow.rows[CID]["listing_id"] = None
    flow.get_listing.side_effect = AssertionError("Retry must not reload a deleted listing")
    app.switch_page("views/messaging.py").run()
    rpc.side_effect = save
    click(app, "Retry offer action")
    assert len(records) == 1
    assert app.chat_input
    assert any("Listing no longer available" in item.value for item in app.info)


def open_chat(ui, offer=OFFER):
    app, mocks, _ = ui
    mocks["get_chat_events"].return_value = [dict(offer)]
    mocks["get_offers"].return_value = [dict(offer)]
    app.run()
    app.button(key=f"chat_{CID}").click().run()
    assert not app.exception
    return app, mocks


@pytest.mark.parametrize("actor", [7, 8])
def test_recipient_counter_creates_new_card_and_preserves_history(ui, monkeypatch, actor):
    app, mocks, _ = ui
    row = {**ROW, "own_profile_id": actor}
    mocks["get_conversation_details"].return_value = row
    original = {**OFFER, "sender_id": 8 if actor == 7 else 7}
    app, mocks = open_chat(ui, original)

    def counter(cid, parent, cents, operation_id, note):
        old = {**original, "status": "superseded"}
        new = {**original, "id": str(uuid4()), "sender_id": actor, "amount_cents": cents,
               "note": note, "parent_offer_id": parent, "created_at": "2026-11-20T10:01:00+00:00"}
        mocks["get_chat_events"].return_value = [old, new]
        mocks["get_offers"].return_value = [new]
        return new

    action = MagicMock(side_effect=counter)
    monkeypatch.setattr(repository, "counter_offer", action)
    click(app, "Counteroffer")
    app.text_input(key=f"messaging_offer_price_counter-{OID}").set_value("14.25")
    app.text_area(key=f"messaging_offer_note_counter-{OID}").set_value("My counter")
    click(app, "Send Counteroffer")
    assert action.call_args.args[:3] == (CID, OID, 1425)
    assert any(item.value == "Status: Superseded" for item in app.text)
    assert any(item.value == "Status: Pending" for item in app.text)
    assert sum(item.value == "My counter" for item in app.text) == 1
    assert not any(button.label == "Accept" for button in app.button)
    assert app.chat_input


@pytest.mark.parametrize("action,status", [("Accept", "accepted"), ("Decline", "declined")])
def test_offer_response_updates_card_and_offers_buy_now(ui, monkeypatch, action, status):
    app, mocks = open_chat(ui)

    def respond(*args):
        result = {**OFFER, "status": status}
        mocks["get_chat_events"].return_value = [result]
        mocks["get_offers"].return_value = [result]
        mocks["get_buy_now_agreement"].return_value = result if status == "accepted" else None
        return result

    response = MagicMock(side_effect=respond)
    monkeypatch.setattr(repository, f"{action.lower()}_offer", response)
    click(app, action)
    assert response.call_args.args[:2] == (CID, OID)
    if status == "accepted":
        assert not any(item.value == "Status: Accepted" for item in app.text)
        assert any(item.value.startswith("€15.00") for item in app.subheader)
        assert not next(button for button in app.button if "Buy Now" in button.label).disabled
        assert any(item.value.startswith("Reserves the item") for item in app.caption)
    else:
        assert any(item.value == f"Status: {status.title()}" for item in app.text)
    assert app.chat_input


@pytest.mark.parametrize("status,own,deleted", [
    ("pending", True, False), ("accepted", False, False), ("declined", False, False),
    ("superseded", False, False), ("pending", False, True),
])
def test_only_recipient_of_current_pending_offer_has_response_controls(ui, status, own, deleted):
    app, mocks, _ = ui
    if deleted:
        mocks["get_conversation_details"].return_value = {**ROW, "listing_id": None}
    app, _ = open_chat(ui, {**OFFER, "status": status, "sender_id": 7 if own else 8})
    assert not any(button.label in ("Accept", "Decline", "Counteroffer") for button in app.button)
    assert app.chat_input


@pytest.mark.parametrize("actor", [7, 8])
def test_offer_and_normal_message_remain_distinct(ui, actor):
    ui[1]["get_conversation_details"].return_value = {**ROW, "own_profile_id": actor}
    app, mocks = open_chat(ui)
    mocks["get_chat_events"].return_value = [OFFER, {
        "id": 1, "type": "message", "sender_id": 7, "body": "A regular message",
        "created_at": "2026-11-20T10:02:00+00:00",
    }]
    app.run()
    assert sum(item.value == "A regular message" for item in app.text) == 1
    assert any(item.value == "A regular message" for item in app.text)
    app.chat_input[0].set_value("Another message").run()
    mocks["send_message"].assert_called_once()
    assert mocks["send_message"].call_args.args[:2] == (CID, "Another message")


def test_stale_response_is_safe_and_does_not_hide_normal_chat(ui, monkeypatch):
    app, _ = open_chat(ui)
    monkeypatch.setattr(repository, "accept_offer", MagicMock(side_effect=APIError({
        "code": "23514", "message": "private provider text", "details": None, "hint": None,
    })))
    click(app, "Accept")
    assert any("Refresh the chat" in item.value for item in app.warning)
    assert not any("private provider text" in item.value for item in app.warning)
    assert app.chat_input


def test_outdated_pending_card_does_not_show_actions(ui):
    app, mocks = open_chat(ui)
    mocks["get_offers"].return_value = [{**OFFER, "id": str(uuid4())}]
    app.run()
    assert not app.exception
    assert not any(button.label in ("Accept", "Decline", "Counteroffer") for button in app.button)


def test_account_change_discards_offer_drafts_and_unconfirmed_actions(ui):
    app, _, user = ui
    app.run()
    app.session_state["messaging_offer_pending"] = {"note": "Private note"}
    app.session_state["messaging_offer_note_old"] = "Private draft"
    user.to_dict = lambda: {"email": "another@novasbe.pt", "email_verified": True}
    app.run()
    assert not app.exception
    assert "messaging_offer_pending" not in app.session_state
    assert "messaging_offer_note_old" not in app.session_state


@pytest.mark.parametrize("status", ["reserved", "sold", "unavailable"])
@pytest.mark.parametrize("has_offer", [True, False])
def test_unavailable_listing_hides_negotiation_but_keeps_chat(ui, status, has_offer):
    app, mocks, _ = ui
    mocks["get_conversation_details"].return_value = {**ROW, "listing_status": status}
    if has_offer:
        app, mocks = open_chat(ui)
    else:
        app.run()
        click(app, "Open chat")
    assert not app.exception
    assert not any(button.label in ("Accept", "Decline", "Counteroffer", "Send Offer") for button in app.button)
    assert any("Negotiation is unavailable" in item.value for item in list(app.info) + list(app.caption))
    assert app.chat_input and not app.chat_input[0].disabled
    if has_offer:
        assert any(item.value == "Status: Pending" for item in app.text)


def test_agreement_preview_error_does_not_block_offers_or_sending(ui):
    ui[1]["get_buy_now_agreement"].side_effect = RuntimeError("private provider detail")
    app, mocks = open_chat(ui)
    assert not app.exception
    assert any(item.value == "Status: Pending" for item in app.text)
    assert any(button.label == "Accept" for button in app.button)
    mocks["get_buy_now_agreement"].assert_not_called()
    assert not any("private provider detail" in item.value for item in app.caption)
    app.chat_input[0].set_value("Still working").run()
    assert mocks["send_message"].call_args.args[1] == "Still working"
    assert not any(button.label.startswith("Buy Now") and not button.disabled for button in app.button)


@pytest.mark.parametrize("has_offer", [True, False])
def test_failed_availability_check_keeps_chat_and_recovers(ui, monkeypatch, has_offer):
    # Use the real details method with only transport/identity mocked, so the
    # failure travels through the repository to the actual Streamlit page.
    monkeypatch.setattr(repository, "_actor", lambda: 7)
    monkeypatch.setattr(repository, "_authorized", lambda cid, actor: dict(ROW))
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"name": ROW["other_name"]})
    lookup = MagicMock(side_effect=RuntimeError("private availability response"))
    monkeypatch.setattr(database, "get_listing", lookup)
    monkeypatch.setattr(repository, "get_conversation_details", REAL_CONVERSATION_DETAILS)
    app, mocks, _ = ui
    mocks["get_chat_events"].return_value = ([OFFER] if has_offer else []) + [{
        "id": 1, "type": "message", "sender_id": 8, "body": "Existing message",
        "created_at": OFFER["created_at"],
    }]
    mocks["get_offers"].return_value = [OFFER] if has_offer else []
    app.run()
    click(app, "Open chat")
    assert any("availability could not be verified" in item.value for item in app.info)
    assert any(item.value == "Existing message" for item in app.text)
    if has_offer:
        assert any(item.value == "Status: Pending" for item in app.text)
    assert not any(button.label in ("Accept", "Decline", "Counteroffer", "Send Offer") for button in app.button)
    assert not any("private availability response" in item.value for item in app.info)
    app.chat_input[0].set_value("Message during outage").run()
    assert mocks["send_message"].call_args.args[1] == "Message during outage"
    lookup.side_effect = None
    lookup.return_value = {"status": "active"}
    click(app, "Refresh chat")
    assert any(button.label == ("Accept" if has_offer else "Send Offer") for button in app.button)
