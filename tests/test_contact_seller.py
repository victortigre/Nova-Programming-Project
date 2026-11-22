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
    seller = {"id": 8, "name": "Test seller", "rules_accepted_at": "2026-11-20",
              "bank_holder": "Test seller", "iban": "PT50000201231234567890154"}
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
        "sales": 0, "purchases": 0, "answer": 0, "pay": 0, "check_payment": 0,
    })
    purchase = MagicMock()  # buying starts in the chat now (Buy Now), never from Browse
    monkeypatch.setattr(deals, "buy_now", purchase)
    rows = {}

    def insert(payload):
        row = {"id": CID, **payload, "seller_id": item["seller_id"], "original_listing_id": 10,
               "listing_title_snapshot": item["title"], "price_cents": 1234,
               "created_at": "2026-11-20T10:00:00+00:00"}
        rows[CID] = row
        return row

    creation = MagicMock(side_effect=insert)
    monkeypatch.setattr(database, "messaging_insert_conversation", creation)
    monkeypatch.setattr(database, "messaging_conversation_for_listing", lambda *args: rows.get(CID))
    monkeypatch.setattr(database, "messaging_conversation", lambda *args: rows.get(CID))
    monkeypatch.setattr(database, "messaging_conversations", lambda *args: list(rows.values()))
    monkeypatch.setattr(database, "messaging_messages", lambda *args: [])
    monkeypatch.setattr(database, "messaging_offers", lambda *args: [])
    # Used only when a listing disappears and Browse returns to its grid.
    monkeypatch.setattr(database, "feed_listings", lambda *args: [])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
    app.secrets["auth"] = {"auth0": {"client_id": "test-client", "client_secret": "test-only",
        "server_metadata_url": "https://example.invalid/.well-known/openid-configuration"}}
    app.session_state["last_page"] = "browse"
    app.session_state["open_listing"] = 10
    return SimpleNamespace(app=app, user=user, buyer=buyer, seller=seller, item=item,
                           get_listing=get_listing, creation=creation, purchase=purchase, rows=rows)


def test_contact_opens_chat_on_first_visit_and_repeated_contact_reuses_it(flow):
    app = flow.app.run()
    assert not app.exception
    assert any(button.label == "Request to Purchase" for button in app.button)
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
    assert not any(button.label == "Make an Offer" for button in flow.app.button)
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


def test_browse_buys_now_at_the_listed_price_not_request_to_purchase(flow):
    flow.app.run()
    assert not flow.app.exception
    assert not any(button.label == "Request to Purchase" for button in flow.app.button)
    assert any("Buy Now" in item.value for item in flow.app.caption)
    assert flow.app.button(key="buy-now-10").label == "Buy Now"  # at the listed price
    flow.purchase.assert_not_called()
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
    assert not any(button.label == "Request to Purchase" for button in flow.app.button)
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


def test_listing_actions_are_offer_and_contact(flow):
    app = flow.app.run()
    assert not app.exception
    labels = [b.label for b in app.button if b.key in ('offer-10', 'contact-10', 'buy-10')]
    assert labels == ["Make an Offer", "Contact Seller"]
    assert app.button(key='offer-10').proto.type == 'secondary'
    assert app.button(key='contact-10').proto.type == 'secondary'
    actions = next(c for c in app.get('flex_container') if c.key == 'listing-actions')
    columns = actions.get('column')
    assert len(columns) == 2
    assert columns[0].button[0].label == 'Make an Offer'
    assert columns[1].button[0].label == 'Contact Seller'
    flow.purchase.assert_not_called()
    flow.creation.assert_not_called()


def test_arrows_click_through_the_photos_of_a_listing(flow, monkeypatch):
    flow.item["photo_paths"] = ["a.jpg", "b.jpg", "c.jpg"]
    monkeypatch.setattr(database, "listing_photo_urls",
                        lambda paths: {path: f"https://example.invalid/{path}" for path in paths})

    def large(app):
        """The address of the large photo: the first picture on the page."""
        return [picture.url for element in app.get("image") for picture in element.proto.imgs][0]

    app = flow.app.run()
    assert not app.exception
    assert large(app) == "https://example.invalid/a.jpg"
    app.button(key="photo-next-10").click().run()
    assert large(app) == "https://example.invalid/b.jpg"
    # Going back from the first photo shows the last one.
    app.button(key="photo-back-10").click().run()
    app.button(key="photo-back-10").click().run()
    assert not app.exception
    assert large(app) == "https://example.invalid/c.jpg"
    # A click on a small photo shows that photo large.
    app.button(key="thumbpick-10-1").click().run()
    assert not app.exception
    assert large(app) == "https://example.invalid/b.jpg"
