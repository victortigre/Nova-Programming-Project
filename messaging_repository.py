"""Authenticated messaging operations for future Streamlit pages.

No UI-supplied actor IDs or emails are accepted. Every call rechecks st.user.
Nothing connects on import. The standalone session-state demo does not use this.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from uuid import UUID

import streamlit as st

import database
from accounts import logged_in_user, verified_nova_email
from profiles import DONE, onboarding_step
from offers import (OFFER_STATUS_LABELS, offers_waiting_for, validate_offer_note,
                    validate_offer_price)
from messaging import (
    conversation_key,
    require_conversation_participant,
    validate_conversation_participants,
    validate_message,
)


# --- One check per page load ---------------------------------------------------
# A page asks several questions in a row (who is signed in, may they open this
# chat, the messages, the offers). Each answer is a trip to Supabase, so asking
# "who is signed in" four times made every click slower. Inside
# `with checked_once():` the answers are kept until the page has finished
# loading, then thrown away. The next click asks again, so a block still counts
# right away. Sending and offer actions always ask afresh (see _actor_now).
_page_load: ContextVar = ContextVar("messaging_page_load", default=None)


@contextmanager
def checked_once():
    """Ask Supabase each question once while the page loads (reads only)."""
    if _page_load.get() is not None:  # Already inside one: share it.
        yield
        return
    token = _page_load.set({})
    try:
        yield
    finally:
        _page_load.reset(token)


def _remember(key, load):
    memory = _page_load.get()
    if memory is None:
        return load()
    if key not in memory:
        memory[key] = load()
    return memory[key]


def _remember_names(names: dict) -> None:
    memory = _page_load.get()
    if memory is not None:
        memory.setdefault("names", {}).update(names)


def _names(profile_ids: list) -> dict:
    """{profile id: name}; names seen earlier in this page load need no request."""
    memory = _page_load.get()
    known = memory.get("names", {}) if memory is not None else {}
    names = {pid: known[pid] for pid in profile_ids if pid in known}
    missing = sorted({pid for pid in profile_ids if pid not in known and pid is not None})
    if missing:
        names.update(database.names_of(missing))
    return names


def is_configured() -> bool:
    """Check local configuration only; never opens a database connection."""
    if not st.user.is_logged_in or verified_nova_email(logged_in_user()) is None:
        raise ValueError("Please sign in with a verified Nova account.")
    return database.database_is_set_up()


def _details(row: dict, actor: int, *, include_photo: bool = False) -> dict:
    require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    other_id = row["seller_id"] if actor == row["buyer_id"] else row["buyer_id"]
    other = database.get_profile_by_id(other_id)
    if other and other.get("name"):
        _remember_names({other_id: other["name"]})
    details = {**row, "other_name": other["name"] if other else "Profile unavailable",
               "own_profile_id": actor}
    if include_photo:
        # Photos are optional presentation data. Authorize the conversation first,
        # use the existing private-photo helper, and never let signing failures
        # prevent participants from reading or sending messages.
        details["other_photo_url"] = None
        if other and other.get("photo_path"):
            try:
                details["other_photo_url"] = database.photo_url(other["photo_path"])
            except Exception:
                pass
    return details


def get_conversation_details(conversation_id: str) -> dict:
    actor = _actor()
    row = _details(_authorized(conversation_id, actor), actor, include_photo=True)
    # Membership and identity above remain mandatory. Availability is optional:
    # fail closed for negotiation without hiding an authorized chat's history.
    try:
        listing = database.get_listing(row["listing_id"]) if row.get("listing_id") is not None else None
        row["listing_status"] = listing["status"] if listing else "unavailable"
    except Exception:
        row["listing_status"] = "unknown"
    return row


def get_inbox(*, include_photos: bool = False) -> list[dict]:
    """Participant-only previews including offer creation and responses.

    One request for the whole list (database.messaging_inbox), however many
    chats there are (optional profile photos add two requests in total).
    The newest event decides the order: the last message, or
    the offer made or answered most recently.
    """
    actor = _actor()
    # One lookup of this student's unread chats, so each preview can show a dot.
    # Empty if read-tracking isn't set up yet, so the inbox still loads.
    try:
        unread = set(database.messaging_unread_conversations(actor))
    except Exception:
        unread = set()
    # How many are new, for the violet counter. Optional: if the counting
    # function isn't in the database yet, an unread chat simply shows "1".
    try:
        counts = database.messaging_unread_counts(actor)
        counts = counts if isinstance(counts, dict) else {}
    except Exception:
        counts = {}
    items = database.messaging_inbox(actor)
    # Membership first: nothing about another student is looked up before it.
    for item in items:
        row = item["conversation"]
        require_conversation_participant(actor, row["buyer_id"], row["seller_id"])

    def other_in(row: dict) -> int:
        return row["seller_id"] if actor == row["buyer_id"] else row["buyer_id"]

    # The photos of everyone in the list: one request for where they are stored
    # and one for their links, however many chats there are.
    photos = {}
    if include_photos and items:
        try:
            paths = database.photo_paths_of([other_in(item["conversation"]) for item in items])
            links = database.photo_urls(list(paths.values())) if paths else {}
            photos = {other_id: links.get(path) for other_id, path in paths.items()}
        except Exception:
            photos = {}  # Optional photos must never hide authorized conversations.
    summaries = []
    for item in items:
        row = item["conversation"]
        summary = {**row, "other_name": item.get("other_name") or "Profile unavailable",
                   "own_profile_id": actor, "unread": row["id"] in unread,
                   "unread_count": (max(1, int(counts.get(row["id"]) or 0))
                                    if row["id"] in unread else 0)}
        if include_photos:
            summary["other_photo_url"] = photos.get(other_in(row))
        latest = item.get("last_message")
        summary["last_message"] = latest
        events = []
        if latest:
            events.append({**latest, "type": "message", "activity_at": latest["created_at"]})
        offer = item.get("last_offer")
        if offer:
            events.append({**offer, "type": "offer", "activity_at": max(
                (offer["created_at"], offer.get("responded_at") or offer["created_at"]),
                key=datetime.fromisoformat)})
        activity = max(events, key=lambda event: (
            datetime.fromisoformat(event["activity_at"]), event["type"], str(event["id"])
        ), default=None)
        # An empty chat — a bare "Buy Now" reservation with no message or offer yet —
        # is not shown in the inbox. It appears only once there's real activity (the
        # buyer messages, makes an offer, or the "I've paid" line is posted). Paying
        # and confirming still happen on My purchases / My listings, not here.
        if activity is None:
            continue
        summary["last_activity"] = activity
        summary["activity_at"] = activity["activity_at"]
        summaries.append(summary)
    return sorted(summaries, key=lambda row: (
        datetime.fromisoformat(row["activity_at"]), row["id"],
    ), reverse=True)


def _actor() -> int:
    """The signed-in student's profile id; asked once per page load (reads)."""
    if not st.user.is_logged_in:
        raise ValueError("Please sign in with a verified Nova account.")
    return _remember("actor", _actor_now)


