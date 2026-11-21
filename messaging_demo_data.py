"""Mock messaging store. Replace these operations with database helpers later.

The UI owns the store's lifetime through st.session_state. This module has
no Streamlit or Supabase dependency and never uses real account identities.
"""

from copy import deepcopy
from datetime import datetime, timezone

from messaging import (
    MAX_MESSAGE_LENGTH,
    is_conversation_participant,
    require_conversation_participant,
    validate_message,
)

DEMO_USER_ID = 1


def new_demo_store() -> dict:
    """Return fresh, independent example data for one browser session."""
    return deepcopy({
        "users": {1: "You (demo)", 2: "Sofia", 3: "Miguel", 4: "Inês"},
        "listings": {
            1: {"title": "Study desk", "price": 45, "icon": "🪑"},
            2: {"title": "Economics textbook", "price": 18, "icon": "📚"},
            3: {"title": "Coffee machine", "price": 30, "icon": "☕"},
        },
        "conversations": {
            1: {"listing_id": 1, "participants": [1, 2]},
            2: {"listing_id": 2, "participants": [1, 3]},
            3: {"listing_id": 3, "participants": [1, 4]},
        },
        "messages": [
            {"id": 1, "conversation_id": 1, "sender_id": 1, "body": "Hi Sofia! Is the desk still available?", "created_at": "2026-11-16T10:00:00+00:00"},
            {"id": 2, "conversation_id": 1, "sender_id": 2, "body": "Hi! Yes, you can collect it near campus this week.", "created_at": "2026-11-16T10:05:00+00:00"},
            {"id": 3, "conversation_id": 2, "sender_id": 3, "body": "Hello! Does the textbook have any notes inside?", "created_at": "2026-11-16T12:30:00+00:00"},
            {"id": 4, "conversation_id": 2, "sender_id": 1, "body": "Just a few pencil notes. Happy to show you!", "created_at": "2026-11-16T12:35:00+00:00"},
            {"id": 5, "conversation_id": 3, "sender_id": 1, "body": "Hi Inês, could I pick it up tomorrow?", "created_at": "2026-11-17T09:00:00+00:00"},
            {"id": 6, "conversation_id": 3, "sender_id": 4, "body": "Of course! After class works for me.", "created_at": "2026-11-17T09:10:00+00:00"},
        ],
    })


def conversation_for(store: dict, conversation_id: int, user_id: int) -> dict:
    conversation = store["conversations"].get(conversation_id)
    if conversation is None:
        raise ValueError("Conversation unavailable.")
    require_conversation_participant(user_id, *conversation["participants"])
    return conversation


def message_history(store: dict, conversation_id: int, user_id: int) -> list[dict]:
    conversation_for(store, conversation_id, user_id)
    return sorted(
        (message for message in store["messages"] if message["conversation_id"] == conversation_id),
        key=lambda message: (datetime.fromisoformat(message["created_at"]), message["id"]),
    )


def inbox(store: dict, user_id: int) -> list[dict]:
    rows = []
    for conversation_id, conversation in store["conversations"].items():
        if not is_conversation_participant(user_id, *conversation["participants"]):
            continue
        other_id = next(person for person in conversation["participants"] if person != user_id)
        history = message_history(store, conversation_id, user_id)
        rows.append({
            "id": conversation_id,
            "other_name": store["users"][other_id],
            "listing": store["listings"][conversation["listing_id"]],
            "last_message": history[-1] if history else None,
        })
    return sorted(rows, key=lambda row: (
        datetime.fromisoformat(row["last_message"]["created_at"]) if row["last_message"] else datetime.min.replace(tzinfo=timezone.utc),
        row["last_message"]["id"] if row["last_message"] else 0,
    ), reverse=True)


def send_message(store: dict, conversation_id: int, user_id: int, body: str) -> None:
    conversation_for(store, conversation_id, user_id)
    body = validate_message(body)
    store["messages"].append({
        "id": max((message["id"] for message in store["messages"]), default=0) + 1,
        "conversation_id": conversation_id,
        "sender_id": user_id,
        "body": body,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
