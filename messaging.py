"""Reusable messaging rules, independent of Streamlit and storage.

Callers must obtain the acting profile from verified authentication. These
helpers validate rules; they do not authenticate a supplied profile ID.
Database constraints must also enforce uniqueness when persistence is added.
"""

MAX_MESSAGE_LENGTH = 2000


def validate_message(body: str) -> str:
    """Trim outer whitespace, preserving internal spacing and line breaks.

    Return the text to store, or raise ValueError with a user-facing reason.
    The length limit applies to the trimmed text, measured in characters.
    """
    if not isinstance(body, str):
        raise ValueError("Message must be text.")
    body = body.strip()
    if not body:
        raise ValueError("Write a message before sending.")
    if len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Messages can be at most {MAX_MESSAGE_LENGTH} characters.")
    return body


def _valid_profile_id(value: object) -> bool:
    # bool is a subclass of int, but True must never stand in for profile 1.
    return type(value) is int and value > 0


def validate_conversation_participants(buyer_id: int, seller_id: int) -> None:
    """Require two different, existing-profile-shaped IDs.

    Actual profile existence and listing ownership need storage-layer checks.
    """
    if not _valid_profile_id(buyer_id) or not _valid_profile_id(seller_id):
        raise ValueError("Both participants must have a valid profile.")
    if buyer_id == seller_id:
        raise ValueError("You cannot message yourself about your own listing.")


def is_conversation_participant(actor_id: int, buyer_id: int, seller_id: int) -> bool:
    """Fail closed for invalid identities or malformed participant pairs."""
    return (
        _valid_profile_id(actor_id)
        and _valid_profile_id(buyer_id)
        and _valid_profile_id(seller_id)
        and buyer_id != seller_id
        and actor_id in (buyer_id, seller_id)
    )


def require_conversation_participant(actor_id: int, buyer_id: int, seller_id: int) -> None:
    """Guard history reads and sends without disclosing other participants."""
    if not is_conversation_participant(actor_id, buyer_id, seller_id):
        raise ValueError("Conversation unavailable.")


def conversation_key(listing_id: int, buyer_id: int) -> tuple[int, int]:
    """Identify one buyer/listing conversation, independent of its seller.

    Use only for real numeric listing IDs, never fictional demo listing keys.
    A future database UNIQUE(listing_id, buyer_id) must handle concurrent creates.
    """
    if type(listing_id) is not int or listing_id <= 0:
        raise ValueError("Listing must have a valid ID.")
    if not _valid_profile_id(buyer_id):
        raise ValueError("Buyer must have a valid profile.")
    return listing_id, buyer_id
