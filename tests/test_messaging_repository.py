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


def inbox_row(conversation, other_name="Participant", last_message=None,
              last_offer=None, newest_offer=None):
    """One row as the messaging_inbox database function returns it."""
    return {"conversation": conversation, "other_name": other_name, "last_message": last_message,
            "last_offer": last_offer, "newest_offer": newest_offer}


def test_inbox_sorts_by_message_activity_and_uses_profile_name(context, monkeypatch):
    first = {**context[3], "created_at": "2026-11-18T10:00:00+00:00"}
    second = {**first, "id": MID, "created_at": "2026-11-19T10:00:00+00:00"}
    latest = {"id": 12, "created_at": "2026-11-20T10:00:00+00:00", "body": "Newest"}
    # MID has no message but an earlier offer, so it still appears (and sorts below CID)
    # while keeping its last_message None; CID's newer message sorts it to the top.
    earlier_offer = {"id": 1, "status": "pending", "amount_cents": 1000, "sender_id": 8,
                     "parent_offer_id": None, "created_at": "2026-11-19T10:00:00+00:00",
                     "responded_at": None}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [
        inbox_row(second, "Other participant", last_offer=earlier_offer),
        inbox_row(first, "Other participant", last_message=latest),
    ])
    rows = repo.get_inbox()
    assert [row["id"] for row in rows] == [CID, MID]
    assert rows[0]["last_message"] == latest
    assert rows[1]["last_message"] is None
    assert rows[0]["other_name"] == "Other participant"
    assert "email" not in rows[0]


def test_inbox_flags_unread_chats(context, monkeypatch):
    first = {**context[3], "created_at": "2026-11-20T10:00:00+00:00"}
    second = {**first, "id": MID}
    message = {"id": 1, "sender_id": 8, "body": "Hi", "created_at": "2026-11-20T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [
        inbox_row(first, last_message=message), inbox_row(second, last_message=message),
    ])
    monkeypatch.setattr(database, "messaging_unread_conversations", lambda actor: [CID])
    rows = {row["id"]: row for row in repo.get_inbox()}
    assert rows[CID]["unread"] is True
    assert rows[MID]["unread"] is False


def test_inbox_still_loads_when_read_tracking_is_missing(context, monkeypatch):
    row = {**context[3], "created_at": "2026-11-20T10:00:00+00:00"}
    message = {"id": 1, "sender_id": 8, "body": "Hi", "created_at": "2026-11-20T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [inbox_row(row, last_message=message)])
    monkeypatch.setattr(database, "messaging_unread_conversations",
                        MagicMock(side_effect=RuntimeError("function not set up yet")))
    rows = repo.get_inbox()  # must not raise
    assert rows[0]["unread"] is False


def _inbox_rows(context, monkeypatch):
    """Two chats (CID and MID) in the inbox, as in test_inbox_flags_unread_chats."""
    first = {**context[3], "created_at": "2026-11-20T10:00:00+00:00"}
    second = {**first, "id": MID}
    message = {"id": 1, "sender_id": 8, "body": "Hi", "created_at": "2026-11-20T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [
        inbox_row(first, last_message=message), inbox_row(second, last_message=message),
    ])
    return repo.get_inbox()


def test_inbox_counts_how_many_are_new(context, monkeypatch):
    monkeypatch.setattr(database, "messaging_unread_conversations", lambda actor: [CID])
    monkeypatch.setattr(database, "messaging_unread_counts", lambda actor: {CID: 3})
    rows = {row["id"]: row for row in _inbox_rows(context, monkeypatch)}
    assert rows[CID]["unread_count"] == 3
    assert rows[MID]["unread_count"] == 0


def test_inbox_counts_fall_back_to_one_without_the_counting_function(context, monkeypatch):
    monkeypatch.setattr(database, "messaging_unread_conversations", lambda actor: [CID])

    def missing(actor):
        raise RuntimeError("function not in the database yet")
    monkeypatch.setattr(database, "messaging_unread_counts", missing)
    rows = {row["id"]: row for row in _inbox_rows(context, monkeypatch)}
    assert rows[CID]["unread_count"] == 1


def test_unread_conversations_returns_the_set(context, monkeypatch):
    monkeypatch.setattr(database, "messaging_unread_conversations", lambda actor: [CID, MID, CID])
    assert repo.unread_conversations() == {CID, MID}


def test_mark_read_records_for_the_signed_in_student(context, monkeypatch):
    marker = MagicMock()
    monkeypatch.setattr(database, "messaging_mark_read", marker)
    repo.mark_read(CID)
    marker.assert_called_once_with(CID, 7)  # (conversation id, the actor's profile id)


