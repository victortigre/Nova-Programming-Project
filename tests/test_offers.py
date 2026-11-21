"""Pure offer rules, with no UI or database."""

import pytest

from listings import MAX_PRICE_CENTS
from offers import require_offer_recipient, validate_offer_note, validate_offer_price


@pytest.mark.parametrize("amount", [1, 1234, MAX_PRICE_CENTS])
def test_offer_amount_is_integer_cents(amount):
    assert validate_offer_price(amount) == amount


@pytest.mark.parametrize("amount", [0, -1, True, False, "1200", 12.34, None, MAX_PRICE_CENTS + 1])
def test_invalid_offer_price(amount):
    with pytest.raises(ValueError):
        validate_offer_price(amount)


def test_note_is_optional_and_kept_once():
    assert validate_offer_note(None) is None
    assert validate_offer_note(" \n ") is None
    assert validate_offer_note("  Olá!\nCan we meet?  ") == "Olá!\nCan we meet?"
    assert len(validate_offer_note("x" * 2000)) == 2000


@pytest.mark.parametrize("note", [123, b"text", "x" * 2001])
def test_invalid_note(note):
    with pytest.raises(ValueError):
        validate_offer_note(note)


@pytest.mark.parametrize("sender,recipient", [(7, 8), (8, 7)])
def test_only_other_participant_responds(sender, recipient):
    conversation = {"id": "chat", "buyer_id": 7, "seller_id": 8}
    offer = {"conversation_id": "chat", "sender_id": sender, "status": "pending"}
    require_offer_recipient(recipient, conversation, offer)
    for actor in (sender, 99):
        with pytest.raises(ValueError):
            require_offer_recipient(actor, conversation, offer)
    for status in ("accepted", "declined", "superseded"):
        with pytest.raises(ValueError):
            require_offer_recipient(recipient, conversation, {**offer, "status": status})
    with pytest.raises(ValueError):
        require_offer_recipient(recipient, conversation, {**offer, "conversation_id": "other"})
