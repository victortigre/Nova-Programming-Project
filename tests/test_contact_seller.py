"""Browse -> repository -> Messages using the real app, with mocked storage."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import accounts
import browsing
import database
import deals
import messaging_repository as repository
import ui

CID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def flow(monkeypatch):
    user = SimpleNamespace(is_logged_in=True, to_dict=lambda: {
        "email": "buyer@novasbe.pt", "email_verified": True,
    })
    monkeypatch.setattr(st, "user", user)
    monkeypatch.setattr(accounts, "logged_in_user", lambda: user.to_dict())
    monkeypatch.setattr(repository, "logged_in_user", lambda: user.to_dict())
    monkeypatch.setattr(accounts, "admin_emails", lambda: [])
    monkeypatch.setattr(database, "_client", MagicMock(side_effect=AssertionError("No live access")))
    monkeypatch.setattr(database, "database_is_set_up", lambda: True)
    monkeypatch.setattr(ui, "apply_style", lambda: None)
    buyer = {"id": 7, "name": "Test buyer", "rules_accepted_at": "2026-11-20"}
    seller = {"id": 8, "name": "Test seller", "rules_accepted_at": "2026-11-20"}
    item = {"id": 10, "seller_id": 8, "title": "Stored listing", "description": "Stored description",
            "price_cents": 1234, "status": "active", "photo_paths": [],
            "category": "Furniture", "condition": "Good", "pickup_area": "Lisbon centre"}
    get_listing = MagicMock(side_effect=lambda lid: item.copy())
    monkeypatch.setattr(database, "get_listing", get_listing)
    monkeypatch.setattr(database, "get_profile", lambda email: buyer.copy())
    monkeypatch.setattr(database, "messaging_actor_profile", lambda email: buyer.copy())
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: seller.copy())
    monkeypatch.setattr(database, "listing_photo_urls", lambda paths: {})
    monkeypatch.setattr(browsing, "saved_ids", lambda *args: set())
    monkeypatch.setattr(browsing, "saved_listings", lambda *args: [])
    monkeypatch.setattr(deals, "to_do", lambda *args: {
        "sales": 0, "purchases": 0, "answer": 0, "confirm_sale": 0, "confirm_received": 0,
    })
    purchase = MagicMock()
    monkeypatch.setattr(deals, "request_to_buy", purchase)
    rows = {}

    def insert(payload):
        row = {"id": CID, **payload, "seller_id": item["seller_id"], "original_listing_id": 10,
               "listing_title_snapshot": item["title"], "listing_price_snapshot": "12.34",
               "created_at": "2026-11-20T10:00:00+00:00"}
        rows[CID] = row
        return row

    creation = MagicMock(side_effect=insert)
    monkeypatch.setattr(database, "messaging_insert_conversation", creation)
    monkeypatch.setattr(database, "messaging_conversation_for_listing", lambda *args: rows.get(CID))
    monkeypatch.setattr(database, "messaging_conversation", lambda *args: rows.get(CID))
    monkeypatch.setattr(database, "messaging_conversations", lambda *args: list(rows.values()))
    monkeypatch.setattr(database, "messaging_messages", lambda *args: [])
    # Used only when a listing disappears and Browse returns to its grid.
    monkeypatch.setattr(database, "feed_listings", lambda *args: [])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.secrets["auth"] = {"auth0": {"client_id": "test-client", "client_secret": "test-only",
        "server_metadata_url": "https://example.invalid/.well-known/openid-configuration"}}
    app.session_state["last_page"] = "browse"
    app.session_state["open_listing"] = 10
    return SimpleNamespace(app=app, user=user, buyer=buyer, seller=seller, item=item,
                           get_listing=get_listing, creation=creation, purchase=purchase, rows=rows)


def test_contact_opens_chat_on_first_visit_and_repeated_contact_reuses_it(flow):
    app = flow.app.run()
    assert not app.exception
    assert any(button.label == "Request to buy" for button in app.button)
    assert any(link.label == "Report this listing" for link in app.get("page_link"))
    app.button(key="contact-10").click().run()
    assert not app.exception
    assert app.session_state["messaging_selected"] == CID
    assert app.session_state["messaging_account"] == "buyer@novasbe.pt"
    assert app.chat_input
    assert any(item.value == "Test seller" for item in app.subheader)
    flow.creation.assert_called_once_with({"listing_id": 10, "buyer_id": 7})
    flow.purchase.assert_not_called()
    # Return to Browse with the listing selected, then contact again.
    app.switch_page("views/browse.py")
    app.session_state["last_page"] = "browse"
    app.session_state["open_listing"] = 10
    app.run()
    app.button(key="contact-10").click().run()
    assert not app.exception
    assert app.chat_input
    assert flow.creation.call_count == 1
    flow.purchase.assert_not_called()


@pytest.mark.parametrize("restriction", ["self", "blocked_seller", "blocked_buyer", "unfinished_seller", "unfinished_buyer", "logged_out", "unverified"])
def test_contact_not_shown_to_ineligible_accounts(flow, restriction, monkeypatch):
    if restriction == "self":
        flow.item["seller_id"] = 7
    elif restriction == "blocked_seller":
        flow.seller["blocked_at"] = "2026-11-20"
    elif restriction == "blocked_buyer":
        flow.buyer["blocked_at"] = "2026-11-20"
    elif restriction == "unfinished_seller":
        flow.seller["rules_accepted_at"] = None
    elif restriction == "unfinished_buyer":
        flow.buyer["rules_accepted_at"] = None
    elif restriction == "logged_out":
        flow.user.is_logged_in = False
    else:
        flow.user.to_dict = lambda: {"email": "buyer@novasbe.pt", "email_verified": False}
    # Welcome rendering is unrelated; the app still controls access to that page.
    if restriction == "unfinished_buyer":
        monkeypatch.setattr(st, "navigation", lambda *args, **kwargs: SimpleNamespace(run=lambda: None))
    flow.app.run()
    assert not flow.app.exception
    assert not any(button.label == "Contact Seller" for button in flow.app.button)
    flow.creation.assert_not_called()


def test_listing_deleted_between_display_and_contact_cannot_create_chat(flow):
    flow.app.run()
    # Detail view still loads on rerun, but the backend's fresh lookup sees deletion.
    flow.get_listing.side_effect = [flow.item.copy(), None]
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert any("no longer available" in warning.value for warning in flow.app.warning)
    flow.creation.assert_not_called()
    flow.purchase.assert_not_called()


def test_seller_blocked_between_display_and_contact_is_rechecked(flow, monkeypatch):
    flow.app.run()
    monkeypatch.setattr(database, "get_profile_by_id", MagicMock(side_effect=[
        flow.seller.copy(), {**flow.seller, "blocked_at": "2026-11-20"},
    ]))
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert any("Seller unavailable" in warning.value for warning in flow.app.warning)
    flow.creation.assert_not_called()


def test_backend_failure_is_sanitized_and_contact_can_be_retried(flow):
    flow.app.run()
    original = flow.creation.side_effect
    flow.creation.side_effect = RuntimeError("private provider response")
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert "database setup" in flow.app.error[0].value
    assert "private provider response" not in flow.app.error[0].value
    flow.creation.side_effect = original
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert flow.app.chat_input
    flow.purchase.assert_not_called()


def test_previous_accounts_pending_text_is_not_carried_into_chat(flow):
    flow.app.session_state["messaging_account"] = "another@novasbe.pt"
    flow.app.session_state["messaging_pending"] = {"body": "Private draft"}
    flow.app.run()
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert "messaging_pending" not in flow.app.session_state
    assert flow.app.chat_input


def test_contact_does_not_change_request_to_buy(flow):
    flow.app.run()
    flow.app.button(key="buy-10").click().run()
    assert not flow.app.exception
    flow.purchase.assert_called_once_with(database, 10, "buyer@novasbe.pt")
    flow.creation.assert_not_called()


def test_deleted_listing_is_not_contactable_from_detail(flow):
    flow.get_listing.return_value = None
    flow.get_listing.side_effect = None
    flow.app.run()
    assert not flow.app.exception
    assert not any(button.label == "Contact Seller" for button in flow.app.button)
    flow.creation.assert_not_called()


def test_reserved_listing_keeps_contact_without_purchase_action(flow):
    flow.item["status"] = "reserved"
    flow.app.run()
    assert not flow.app.exception
    assert not any(button.label == "Request to buy" for button in flow.app.button)
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert flow.app.chat_input
    flow.purchase.assert_not_called()


def test_sold_listing_does_not_create_new_conversation(flow):
    flow.item["status"] = "sold"
    flow.app.run()
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert any("not available for new conversations" in warning.value for warning in flow.app.warning)
    flow.creation.assert_not_called()


def test_current_accounts_pending_message_is_preserved(flow):
    flow.app.session_state["messaging_account"] = "buyer@novasbe.pt"
    pending = {"conversation_id": CID, "body": "Unconfirmed message", "id": CID}
    flow.app.session_state["messaging_pending"] = pending
    flow.app.run()
    flow.app.button(key="contact-10").click().run()
    assert not flow.app.exception
    assert flow.app.session_state["messaging_pending"] == pending
    assert flow.app.chat_input[0].disabled
