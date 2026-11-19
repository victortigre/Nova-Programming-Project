"""Authenticated messaging operations for future Streamlit pages.

No UI-supplied actor IDs or emails are accepted. Every call rechecks st.user.
Nothing connects on import. The standalone session-state demo does not use this.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import streamlit as st

import database
from accounts import verified_nova_email
from messaging import (
    require_conversation_participant,
    validate_conversation_participants,
    validate_message,
)


@dataclass(frozen=True)
class DemoListing:
    seller_email: str
    title: str
    price: str


# Trusted server configuration only; never populate from form/session data.
# Deliberately empty until consenting test accounts and fixtures are configured.
DEMO_LISTINGS: dict[str, DemoListing] = {}


def is_configured() -> bool:
    """Check local configuration only; never opens a database connection."""
    if not st.user.is_logged_in or verified_nova_email(st.user.to_dict()) is None:
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
    email = verified_nova_email(st.user.to_dict())
    if email is None:
        raise ValueError("Please sign in with a verified Nova account.")
    profile = database.get_profile(email)
    if profile is None or type(profile.get("id")) is not int or profile["id"] <= 0:
        raise ValueError("Complete your profile before using messages.")
    return profile["id"]


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


def get_or_create_demo_conversation(demo_listing_ref: str) -> dict:
    """Only configured fixtures may create conversations; no UI seller metadata."""
    actor = _actor()
    fixture = DEMO_LISTINGS.get(demo_listing_ref)
    if fixture is None:
        raise ValueError("Demo listing unavailable.")
    seller = database.get_profile(fixture.seller_email)
    if seller is None:
        raise ValueError("Demo listing unavailable.")
    validate_conversation_participants(actor, seller["id"])
    payload = {
        "buyer_id": actor, "seller_id": seller["id"],
        "demo_listing_ref": demo_listing_ref,
        "listing_title_snapshot": fixture.title,
        "listing_price_snapshot": fixture.price,
    }
    row = database.messaging_insert_conversation(payload)
    require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    if (row["buyer_id"], row["seller_id"], row["demo_listing_ref"]) != (actor, seller["id"], demo_listing_ref):
        raise ValueError("Demo listing configuration no longer matches this conversation.")
    return row