def _actor_now() -> int:
    """Always asks Supabase. Used before every send or offer action."""
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
    if profile.get("name"):
        _remember_names({profile["id"]: profile["name"]})
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
    # Who is in a chat never changes, so this may be remembered for the page load.
    cid = _uuid(conversation_id)
    row = _remember(("conversation", cid, actor),
                    lambda: database.messaging_conversation(cid, actor))
    if row is None:
        raise ValueError("Conversation unavailable.")
    require_conversation_participant(actor, row["buyer_id"], row["seller_id"])
    return row


def get_conversation(conversation_id: str) -> dict:
    return _authorized(conversation_id, _actor())


def mark_read(conversation_id: str) -> None:
    """Record that the signed-in student just opened this chat, so its messages
    stop counting towards the Inbox unread badge."""
    actor = _actor()
    _authorized(conversation_id, actor)  # only a participant may mark it read
    database.messaging_mark_read(_uuid(conversation_id), actor)


def unread_conversations() -> set[str]:
    """Ids of the signed-in student's chats that have messages they haven't opened.
    Powers both the Inbox badge count and the unread dot in the inbox list."""
    return set(database.messaging_unread_conversations(_actor()))


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
    actor = _actor_now()
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
    actor = _actor_now()
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


def _inbox_rows(actor: int) -> list[dict]:
    """Every chat of this student. Inside checked_once() it is asked for once."""
    return _remember(("inbox", actor), lambda: database.messaging_inbox(actor))


def offers_to_answer() -> list[dict]:
    """Offers and counteroffers waiting for the signed-in student's answer.

    For the notifications on Browse. Each has "sender_name" added. One request
    for all chats: the same one the Inbox uses.
    """
    actor = _actor()
    items = _inbox_rows(actor)
    newest = {item["conversation"]["id"]: item.get("newest_offer") for item in items}
    other_names = {item["conversation"]["id"]: item.get("other_name") for item in items}
    listing_ids = {item["conversation"]["id"]: item["conversation"].get("listing_id")
                   for item in items}
    waiting = offers_waiting_for(actor, [item["conversation"] for item in items], newest.get)
    # An offer can only be answered while the item is on sale. Once it is
    # reserved, sold or deleted there is nothing to do, so no notification.
    waiting = [item for item in waiting if _on_sale(listing_ids.get(item["conversation_id"]))]
    # The sender is the other person in that chat, whose name came along.
    return [{**item, "sender_name": other_names.get(item["conversation_id"]) or "A student"}
            for item in waiting]


def _on_sale(listing_id) -> bool:
    """Is this listing still there and active? Asked only for offers that wait."""
    if listing_id is None:
        return False
    try:
        listing = database.get_listing(listing_id)
    except Exception:
        return True  # could not check: better one notification too many
    return listing is not None and listing.get("status") == "active"


