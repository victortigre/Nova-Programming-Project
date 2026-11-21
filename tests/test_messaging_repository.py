"""No network or secrets: both identity and database client are mocked."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from postgrest.exceptions import APIError

import database
import messaging_repository as repo

CID = "11111111-1111-4111-8111-111111111111"
MID = "22222222-2222-4222-8222-222222222222"
ORIGINAL_ACTOR_PROFILE = database.messaging_actor_profile


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(database, "messaging_offers", MagicMock(return_value=[]))
    client = MagicMock()
    monkeypatch.setattr(database, "_client", lambda: client)
    user = SimpleNamespace(is_logged_in=True, to_dict=lambda: {
        "email": "student@novasbe.pt", "email_verified": True,
    })
    monkeypatch.setattr(repo.st, "user", user)
    monkeypatch.setattr(repo, "logged_in_user", lambda: user.to_dict())
    profile = MagicMock(return_value={"id": 7, "rules_accepted_at": "2026-11-20"})
    monkeypatch.setattr(database, "messaging_actor_profile", profile)
    row = {"id": CID, "buyer_id": 7, "seller_id": 8}
    conversation = MagicMock(return_value=row)
    monkeypatch.setattr(database, "messaging_conversation", conversation)
    return client, user, profile, row, conversation


@pytest.mark.parametrize("operation", [
    lambda: repo.list_conversations(),
    lambda: repo.get_inbox(),
    lambda: repo.get_conversation_details(CID),
    lambda: repo.require_access(),
    lambda: repo.get_conversation(CID),
    lambda: repo.get_messages(CID),
    lambda: repo.send_message(CID, "Hi", MID),
    lambda: repo.get_or_create_conversation(10),
])
@pytest.mark.parametrize("identity", ["logged_out", "unverified", "wrong_domain"])
def test_all_operations_reject_invalid_identity_before_database(context, operation, identity):
    client, user, profile, _, conversation = context
    if identity == "logged_out":
        user.is_logged_in = False
    else:
        user.to_dict = lambda: {
            "email": "other@example.com" if identity == "wrong_domain" else "student@novasbe.pt",
            "email_verified": identity != "unverified",
        }
    with pytest.raises(ValueError, match="sign in"):
        operation()
    profile.assert_not_called()
    conversation.assert_not_called()
    client.table.assert_not_called()


def test_missing_profile(context):
    context[2].return_value = None
    with pytest.raises(ValueError, match="profile"):
        repo.list_conversations()
    context[0].table.assert_not_called()


@pytest.mark.parametrize("operation", [
    lambda: repo.get_conversation(CID),
    lambda: repo.get_messages(CID),
    lambda: repo.send_message(CID, "Hi", MID),
])
@pytest.mark.parametrize("row", [None, {"buyer_id": 9, "seller_id": 8}])
def test_missing_or_foreign_conversation_cannot_read_or_write(context, operation, row):
    context[4].return_value = row
    with pytest.raises(ValueError, match="Conversation unavailable"):
        operation()
    context[0].table.assert_not_called()


def test_send_derives_actor_and_validates_text(context, monkeypatch):
    insert = MagicMock(side_effect=lambda payload: {"id": 1, **payload})
    monkeypatch.setattr(database, "messaging_insert_message", insert)
    saved = repo.send_message(CID, "  Hello!  ", MID)
    assert saved["sender_id"] == 7
    assert saved["body"] == "Hello!"
    context[2].assert_called_once_with("student@novasbe.pt")
    context[4].assert_called_once_with(CID, 7)
    with pytest.raises(ValueError):
        repo.send_message(CID, "  ", MID)
    assert insert.call_count == 1


def test_actor_is_resolved_again_on_each_operation(context):
    repo.get_conversation(CID)
    context[2].return_value = {"id": 99, "rules_accepted_at": "2026-11-20"}
    with pytest.raises(ValueError, match="Conversation unavailable"):
        repo.get_conversation(CID)


def test_history_page_is_chronological(context, monkeypatch):
    history = MagicMock(return_value=[{"id": 2}, {"id": 1}])
    monkeypatch.setattr(database, "messaging_messages", history)
    assert repo.get_messages(CID, limit=2, offset=4) == [{"id": 1}, {"id": 2}]
    history.assert_called_once_with(CID, 2, 4)
    with pytest.raises(ValueError):
        repo.get_messages(CID, limit=1000)


def test_inbox_rechecks_membership(context, monkeypatch):
    query = MagicMock(return_value=[context[3]])
    monkeypatch.setattr(database, "messaging_conversations", query)
    assert repo.list_conversations() == [context[3]]
    query.assert_called_once_with(7)
    query.return_value = [{"buyer_id": 8, "seller_id": 9}]
    with pytest.raises(ValueError):
        repo.list_conversations()


def test_retry_must_match_sender_and_body(context, monkeypatch):
    monkeypatch.setattr(database, "messaging_insert_message", lambda payload: {
        **payload, "sender_id": 8,
    })
    with pytest.raises(ValueError, match="retry"):
        repo.send_message(CID, "Hi", MID)


@pytest.mark.parametrize("code,recovers", [("23505", True), ("42501", False)])
def test_transport_only_recovers_unique_conflicts(context, code, recovers):
    client = context[0]
    payload = {"conversation_id": CID, "client_message_id": MID, "sender_id": 7, "body": "Hi"}
    client.table.return_value.insert.return_value.execute.side_effect = APIError({
        "code": code, "message": "mock error", "details": None, "hint": None,
    })
    query = client.table.return_value.select.return_value
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = [payload]
    if recovers:
        assert database.messaging_insert_message(payload) == payload
    else:
        with pytest.raises(APIError):
            database.messaging_insert_message(payload)
        client.table.return_value.select.assert_not_called()


def test_transport_filters_inbox_by_actor(context):
    client = context[0]
    query = client.table.return_value.select.return_value
    query.or_.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.range.return_value = query
    query.execute.return_value.data = []
    assert database.messaging_conversations(7) == []
    client.table.assert_called_once_with("conversations")
    query.or_.assert_called_once_with("buyer_id.eq.7,seller_id.eq.7")


def test_transport_scopes_history_and_bounds_page(context):
    client = context[0]
    query = client.table.return_value.select.return_value
    for method in ("eq", "order", "range"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = []
    assert database.messaging_messages(CID, 20, 40) == []
    query.eq.assert_called_once_with("conversation_id", CID)
    query.range.assert_called_once_with(40, 59)
    assert query.order.call_count == 2


def test_transport_conversation_create_conflict_fetches_existing(context):
    client = context[0]
    payload = {"listing_id": 10, "buyer_id": 7}
    client.table.return_value.insert.return_value.execute.side_effect = APIError({
        "code": "23505", "message": "mock unique conflict", "details": None, "hint": None,
    })
    query = client.table.return_value.select.return_value
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = [payload]
    assert database.messaging_insert_conversation(payload) == payload
    assert query.eq.call_args_list[0].args == ("original_listing_id", 10)
    assert query.eq.call_args_list[1].args == ("buyer_id", 7)


def test_inbox_sorts_by_message_activity_and_uses_profile_name(context, monkeypatch):
    first = {**context[3], "created_at": "2026-11-18T10:00:00+00:00"}
    second = {**first, "id": MID, "created_at": "2026-11-19T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_conversations", lambda actor: [second, first])
    monkeypatch.setattr(database, "get_profile_by_id", lambda profile_id: {
        "id": profile_id, "name": "Other participant", "email": "not-returned@novasbe.pt",
    })
    latest = {"id": 12, "created_at": "2026-11-20T10:00:00+00:00", "body": "Newest"}
    monkeypatch.setattr(database, "messaging_messages", lambda cid, limit, offset: [latest] if cid == CID else [])
    rows = repo.get_inbox()
    assert [row["id"] for row in rows] == [CID, MID]
    assert rows[0]["last_message"] == latest
    assert rows[1]["last_message"] is None
    assert rows[0]["other_name"] == "Other participant"
    assert "email" not in rows[0]


@pytest.mark.parametrize("operation", [
    lambda: repo.get_inbox(), lambda: repo.get_conversation_details(CID),
    lambda: repo.get_messages(CID), lambda: repo.send_message(CID, "Hello", MID),
    lambda: repo.get_or_create_conversation(10),
])
@pytest.mark.parametrize("restriction", ["blocked", "onboarding"])
def test_account_restrictions_apply_at_each_operation(context, operation, restriction):
    context[2].return_value = {
        "id": 7, "blocked_at": "2026-11-20" if restriction == "blocked" else None,
        "rules_accepted_at": "2026-11-20" if restriction == "blocked" else None,
    }
    with pytest.raises(ValueError, match="blocked|Welcome"):
        operation()
    context[4].assert_not_called()
    context[0].table.assert_not_called()


def test_repository_uses_refreshed_authenticated_identity(context, monkeypatch):
    context[1].to_dict = lambda: {"email": "student@novasbe.pt", "email_verified": False}
    monkeypatch.setattr(repo, "logged_in_user", lambda: {
        "email": "student@novasbe.pt", "email_verified": True,
    })
    assert repo.get_conversation(CID)["id"] == CID
    context[2].assert_called_once_with("student@novasbe.pt")


def test_fresh_block_rejects_next_operation_without_using_display_cache(context, monkeypatch):
    cached = MagicMock(return_value={"id": 7, "rules_accepted_at": "yes", "blocked_at": None})
    monkeypatch.setattr(database, "get_profile", cached)
    assert repo.get_conversation(CID)["id"] == CID
    context[2].return_value = {"id": 7, "rules_accepted_at": "yes", "blocked_at": "now"}
    with pytest.raises(ValueError, match="blocked"):
        repo.get_conversation(CID)
    assert context[2].call_count == 2
    assert context[4].call_count == 1
    cached.assert_not_called()


def test_authorization_transport_uses_email_filter_and_no_cache(context):
    client = context[0]
    query = client.table.return_value.select.return_value
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = [{"id": 7, "email": "student@novasbe.pt"}]
    # Call the underlying transport, not the repository fixture's mock.
    assert ORIGINAL_ACTOR_PROFILE("student@novasbe.pt")["id"] == 7
    query.execute.return_value.data = [{"id": 7, "blocked_at": "now"}]
    assert ORIGINAL_ACTOR_PROFILE("student@novasbe.pt")["blocked_at"] == "now"
    assert query.execute.call_count == 2
    query.eq.assert_called_with("email", "student@novasbe.pt")


@pytest.mark.parametrize("mismatch", [{"body": "Changed"}, {"sender_id": 8}, {"conversation_id": MID}])
def test_message_retry_cannot_change_original_payload(context, monkeypatch, mismatch):
    monkeypatch.setattr(database, "messaging_insert_message", lambda payload: {**payload, **mismatch})
    with pytest.raises(ValueError, match="retry"):
        repo.send_message(CID, "Original", MID)


def test_successful_message_retry_returns_original_row(context, monkeypatch):
    saved = {"id": 12, "conversation_id": CID, "sender_id": 7,
             "body": "Original", "client_message_id": MID}
    insert = MagicMock(return_value=saved)
    monkeypatch.setattr(database, "messaging_insert_message", insert)
    assert repo.send_message(CID, " Original ", MID) == saved
    assert repo.send_message(CID, "Original", MID) == saved
    assert insert.call_args_list[0] == insert.call_args_list[1]


@pytest.mark.parametrize("table", ["messages", "conversations"])
def test_unmatched_unique_conflict_is_not_treated_as_success(context, table):
    client = context[0]
    error = APIError({"code": "23505", "message": "Other unique constraint",
                      "details": None, "hint": None})
    client.table.return_value.insert.return_value.execute.side_effect = error
    query = client.table.return_value.select.return_value
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = []
    with pytest.raises(APIError) as raised:
        if table == "messages":
            database.messaging_insert_message({"conversation_id": CID, "client_message_id": MID})
        else:
            database.messaging_insert_conversation({"listing_id": 10, "buyer_id": 7})
    assert raised.value is error


@pytest.mark.parametrize("status,response", [("pending", None), ("superseded", "2026-11-22T10:00:00+00:00"),
                                            ("accepted", "2026-11-22T10:00:00+00:00"),
                                            ("declined", "2026-11-22T10:00:00+00:00")])
def test_inbox_counts_offer_creation_and_responses(context, monkeypatch, status, response):
    first = {**context[3], "created_at": "2026-11-18T10:00:00+00:00"}
    second = {**first, "id": MID}
    monkeypatch.setattr(database, "messaging_conversations", lambda actor: [second, first])
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"name": "Participant"})
    monkeypatch.setattr(database, "messaging_messages", lambda cid, *args: [] if cid == CID else [
        {"id": 1, "body": "Hello", "created_at": "2026-11-20T09:00:00+00:00"}])
    offer = {"id": MID, "status": status, "amount_cents": 2500, "sender_id": 8,
             "parent_offer_id": CID, "created_at": "2026-11-20T10:00:00+00:00", "responded_at": response}
    monkeypatch.setattr(database, "messaging_offers", lambda cid, *args: [offer] if cid == CID else [])
    rows = repo.get_inbox()
    assert [row["id"] for row in rows] == [CID, MID]
    assert rows[0]["last_activity"]["type"] == "offer"
    assert rows[0]["activity_at"] == (response or offer["created_at"])
    assert rows[0]["last_message"] is None


@pytest.mark.parametrize("status", ["active", "reserved", "sold", None])
def test_chat_details_reads_current_listing_status(context, monkeypatch, status):
    context[3]["listing_id"] = 10
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"name": "Participant"})
    monkeypatch.setattr(database, "get_listing", lambda lid: {"status": status} if status else None)
    assert repo.get_conversation_details(CID)["listing_status"] == (status or "unavailable")


def test_listing_check_failure_preserves_authorized_chat_and_recovers(context, monkeypatch):
    context[3]["listing_id"] = 10
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"name": "Participant"})
    lookup = MagicMock(side_effect=RuntimeError("private provider details"))
    monkeypatch.setattr(database, "get_listing", lookup)
    row = repo.get_conversation_details(CID)
    assert row["listing_status"] == "unknown"
    assert row["id"] == CID and row["own_profile_id"] == 7
    assert "private provider details" not in str(row)
    lookup.side_effect = None
    lookup.return_value = {"status": "active"}
    assert repo.get_conversation_details(CID)["listing_status"] == "active"


def test_listing_fallback_does_not_bypass_membership(context, monkeypatch):
    context[4].return_value = None
    lookup = MagicMock(side_effect=RuntimeError("Unavailable"))
    monkeypatch.setattr(database, "get_listing", lookup)
    with pytest.raises(ValueError, match="Conversation unavailable"):
        repo.get_conversation_details(CID)
    lookup.assert_not_called()
