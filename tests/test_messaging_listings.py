"""Real listing integration with mocked storage; never connects to Supabase."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from postgrest.exceptions import APIError

import database
import messaging_repository as repo

CID = "11111111-1111-4111-8111-111111111111"
MID = "22222222-2222-4222-8222-222222222222"
ORIGINAL_INSERT = database.messaging_insert_conversation


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(database, "_client", MagicMock(side_effect=AssertionError("No live database")))
    monkeypatch.setattr(repo.st, "user", SimpleNamespace(is_logged_in=True))
    monkeypatch.setattr(repo, "logged_in_user", lambda: {
        "email": "buyer@novasbe.pt", "email_verified": True,
    })
    actor = MagicMock(return_value={"id": 7, "rules_accepted_at": "2026-11-20"})
    seller = MagicMock(return_value={"id": 8, "rules_accepted_at": "2026-11-20"})
    listing = MagicMock(return_value={"id": 10, "seller_id": 8, "title": "Stored title",
                                     "price_cents": 1234, "status": "active"})
    existing = MagicMock(return_value=None)
    row = {"id": CID, "buyer_id": 7, "seller_id": 8, "listing_id": 10,
           "original_listing_id": 10, "listing_title_snapshot": "Stored title",
           "listing_price_snapshot": "12.34"}
    insert = MagicMock(return_value=row)
    for name, mock in (("messaging_actor_profile", actor), ("get_profile_by_id", seller),
                       ("get_listing", listing), ("messaging_conversation_for_listing", existing),
                       ("messaging_insert_conversation", insert)):
        monkeypatch.setattr(database, name, mock)
    return SimpleNamespace(actor=actor, seller=seller, listing=listing,
                           existing=existing, insert=insert, row=row)


def test_create_uses_login_and_only_real_listing_id(store):
    assert repo.get_or_create_conversation(10) == store.row
    store.actor.assert_called_once_with("buyer@novasbe.pt")
    store.listing.assert_called_once_with(10)
    store.seller.assert_called_once_with(8)
    # No UI-supplied title, price or seller: the database trigger supplies them.
    store.insert.assert_called_once_with({"listing_id": 10, "buyer_id": 7})


def test_repeated_contact_reuses_original_snapshot(store):
    store.existing.return_value = store.row
    store.listing.return_value = {**store.listing.return_value, "title": "Edited", "price_cents": 9999}
    for _ in range(2):
        result = repo.get_or_create_conversation(10)
        assert result["listing_title_snapshot"] == "Stored title"
        assert result["listing_price_snapshot"] == "12.34"
    store.insert.assert_not_called()


@pytest.mark.parametrize("listing_id", [None, True, False, "10", 0, -1, 10.0])
def test_invalid_listing_id_cannot_query_or_write(store, listing_id):
    with pytest.raises(ValueError):
        repo.get_or_create_conversation(listing_id)
    store.listing.assert_not_called()
    store.insert.assert_not_called()


def test_deleted_listing_cannot_start_or_reopen_via_listing(store):
    store.listing.return_value = None
    store.existing.return_value = {**store.row, "listing_id": None}
    with pytest.raises(ValueError, match="no longer available"):
        repo.get_or_create_conversation(10)
    store.existing.assert_not_called()
    store.insert.assert_not_called()


def test_self_messaging_is_rejected(store):
    store.seller.return_value = {"id": 7, "rules_accepted_at": "2026-11-20"}
    with pytest.raises(ValueError, match="yourself"):
        repo.get_or_create_conversation(10)
    store.insert.assert_not_called()


@pytest.mark.parametrize("seller", [None, {"id": 8}, {"id": 8, "rules_accepted_at": "yes", "blocked_at": "yes"}])
def test_unavailable_seller_cannot_receive_new_conversation(store, seller):
    store.seller.return_value = seller
    with pytest.raises(ValueError, match="Seller unavailable"):
        repo.get_or_create_conversation(10)
    store.insert.assert_not_called()


@pytest.mark.parametrize("status", ["active", "reserved"])
def test_active_and_reserved_listings_allow_contact(store, status):
    store.listing.return_value["status"] = status
    assert repo.get_or_create_conversation(10)["id"] == CID


def test_sold_listing_cannot_start_new_chat_but_existing_chat_is_reused(store):
    store.listing.return_value["status"] = "sold"
    with pytest.raises(ValueError, match="new conversations"):
        repo.get_or_create_conversation(10)
    store.insert.assert_not_called()
    store.existing.return_value = store.row
    assert repo.get_or_create_conversation(10) == store.row


def test_raced_duplicate_insert_returns_same_conversation(store, monkeypatch):
    # Exercise the real transport through the repository, replacing only its
    # client. Another request inserts after the initial lookup.
    monkeypatch.setattr(database, "messaging_insert_conversation", ORIGINAL_INSERT)
    client = MagicMock()
    monkeypatch.setattr(database, "_client", lambda: client)
    client.table.return_value.insert.return_value.execute.side_effect = APIError({
        "code": "23505", "message": "Duplicate buyer/listing", "details": None, "hint": None,
    })
    query = client.table.return_value.select.return_value
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = [store.row]
    assert repo.get_or_create_conversation(10) == store.row
    client.table.return_value.insert.assert_called_once_with({"listing_id": 10, "buyer_id": 7})
    assert query.eq.call_args_list[0].args == ("original_listing_id", 10)
    assert query.eq.call_args_list[1].args == ("buyer_id", 7)


@pytest.mark.parametrize("field,value", [("buyer_id", 9), ("seller_id", 9), ("original_listing_id", 11)])
def test_existing_result_must_match_original_listing_and_participants(store, field, value):
    store.existing.return_value = {**store.row, field: value}
    with pytest.raises(ValueError):
        repo.get_or_create_conversation(10)
    store.insert.assert_not_called()


@pytest.mark.parametrize("actor_id", [7, 8])
def test_both_participants_can_read_and_send_after_deletion(store, monkeypatch, actor_id):
    store.actor.return_value = {"id": actor_id, "rules_accepted_at": "2026-11-20"}
    deleted = {**store.row, "listing_id": None}
    monkeypatch.setattr(database, "messaging_conversation", lambda cid, actor: deleted)
    history = [{"id": 1, "body": "Before deletion", "sender_id": 7}]
    monkeypatch.setattr(database, "messaging_messages", lambda *args: history)
    monkeypatch.setattr(database, "messaging_insert_message", lambda payload: {"id": 2, **payload})
    assert repo.get_messages(CID) == history
    assert repo.send_message(CID, "After deletion", MID)["sender_id"] == actor_id
    store.listing.assert_not_called()


def test_outsider_cannot_access_deleted_chat(store, monkeypatch):
    store.actor.return_value = {"id": 99, "rules_accepted_at": "2026-11-20"}
    monkeypatch.setattr(database, "messaging_conversation", lambda *args: {**store.row, "listing_id": None})
    for operation in (lambda: repo.get_messages(CID), lambda: repo.send_message(CID, "Hi", MID)):
        with pytest.raises(ValueError, match="unavailable"):
            operation()


def test_deletion_race_propagates_database_rejection_without_fallback(store):
    store.insert.side_effect = APIError({"code": "23514", "message": "Listing no longer available.",
                                       "details": None, "hint": None})
    with pytest.raises(APIError):
        repo.get_or_create_conversation(10)
    store.insert.assert_called_once()


def test_ui_cannot_supply_participant_or_snapshot_overrides(store):
    with pytest.raises(TypeError):
        repo.get_or_create_conversation(10, buyer_id=99, seller_id=100, title="Spoofed")
    store.insert.assert_not_called()
