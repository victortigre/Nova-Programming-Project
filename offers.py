"""Pure offer rules. Prices are cents; offers are never text messages."""

from listings import MAX_PRICE_CENTS
from messaging import MAX_MESSAGE_LENGTH, require_conversation_participant

OFFER_STATUS_LABELS = {
    "pending": "Pending", "accepted": "Accepted",
    "declined": "Declined", "superseded": "Superseded",
}


def validate_offer_price(price_cents: int) -> int:
    if type(price_cents) is not int or not 1 <= price_cents <= MAX_PRICE_CENTS:
        raise ValueError(f"Offer price must be between 1 and {MAX_PRICE_CENTS} cents.")
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