def test_mark_read_refuses_a_chat_you_are_not_in(context, monkeypatch):
    monkeypatch.setattr(database, "messaging_conversation",
                        lambda conversation_id, actor: {"id": CID, "buyer_id": 8, "seller_id": 9})
    marker = MagicMock()
    monkeypatch.setattr(database, "messaging_mark_read", marker)
    with pytest.raises(ValueError):
        repo.mark_read(CID)
    marker.assert_not_called()


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
    offer = {"id": MID, "status": status, "amount_cents": 2500, "sender_id": 8,
             "parent_offer_id": CID, "created_at": "2026-11-20T10:00:00+00:00", "responded_at": response}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [
        inbox_row(second, last_message={"id": 1, "body": "Hello", "created_at": "2026-11-20T09:00:00+00:00"}),
        inbox_row(first, last_offer=offer, newest_offer=offer),
    ])
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


@pytest.mark.parametrize("actor,other", [(7, 8), (8, 7)])
def test_chat_photo_belongs_to_authenticated_participant_other_side(context, monkeypatch, actor, other):
    context[2].return_value["id"] = actor
    context[3]["listing_id"] = 10
    profile = MagicMock(return_value={"id": other, "name": "Other participant", "photo_path": f"profile-{other}.jpg"})
    photo = MagicMock(return_value=f"https://photos.example.invalid/{other}.jpg")
    monkeypatch.setattr(database, "get_profile_by_id", profile)
    monkeypatch.setattr(database, "photo_url", photo)
    monkeypatch.setattr(database, "get_listing", lambda lid: {"status": "active"})
    row = repo.get_conversation_details(CID)
    assert row["own_profile_id"] == actor
    assert row["other_photo_url"] == f"https://photos.example.invalid/{other}.jpg"
    profile.assert_called_once_with(other)
    photo.assert_called_once_with(f"profile-{other}.jpg")


@pytest.mark.parametrize("profile", [None, {"name": "Participant"}, {"name": "Participant", "photo_path": None}])
def test_chat_missing_photo_uses_fallback_without_storage_lookup(context, monkeypatch, profile):
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: profile)
    photo = MagicMock(side_effect=AssertionError("No photo to sign"))
    monkeypatch.setattr(database, "photo_url", photo)
    assert repo.get_conversation_details(CID)["other_photo_url"] is None
    photo.assert_not_called()


def test_chat_photo_signing_failure_is_nonblocking_and_sanitized(context, monkeypatch):
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"name": "Participant", "photo_path": "profile.jpg"})
    monkeypatch.setattr(database, "photo_url", MagicMock(side_effect=RuntimeError("private provider detail")))
    row = repo.get_conversation_details(CID)
    assert row["other_photo_url"] is None
    assert row["other_name"] == "Participant"
    assert "private provider detail" not in str(row)


def test_unauthorized_conversation_never_loads_profile_photo(context, monkeypatch):
    context[4].return_value = {"buyer_id": 90, "seller_id": 91}
    photo = MagicMock()
    profile = MagicMock()
    monkeypatch.setattr(database, "photo_url", photo)
    monkeypatch.setattr(database, "get_profile_by_id", profile)
    with pytest.raises(ValueError, match="Conversation unavailable"):
        repo.get_conversation_details(CID)
    photo.assert_not_called()
    profile.assert_not_called()


def test_one_authenticated_profile_has_buying_and_selling_conversations(context, monkeypatch):
    buying = {"id": CID, "buyer_id": 7, "seller_id": 8, "created_at": "2026-11-20T10:00:00+00:00"}
    selling = {"id": MID, "buyer_id": 9, "seller_id": 7, "created_at": "2026-11-20T11:00:00+00:00"}
    buy_msg = {"id": 1, "sender_id": 8, "body": "Hi", "created_at": "2026-11-20T10:00:00+00:00"}
    sell_msg = {"id": 2, "sender_id": 9, "body": "Hi", "created_at": "2026-11-20T11:00:00+00:00"}
    query = MagicMock(return_value=[inbox_row(buying, "Seller", last_message=buy_msg),
                                    inbox_row(selling, "Buyer", last_message=sell_msg)])
    monkeypatch.setattr(database, "messaging_inbox", query)
    per_chat = MagicMock(side_effect=AssertionError("The inbox must not ask chat by chat"))
    for name in ("messaging_conversations", "messaging_messages", "messaging_offers", "get_profile_by_id"):
        monkeypatch.setattr(database, name, per_chat)
    photo = MagicMock()
    monkeypatch.setattr(database, "photo_url", photo)
    rows = repo.get_inbox()
    assert [(r["id"], r["other_name"], r["own_profile_id"]) for r in rows] == [(MID, "Buyer", 7), (CID, "Seller", 7)]
    query.assert_called_once_with(7)  # One request for the whole inbox.
    photo.assert_not_called()  # No photo-signing requests per Inbox row.


