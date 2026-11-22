"""Shortcuts for tests that need a purchase (deals.py) without repeating the steps.

A purchase starts in a chat: the buyer and seller agree a price (an accepted
offer), then the buyer taps Buy Now. These helpers set that up in the fake
database (tests/fake_database.py).
"""

from itertools import count

import deals
import payments

TEST_IBAN = "PT50000201231234567890154"  # a valid example IBAN, not a real account
_chats = count(1)


def give_bank_details(db, email: str) -> None:
    """The seller accepts bank transfer (and nothing else)."""
    db.save_payment_methods(email, {"bank_holder": "Test Seller", "iban": TEST_IBAN})


def start_purchase(db, listing_id: int, buyer_email: str, price_cents: int = 2000) -> dict:
    """Chat about the listing, agree on `price_cents`, tap Buy Now. Returns the deal."""
    listing = db.get_listing(listing_id)
    seller = db.get_profile_by_id(listing["seller_id"])
    if not payments.can_be_paid(seller):
        give_bank_details(db, seller["email"])
    buyer = db.get_profile(buyer_email)
    chat_id = f"chat-{next(_chats)}"
    db.add_chat(chat_id, listing_id, buyer["id"], seller["id"])
    db.add_offer(chat_id, buyer["id"], price_cents, status="accepted")
    return deals.buy_now(db, buyer_email, chat_id)


def finish_purchase(db, request_id: int, buyer_email: str, seller_email: str) -> None:
    """The buyer pays by bank transfer, the seller confirms: the deal is completed."""
    deals.mark_paid(db, request_id, buyer_email, "bank")
    deals.confirm_payment(db, request_id, seller_email)
