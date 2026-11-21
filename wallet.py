"""Wallet: each student's balance of Nova credits (pretend money, not real payments).

How money moves (see deals.py for the buying steps):

    add credits        the student tops up in "My profile" (+, a demo button)
    seller accepts     the price is HELD from the buyer's balance (-)
    buyer confirms     the held money is RELEASED to the seller (+)
      "I got it"
    deal called off    the held money is REFUNDED to the buyer (+)
      (declined or cancelled before the buyer confirmed)

Free items never touch the wallet.

The balance is never stored as one number that gets overwritten. Every change
is a line in a list (wallet_entries), like a bank statement, and the balance
is the sum of the lines. That way every euro can be traced, and the history in
"My profile" is simply that list.

Safety, in the database (see database_setup.sql):
* Holding money checks the balance and takes it in ONE step, so two sales at
  the same moment can never spend the same credits twice.
* A deal can be held once, and then either released OR refunded, once. The
  database refuses a second hold, a second release, or a refund after a release.

Every function takes `db` first, like listings.py and deals.py: the pages pass
the real `database` module, the tests pass the in-memory fake.
"""

from accounts import nova_email
from listings import NotAllowed, format_price

TOP_UP, HOLD, RELEASE, REFUND = "top_up", "hold", "release", "refund"

# The demo "Add credits" buttons, and the most a balance may hold.
TOP_UP_AMOUNTS = [1_000, 5_000, 10_000]  # €10, €50, €100
MAX_BALANCE_CENTS = 1_000_000  # €10,000


class WalletError(ValueError):
    """Something about the money isn't possible (not enough credits, too much...)."""


def _profile(db, email: str) -> dict:
    who = nova_email({"email": email})
    if who is None:
        raise NotAllowed("Only @novasbe.pt accounts have a balance.")
    profile = db.get_profile(who)
    if profile is None:
        raise NotAllowed("Fill in your profile first.")
    return profile


# --- reading ------------------------------------------------------------------

def balance_of(db, profile_id: int) -> int:
    """The credits a student can spend now, in cents (held money is not included)."""
    return sum(entry["amount_cents"] for entry in db.wallet_entries_of(profile_id))


def my_balance(db, email: str) -> int:
    return balance_of(db, _profile(db, email)["id"])


def my_history(db, email: str) -> list[dict]:
    """The student's wallet lines, newest first, each with a readable "text"."""
    entries = db.wallet_entries_of(_profile(db, email)["id"])
    return [{**entry, "text": describe(entry)} for entry in entries]


def describe(entry: dict) -> str:
    """'Added credits', 'Held for “Desk lamp”', ... for the history list."""
    title = entry.get("note") or "an item"
    return {
        TOP_UP: "Added credits",
        HOLD: f"Paid for “{title}” (held until you confirm you got it)",
        RELEASE: f"Sold “{title}”",
        REFUND: f"Refund for “{title}”",
    }.get(entry["kind"], entry["kind"])


def can_afford(db, profile_id: int, price_cents: int) -> bool:
    return price_cents <= 0 or balance_of(db, profile_id) >= price_cents


def euros(cents: int) -> str:
    """1250 -> '€12.50' (also for 0, unlike format_price which says 'Free')."""
    return f"€{cents / 100:,.2f}"


def not_enough_message(db, profile_id: int, price_cents: int) -> str:
    return (f"You need {euros(price_cents)} in credits for this, and you have "
            f"{euros(balance_of(db, profile_id))}. Add credits in My profile.")


# --- the student: add credits --------------------------------------------------

def add_credits(db, email: str, amount_cents: int) -> None:
    """The demo top-up: only the fixed amounts, and never above the maximum balance."""
    profile = _profile(db, email)
    if profile.get("blocked_at"):
        raise NotAllowed("Your account has been blocked.")
    if amount_cents not in TOP_UP_AMOUNTS:
        raise WalletError("Choose one of the amounts on the buttons.")
    if balance_of(db, profile["id"]) + amount_cents > MAX_BALANCE_CENTS:
        raise WalletError(f"A balance can be at most {format_price(MAX_BALANCE_CENTS)}.")
    db.wallet_add_entry({"profile_id": profile["id"], "amount_cents": amount_cents,
                         "kind": TOP_UP, "request_id": None, "note": None})


# --- the buying steps (only deals.py calls these) ------------------------------

def hold(db, request: dict, listing: dict) -> bool:
    """Take the price from the buyer's balance when the seller accepts.

    True when the money is held (or the item is free). False when the buyer
    doesn't have enough credits; then nothing changed.
    """
    price = listing.get("price_cents") or 0
    if price <= 0:
        return True
    return db.wallet_hold(request["buyer_id"], request["id"], price, listing.get("title"))


def release(db, request: dict, listing: dict | None) -> None:
    """Give the held money to the seller (the buyer confirmed they got the item)."""
    if listing is not None:
        db.wallet_settle(request["id"], RELEASE, listing["seller_id"])


def refund(db, request: dict) -> None:
    """Give the held money back to the buyer (the deal was called off)."""
    db.wallet_settle(request["id"], REFUND, request["buyer_id"])
