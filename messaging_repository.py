"""Authenticated messaging operations for future Streamlit pages.

No UI-supplied actor IDs or emails are accepted. Every call rechecks st.user.
Nothing connects on import. The standalone session-state demo does not use this.
"""

from datetime import datetime
from uuid import UUID

import streamlit as st

import database
from accounts import logged_in_user, verified_nova_email
from profiles import DONE, onboarding_step
from messaging import (
    conversation_key,
    require_conversation_participant,
    validate_conversation_participants,
    validate_message,
)


def is_configured() -> bool:
    """Check local configuration only; never opens a database connection."""
    if not st.user.is_logged_in or verified_nova_email(logged_in_user()) is None:
        raise ValueError("Please sign in with a verified Nova account.")
    return database.database_is_set_up()


def _details(row: dict, actor: int) -> dict:
    require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    other_id = row["seller_id"] if actor == row["buyer_id"] else row["buyer_id"]
    other = database.get_profile_by_id(other_id)
    return {**row, "other_name": other["name"] if other else "Profile unavailable",
            "own_profile_id": actor}


def get_conversation_details(conversation_id: str) -> dict:
    actor = _actor()
    return _details(_authorized(conversation_id, actor), actor)


def get_inbox() -> list[dict]:
    """Authorized summaries sorted by latest message, or conversation creation.

    Initial implementation uses one preview query per conversation.
    A paginated aggregate query will be needed before scaling this up.
    """
    actor = _actor()
    summaries = []
    for row in database.messaging_conversations(actor):
        summary = _details(row, actor)
        latest = database.messaging_messages(row["id"], 1, 0)
        summary["last_message"] = latest[0] if latest else None
        summaries.append(summary)
    return sorted(summaries, key=lambda row: (
        datetime.fromisoformat((row["last_message"] or row)["created_at"]),
        row["last_message"]["id"] if row["last_message"] else 0,
        row["id"],
    ), reverse=True)


def _actor() -> int:
    if not st.user.is_logged_in:
        raise ValueError("Please sign in with a verified Nova account.")
    email = verified_nova_email(logged_in_user())
    if email is None:
        raise ValueError("Please sign in with a verified Nova account.")
    profile = database.messaging_actor_profile(email)
    if profile is None or type(profile.get("id")) is not int or profile["id"] <= 0:
        raise ValueError("Complete your profile before using messages.")
    if profile.get("blocked_at"):
        raise ValueError("Your account has been blocked.")
    if onboarding_step(profile) != DONE:
        raise ValueError("Finish the Welcome steps before using messages.")
    return profile["id"]


def require_access() -> None:
    """Recheck account restrictions before rendering any private Messaging UI."""
    _actor()


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid messaging reference.") from None


def _authorized(conversation_id: str, actor: int) -> dict:
    row = database.messaging_conversation(_uuid(conversation_id), actor)
    if row is None:
        raise ValueError("Conversation unavailable.")
    require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    return row


def get_conversation(conversation_id: str) -> dict:
    return _authorized(conversation_id, _actor())


def list_conversations() -> list[dict]:
    """Return the actor's conversations; latest-message previews can follow later."""
    actor = _actor()
    rows = database.messaging_conversations(actor)
    for row in rows:
        require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    return rows


def get_messages(conversation_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    actor = _actor()
    row = _authorized(conversation_id, actor)
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Invalid message page.")
    # Fetch the latest page descending, display it in chronological order.
    return list(reversed(database.messaging_messages(row["id"], limit, offset)))


def send_message(conversation_id: str, body: str, client_message_id: str) -> dict:
    """Reuse the same client_message_id when retrying an uncertain send."""
    actor = _actor()
    conversation = _authorized(conversation_id, actor)
    payload = {
        "conversation_id": conversation["id"],
        "sender_id": actor,
        "body": validate_message(body),
        "client_message_id": _uuid(client_message_id),
    }
    saved = database.messaging_insert_message(payload)
    if any(saved.get(key) != value for key, value in payload.items()):
        raise ValueError("Message retry does not match the original message.")
    return saved


def get_or_create_conversation(listing_id: int) -> dict:
    """Use a stored listing and the current login; never accept participant IDs.

    A missing listing cannot start/reopen a chat through this operation. Existing
    participants can still open it by conversation ID and continue messaging.
    """
    actor = _actor()
    conversation_key(listing_id, actor)  # Reject bool, text, negative IDs.
    listing = database.get_listing(listing_id)
    if listing is None:
        raise ValueError("Listing no longer available.")
    seller = database.get_profile_by_id(listing["seller_id"])
    if seller is None or seller.get("blocked_at") or onboarding_step(seller) != DONE:
        raise ValueError("Seller unavailable.")
    validate_conversation_participants(actor, seller["id"])
    existing = database.messaging_conversation_for_listing(listing_id, actor)
    if existing is not None:
        row = existing
    else:
        if listing["status"] not in ("active", "reserved"):
            raise ValueError("Listing is not available for new conversations.")
        # The INSERT trigger derives seller and immutable snapshots atomically
        # from the live listing. Its lock serializes this with listing deletion.
        row = database.messaging_insert_conversation({"listing_id": listing_id, "buyer_id": actor})
    require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    if (row["buyer_id"], row["seller_id"], row["original_listing_id"]) != (actor, seller["id"], listing_id):
        raise ValueError("Conversation does not match the listing participants.")
    return row