def test_inbox_rejects_a_row_the_student_is_not_part_of(context, monkeypatch):
    stranger = {"id": CID, "buyer_id": 90, "seller_id": 91, "created_at": "2026-11-20T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [inbox_row(stranger)])
    with pytest.raises(ValueError):
        repo.get_inbox()


def test_inbox_hides_empty_conversations_with_no_message_or_offer(context, monkeypatch):
    # A bare "Buy Now" reservation with no chat activity yet: no last_message and
    # no last_offer. It must not appear in the inbox until there is real activity.
    empty = {**context[3], "created_at": "2026-11-20T10:00:00+00:00"}
    active = {**empty, "id": MID}
    message = {"id": 1, "sender_id": 8, "body": "Hi", "created_at": "2026-11-20T11:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [
        inbox_row(empty),  # last_message=None and last_offer=None -> hidden
        inbox_row(active, last_message=message),  # has activity -> shown
    ])
    monkeypatch.setattr(database, "messaging_unread_conversations", lambda actor: [])
    rows = repo.get_inbox()
    assert [row["id"] for row in rows] == [MID]
    assert all(row["id"] != CID for row in rows)


def test_inbox_row_without_a_profile_name_still_shows(context, monkeypatch):
    row = {**context[3], "created_at": "2026-11-20T10:00:00+00:00"}
    message = {"id": 1, "sender_id": 8, "body": "Hi", "created_at": "2026-11-20T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox", lambda actor: [inbox_row(row, None, last_message=message)])
    assert repo.get_inbox()[0]["other_name"] == "Profile unavailable"


def test_offer_notices_use_the_one_inbox_request(context, monkeypatch):
    mine = {**context[3], "listing_title_snapshot": "Bike", "listing_id": 10}
    offer = {"id": MID, "status": "pending", "amount_cents": 4500, "sender_id": 8,
             "parent_offer_id": None, "created_at": "2026-11-20T10:00:00+00:00"}
    query = MagicMock(return_value=[inbox_row(mine, "Seller name", newest_offer=offer)])
    monkeypatch.setattr(database, "messaging_inbox", query)
    names = MagicMock(side_effect=AssertionError("The name came with the inbox row"))
    monkeypatch.setattr(database, "names_of", names)
    on_sale = {"status": "active"}
    monkeypatch.setattr(database, "get_listing", lambda listing_id: on_sale)
    assert repo.offers_to_answer() == [{
        "conversation_id": CID, "amount_cents": 4500, "counter": False, "sender_id": 8,
        "listing_title": "Bike", "created_at": offer["created_at"], "sender_name": "Seller name",
    }]
    query.assert_called_once_with(7)
    # Sold in the meantime: the offer can't be answered, so no notice for it.
    on_sale["status"] = "sold"
    assert repo.offers_to_answer() == []


def test_one_page_load_checks_the_student_and_chat_once(context, monkeypatch):
    _, _, profile, _, conversation = context
    context[2].return_value = {"id": 7, "name": "Me", "rules_accepted_at": "yes"}
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"id": pid, "name": "Seller"})
    monkeypatch.setattr(database, "get_listing", lambda lid: None)
    offer = {"id": MID, "status": "pending", "amount_cents": 900, "sender_id": 8,
             "created_at": "2026-11-20T10:00:00+00:00"}
    offers = MagicMock(return_value=[offer])
    monkeypatch.setattr(database, "messaging_offers", offers)
    monkeypatch.setattr(database, "messaging_messages", lambda *args: [
        {"id": 1, "sender_id": 7, "body": "Hi", "created_at": "2026-11-20T09:00:00+00:00"}])
    names = MagicMock(side_effect=AssertionError("Both names are already known"))
    monkeypatch.setattr(database, "names_of", names)
    with repo.checked_once():
        repo.require_access()
        repo.get_conversation_details(CID)
        events = repo.get_chat_events(CID, limit=50)
        latest = repo.get_offers(CID, limit=1)
    assert profile.call_count == 1
    assert conversation.call_count == 1
    offers.assert_called_once_with(CID, 50, 0)  # get_offers reused the loaded offers.
    assert latest == [offer]
    assert {e["sender_id"]: e["sender_name"] for e in events} == {7: "Me", 8: "Seller"}
    # The next page load asks again, so a block counts on the very next click.
    with repo.checked_once():
        repo.require_access()
    assert profile.call_count == 2


def test_sending_always_rechecks_the_student_even_in_a_page_load(context, monkeypatch):
    profile = context[2]
    monkeypatch.setattr(database, "messaging_insert_message", lambda payload: payload)
    with repo.checked_once():
        repo.require_access()
        profile.return_value = {"id": 7, "rules_accepted_at": "yes", "blocked_at": "now"}
        with pytest.raises(ValueError, match="blocked"):
            repo.send_message(CID, "Hello", MID)