def offer_statuses() -> tuple:
    """A small fingerprint of the offers in the signed-in student's chats:
    (chat, offer, status) for the offer made or answered most recently in each.

    It changes when the other person accepts, declines or counters. app.py
    watches it, so an open chat shows the answer without pressing Refresh.
    """
    statuses = []
    for item in _inbox_rows(_actor()):
        offer = item.get("last_offer")
        if offer:
            statuses.append((str(item["conversation"]["id"]), str(offer.get("id")),
                             offer.get("status")))
    return tuple(sorted(statuses))


def get_offers(conversation_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    actor = _actor()
    row = _authorized(conversation_id, actor)
    _offer_page(limit, offset)
    return list(reversed(_offers_newest_first(row["id"], limit, offset)))


def _offers_newest_first(conversation_id: str, limit: int, offset: int) -> list[dict]:
    """A page of offers. Offers loaded earlier in this page load (by
    get_chat_events) are reused instead of being asked for again."""
    memory = _page_load.get()
    if memory is not None and offset == 0:
        loaded = memory.get(("offers", conversation_id))
        if loaded is not None:
            loaded_limit, rows = loaded
            if limit <= loaded_limit or len(rows) < loaded_limit:
                return rows[:limit]
    rows = database.messaging_offers(conversation_id, limit, offset)
    if memory is not None and offset == 0:
        memory[("offers", conversation_id)] = (limit, rows)
    return rows


def _offer_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Invalid offer page.")


def _offer_action(conversation_id: str, action: str, operation_id: str,
                  offer_id: str | None = None, price_cents: int | None = None,
                  note: str | None = None) -> dict:
    actor = _actor_now()
    conversation = _authorized(conversation_id, actor)
    # SQL rechecks live listing, both accounts, current offer and recipient under
    # locks. Do not reject retries based on a status already changed by that retry.
    return database.messaging_offer_action({
        "p_conversation_id": conversation["id"], "p_actor_id": actor,
        "p_action": action, "p_operation_id": _uuid(operation_id),
        "p_offer_id": _uuid(offer_id) if offer_id is not None else None,
        "p_amount_cents": validate_offer_price(price_cents) if action in ("send", "counter") else None,
        "p_note": validate_offer_note(note),
    })


def send_offer(conversation_id: str, price_cents: int, operation_id: str,
               note: str | None = None) -> dict:
    """Buyer starts an offer. No message or purchase row is created."""
    return _offer_action(conversation_id, "send", operation_id, price_cents=price_cents, note=note)


def counter_offer(conversation_id: str, offer_id: str, price_cents: int,
                  operation_id: str, note: str | None = None) -> dict:
    return _offer_action(conversation_id, "counter", operation_id, offer_id, price_cents, note)


def accept_offer(conversation_id: str, offer_id: str, operation_id: str) -> dict:
    return _offer_action(conversation_id, "accept", operation_id, offer_id)


def decline_offer(conversation_id: str, offer_id: str, operation_id: str) -> dict:
    return _offer_action(conversation_id, "decline", operation_id, offer_id)


def get_chat_events(conversation_id: str, *, limit: int = 50) -> list[dict]:
    """Latest combined timeline for chat cards; existing text API unchanged.

    Each offer is one event, including its optional note, never a duplicate text
    message. Read this again after an action to display the authoritative status.
    """
    actor = _actor()
    row = _authorized(conversation_id, actor)
    _offer_page(limit, 0)
    events = [{**message, "type": "message"}
              for message in database.messaging_messages(row["id"], limit, 0)]
    events += [{**offer, "type": "offer", "status_label": OFFER_STATUS_LABELS[offer["status"]]}
               for offer in _offers_newest_first(row["id"], limit, 0)]
    events.sort(key=lambda event: (datetime.fromisoformat(event["created_at"]), event["type"], str(event["id"])))
    events = events[-limit:]
    names = _names([event["sender_id"] for event in events]) if events else {}
    return [{**event, "sender_name": names.get(event["sender_id"], "Profile unavailable")}
            for event in events]


def get_buy_now_agreement(conversation_id: str) -> dict | None:
    """Buyer-only agreement display; never authorizes checkout or a reservation.

    No payment data is read. The purchase itself is deals.buy_now, which
    validates the agreement, existing purchases and availability again.
    """
    actor = _actor()
    conversation = _authorized(conversation_id, actor)
    if actor != conversation["buyer_id"] or conversation["listing_id"] is None:
        return None
    latest = database.messaging_offers(conversation["id"], 1, 0)
    if not latest or latest[0]["status"] != "accepted":
        return None
    listing = database.get_listing(conversation["listing_id"])
    seller = database.get_profile_by_id(conversation["seller_id"])
    if (listing is None or listing["status"] != "active"
            or listing["seller_id"] != conversation["seller_id"]
            or seller is None or seller.get("blocked_at") or onboarding_step(seller) != DONE):
        return None
    return latest[0]
