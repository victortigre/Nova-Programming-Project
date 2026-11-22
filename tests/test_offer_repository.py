"""Repository/transport tests. SQL is never executed; RPC responses are mocked.

PostgreSQL locking, grants and trigger behaviour require separate development
database integration tests before activation; these tests do not prove them.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

import database
import messaging_repository as repo

CID = "11111111-1111-4111-8111-111111111111"
OID = "22222222-2222-4222-8222-222222222222"
OP = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def context(monkeypatch):
    user = SimpleNamespace(is_logged_in=True)
    monkeypatch.setattr(repo.st, "user", user)
    identity = MagicMock(return_value={"email": "buyer@novasbe.pt", "email_verified": True})
    monkeypatch.setattr(repo, "logged_in_user", identity)
    actor = MagicMock(return_value={"id": 7, "rules_accepted_at": "yes"})
    monkeypatch.setattr(database, "messaging_actor_profile", actor)
    conversation = {"id": CID, "buyer_id": 7, "seller_id": 8, "listing_id": 10}
    query = MagicMock(return_value=conversation)
    monkeypatch.setattr(database, "messaging_conversation", query)
    result = {"id": OID, "conversation_id": CID, "sender_id": 7, "amount_cents": 1200,
              "note": None, "status": "pending", "created_at": "2026-11-20T10:00:00+00:00"}
    client = MagicMock()
    monkeypatch.setattr(database, "_client", lambda: client)
    client.rpc.return_value.execute.return_value.data = result
    return SimpleNamespace(user=user, identity=identity, actor=actor, conversation=conversation,
                           query=query, result=result, client=client)


def test_send_offer_without_text_creates_structured_record_not_message(context):
    assert repo.send_offer(CID, 1200, OP) == context.result
    context.actor.assert_called_once_with("buyer@novasbe.pt")
    context.client.rpc.assert_called_once_with("messaging_offer_action", {
        "p_conversation_id": CID, "p_actor_id": 7, "p_action": "send", "p_operation_id": OP,
        "p_offer_id": None, "p_amount_cents": 1200, "p_note": None,
    })
    context.client.table.assert_not_called()


def test_offer_note_is_only_in_rpc_not_a_second_chat_message(context):
    repo.send_offer(CID, 1200, OP, "  Can collect today  ")
    assert context.client.rpc.call_args.args[1]["p_note"] == "Can collect today"
    context.client.table.assert_not_called()


@pytest.mark.parametrize("actor", [7, 8])
def test_counter_uses_authenticated_actor_and_references_parent(context, actor):
    context.actor.return_value = {"id": actor, "rules_accepted_at": "yes"}
    repo.counter_offer(CID, OID, 1100, OP)
    payload = context.client.rpc.call_args.args[1]
    assert payload["p_actor_id"] == actor
    assert payload["p_offer_id"] == OID
    assert payload["p_action"] == "counter"
    assert payload["p_amount_cents"] == 1100


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_responses_use_atomic_rpc_without_listing_or_purchase_writes(context, action):
    getattr(repo, f"{action}_offer")(CID, OID, OP)
    payload = context.client.rpc.call_args.args[1]
    assert payload["p_action"] == action and payload["p_offer_id"] == OID
    assert payload["p_amount_cents"] is None
    context.client.table.assert_not_called()


OPERATIONS = [
    lambda: repo.send_offer(CID, 1000, OP),
    lambda: repo.counter_offer(CID, OID, 1000, OP),
    lambda: repo.accept_offer(CID, OID, OP),
    lambda: repo.decline_offer(CID, OID, OP),
    lambda: repo.get_offers(CID), lambda: repo.get_chat_events(CID),
    lambda: repo.get_buy_now_agreement(CID),
]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("restriction", ["logout", "unverified", "blocked", "unfinished", "outsider"])
def test_every_operation_checks_identity_account_and_membership(context, operation, restriction):
    if restriction == "logout":
        context.user.is_logged_in = False
    elif restriction == "unverified":
        context.identity.return_value["email_verified"] = False
    elif restriction == "blocked":
        context.actor.return_value["blocked_at"] = "now"
    elif restriction == "unfinished":
        context.actor.return_value["rules_accepted_at"] = None
    else:
        context.actor.return_value["id"] = 99
    with pytest.raises(ValueError):
        operation()
    context.client.rpc.assert_not_called()
    context.client.table.assert_not_called()


@pytest.mark.parametrize("amount", [True, 0, -1, "1000", 1.2, 500001])
def test_invalid_price_never_calls_rpc(context, amount):
    with pytest.raises(ValueError):
        repo.send_offer(CID, amount, OP)
    context.client.rpc.assert_not_called()


def test_same_retry_passes_identical_operation_payload_to_database(context):
    repo.send_offer(CID, 1000, OP, " note ")
    repo.send_offer(CID, 1000, OP, "note")
    assert context.client.rpc.call_args_list[0] == context.client.rpc.call_args_list[1]


@pytest.mark.parametrize("message", [
    "Only the recipient can respond", "Offer retry does not match",
    "Listing unavailable", "No current pending offer",
])
def test_rejected_atomic_operation_is_not_retried_as_an_insert(context, message):
    context.client.rpc.return_value.execute.side_effect = APIError({
        "code": "23514", "message": message, "details": None, "hint": None,
    })
    with pytest.raises(APIError):
        repo.counter_offer(CID, OID, 1000, OP)
    assert context.client.rpc.call_count == 1
    context.client.table.assert_not_called()


def test_mixed_timeline_retains_each_offer_and_its_optional_note(context, monkeypatch):
    first = {**context.result, "status": "superseded", "note": "My first offer"}
    second = {**first, "id": str(uuid4()), "sender_id": 8, "status": "accepted",
              "amount_cents": 1300, "parent_offer_id": OID, "note": None,
              "created_at": "2026-11-20T10:02:00+00:00"}
    message = {"id": 1, "sender_id": 7, "body": "Hi", "created_at": "2026-11-20T10:01:00+00:00"}
    monkeypatch.setattr(database, "messaging_messages", lambda *args: [message])
    monkeypatch.setattr(database, "messaging_offers", lambda *args: [second, first])
    monkeypatch.setattr(database, "names_of", lambda ids: {7: "Buyer", 8: "Seller"})
    events = repo.get_chat_events(CID)
    assert [event["type"] for event in events] == ["offer", "message", "offer"]
    assert events[0]["status_label"] == "Superseded"
    assert events[0]["note"] == "My first offer"
    assert events[-1]["status_label"] == "Accepted"
    assert events[-1]["sender_name"] == "Seller"
    assert events[-1]["amount_cents"] == 1300


@pytest.mark.parametrize("sender", [7, 8])
def test_mutually_accepted_offer_enables_buyer_eligibility_only(context, monkeypatch, sender):
    accepted = {**context.result, "status": "accepted", "sender_id": sender}
    monkeypatch.setattr(database, "messaging_offers", lambda *args: [accepted])
    monkeypatch.setattr(database, "get_listing", lambda lid: {"id": lid, "seller_id": 8, "status": "active"})
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"id": pid, "rules_accepted_at": "yes"})
    assert repo.get_buy_now_agreement(CID) == accepted
    context.actor.return_value["id"] = 8
    assert repo.get_buy_now_agreement(CID) is None
    context.client.rpc.assert_not_called()


@pytest.mark.parametrize("status", ["reserved", "sold", "deleted"])
def test_unavailable_listing_cannot_enable_buy_now(context, monkeypatch, status):
    monkeypatch.setattr(database, "messaging_offers", lambda *args: [{**context.result, "status": "accepted"}])
    monkeypatch.setattr(database, "get_listing", lambda lid: None if status == "deleted" else {"seller_id": 8, "status": status})
    monkeypatch.setattr(database, "get_profile_by_id", lambda pid: {"rules_accepted_at": "yes"})
    assert repo.get_buy_now_agreement(CID) is None


def test_offer_history_transport_scopes_and_paginates(context):
    query = context.client.table.return_value.select.return_value
    for method in ("eq", "order", "range"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = [context.result]
    assert repo.get_offers(CID, limit=20, offset=40) == [context.result]
    context.client.table.assert_called_once_with("offers")
    query.eq.assert_called_once_with("conversation_id", CID)
    query.range.assert_called_once_with(40, 59)


@pytest.mark.parametrize("action", ["accept_offer", "decline_offer"])
def test_offer_response_never_charges_reserves_or_creates_purchase(context, monkeypatch, action):
    writes = []
    for name in ("insert_request", "update_request", "update_listing"):
        mock = MagicMock(side_effect=AssertionError("Offer response must not change purchases"))
        monkeypatch.setattr(database, name, mock)
        writes.append(mock)
    getattr(repo, action)(CID, OID, OP)
    for mock in writes:
        mock.assert_not_called()
    context.client.rpc.assert_called_once()
    assert context.client.rpc.call_args.args[0] == "messaging_offer_action"
    context.client.table.assert_not_called()