def test_get_offers_asks_again_when_more_are_wanted_than_were_loaded(context, monkeypatch):
    offers = MagicMock(return_value=[{"id": i} for i in range(5)])
    monkeypatch.setattr(database, "messaging_offers", offers)
    with repo.checked_once():
        repo.get_offers(CID, limit=5)
        repo.get_offers(CID, limit=10)
    assert offers.call_count == 2


@pytest.mark.parametrize('actor,other', [(7, 8), (8, 7)])
def test_optional_inbox_photos_use_other_participant_once_per_load(context, monkeypatch, actor, other):
    context[2].return_value['id'] = actor
    first = {**context[3], 'created_at': '2026-11-20T10:00:00+00:00'}
    message = {'id': 1, 'sender_id': other, 'body': 'Hi', 'created_at': '2026-11-20T10:00:00+00:00'}
    monkeypatch.setattr(database, 'messaging_inbox', lambda aid: [
        inbox_row(first, last_message=message), inbox_row({**first, 'id': MID}, last_message=message)])
    monkeypatch.setattr(database, 'messaging_unread_conversations', lambda aid: [CID])
    # Two chats with the same student: one request for where the photos are
    # stored and one for their links, not one per chat.
    lookup = MagicMock(return_value={other: 'stored-photo.jpg'})
    sign = MagicMock(return_value={'stored-photo.jpg': 'https://photos.example.invalid/photo.jpg'})
    monkeypatch.setattr(database, 'photo_paths_of', lookup)
    monkeypatch.setattr(database, 'photo_urls', sign)
    rows = repo.get_inbox(include_photos=True)
    assert all(row['other_photo_url'] == 'https://photos.example.invalid/photo.jpg' for row in rows)
    assert next(row for row in rows if row['id'] == CID)['unread']
    lookup.assert_called_once()
    assert set(lookup.call_args.args[0]) == {other}
    sign.assert_called_once_with(['stored-photo.jpg'])


@pytest.mark.parametrize('failure', ['missing_profile', 'no_photo', 'lookup_error', 'sign_error'])
def test_optional_inbox_photo_failure_keeps_conversations(context, monkeypatch, failure):
    row = {**context[3], 'created_at': '2026-11-20T10:00:00+00:00'}
    message = {'id': 1, 'sender_id': 8, 'body': 'Hi', 'created_at': '2026-11-20T10:00:00+00:00'}
    monkeypatch.setattr(database, 'messaging_inbox', lambda actor: [inbox_row(row, last_message=message)])
    monkeypatch.setattr(database, 'messaging_unread_conversations', lambda actor: [])
    # A missing profile and a profile without a photo both come back as "no path".
    lookup = MagicMock(return_value={} if failure in ('missing_profile', 'no_photo')
                       else {8: 'photo.jpg'})
    sign = MagicMock(side_effect=RuntimeError('private photo error'))
    if failure == 'lookup_error':
        lookup.side_effect = RuntimeError('private profile error')
    monkeypatch.setattr(database, 'photo_paths_of', lookup)
    monkeypatch.setattr(database, 'photo_urls', sign)
    result = repo.get_inbox(include_photos=True)
    assert result[0]['id'] == CID and result[0]['other_photo_url'] is None
    assert 'private' not in str(result)
    if failure != 'sign_error':
        sign.assert_not_called()


def test_inbox_photo_lookup_does_not_bypass_membership(context, monkeypatch):
    monkeypatch.setattr(database, 'messaging_inbox', lambda actor: [
        inbox_row({'id': CID, 'buyer_id': 90, 'seller_id': 91})])
    lookup, sign = MagicMock(), MagicMock()
    monkeypatch.setattr(database, 'photo_paths_of', lookup)
    monkeypatch.setattr(database, 'photo_urls', sign)
    with pytest.raises(ValueError):
        repo.get_inbox(include_photos=True)
    lookup.assert_not_called()
    sign.assert_not_called()


def test_offer_statuses_change_when_an_offer_is_answered(context, monkeypatch):
    mine = {**context[3], "listing_title_snapshot": "Bike"}
    offer = {"id": MID, "status": "pending", "amount_cents": 4500, "sender_id": 7,
             "parent_offer_id": None, "created_at": "2026-11-20T10:00:00+00:00"}
    monkeypatch.setattr(database, "messaging_inbox",
                        lambda actor: [inbox_row(mine, "Seller name", last_offer=offer)])
    before = repo.offer_statuses()
    assert before == ((CID, MID, "pending"),)
    offer["status"] = "accepted"
    assert repo.offer_statuses() != before


def test_offer_notices_and_statuses_share_one_inbox_request(context, monkeypatch):
    query = MagicMock(return_value=[inbox_row(context[3])])
    monkeypatch.setattr(database, "messaging_inbox", query)
    with repo.checked_once():
        repo.offers_to_answer()
        repo.offer_statuses()
    query.assert_called_once_with(7)
