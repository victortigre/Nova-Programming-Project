"""Pure offer rules. Prices are cents; offers are never text messages."""

from listings import MAX_PRICE_CENTS
from messaging import MAX_MESSAGE_LENGTH, require_conversation_participant

OFFER_STATUS_LABELS = {
    "pending": "Pending", "accepted": "Accepted",
    "declined": "Declined", "superseded": "Superseded",
}


def validate_offer_price(price_cents: int) -> int:
    if type(price_cents) is not int or not 1 <= price_cents <= MAX_PRICE_CENTS:
        raise ValueError(f"Offer price must be between €0.01 and €{MAX_PRICE_CENTS // 100:,}.")
    return price_cents


def validate_offer_note(note: str | None) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise ValueError("The optional offer message must be text.")
    note = note.strip()
    if len(note) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Offer messages can be at most {MAX_MESSAGE_LENGTH} characters.")
    return note or None


def require_offer_recipient(actor: int, conversation: dict, offer: dict) -> None:
    require_conversation_participant(actor, conversation["buyer_id"], conversation["seller_id"])
    if (offer["conversation_id"] != conversation["id"]
            or offer["sender_id"] not in (conversation["buyer_id"], conversation["seller_id"])
            or offer["sender_id"] == actor):
        raise ValueError("Only the recipient can respond to this offer.")
    if offer["status"] != "pending":
        raise ValueError("This offer is no longer pending.")


def offers_waiting_for(actor: int, conversations: list[dict], latest_offer_of) -> list[dict]:
    """Offers this student must answer: the newest offer of a chat, still pending,
    sent by the OTHER person. For the notifications on Browse.

    `latest_offer_of(conversation_id)` returns that chat's newest offer or None.
    Each result: {"conversation_id", "amount_cents", "counter" (True for a
    counteroffer), "sender_id", "listing_title"}. Newest first.
    """
    waiting = []
    for row in conversations:
        if actor not in (row.get("buyer_id"), row.get("seller_id")):
            continue
        offer = latest_offer_of(row["id"])
        if not offer or offer.get("status") != "pending" or offer.get("sender_id") == actor:
            continue
        waiting.append({"conversation_id": row["id"], "amount_cents": offer["amount_cents"],
                        "counter": bool(offer.get("parent_offer_id")),
                        "sender_id": offer["sender_id"],
                        "listing_title": row.get("listing_title_snapshot") or "your item",
                        "created_at": offer.get("created_at") or ""})
    waiting.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return waiting
