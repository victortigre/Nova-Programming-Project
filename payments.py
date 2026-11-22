"""How a seller gets paid: bank transfer (IBAN) or cash in person.

The app never moves money. Students pay each other directly, in one of the
ways the seller accepts. Every seller sets them on My profile (at least one
is needed to sell something for money; free items need none):

    bank     bank transfer: account holder's name and IBAN
    cash     cash, paid in person when buyer and seller meet (no details)

The details are shown ONLY to the buyer of one of the seller's deals, never on
a public profile.

    check_payment_methods  every problem with what a seller typed (empty = fine)
    save_payment_methods   check them and store them on the student's own profile
    methods_of             the methods a profile accepts, with their details
    can_be_paid            does this profile accept at least one method?
    clean_iban, show_iban, iban_is_valid   IBAN helpers

Only save_payment_methods touches the database (through `db`, like listings.py);
the rest are plain rules, easy to test.
"""

import re

from accounts import nova_email

BANK, CASH = "bank", "cash"
METHOD_LABELS = {BANK: "Bank transfer", CASH: "Cash in person"}
MAX_HOLDER_LENGTH = 70


# --- IBAN -------------------------------------------------------------------------

def clean_iban(iban: str | None) -> str:
    """Upper case, without spaces or dashes."""
    return re.sub(r"[\s-]", "", iban or "").upper()


def show_iban(iban: str | None) -> str:
    """The IBAN in groups of four, the way banks print it."""
    iban = clean_iban(iban)
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def iban_is_valid(iban: str | None) -> bool:
    """Does it LOOK like an IBAN? Country letters, then the right amount of digits.

    A Portuguese IBAN is PT + 23 digits (25 characters); other countries have
    15 to 34 characters. On purpose there is NO bank checksum ("mod 97"): this
    is a course project, nobody pays real money, so a made-up IBAN with the
    right shape (PT50 0000 0000 0000 0000 0000 0) must be accepted for demos.
    """
    iban = clean_iban(iban)
    if iban.startswith("PT"):
        return bool(re.fullmatch(r"PT[0-9]{23}", iban))
    return bool(re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban))


# --- checking and saving ---------------------------------------------------------------

def check_payment_methods(*, holder=None, iban=None, cash=False) -> list[str]:
    """Every problem with these payment details; an empty list means they are fine.

    Each method is optional, but if you fill one in it must be right, and at
    least one way to get paid is needed.
    """
    errors = []
    holder = (holder or "").strip()
    if holder or clean_iban(iban):
        if len(holder) < 2:
            errors.append("Bank transfer: write the name of the account holder.")
        elif len(holder) > MAX_HOLDER_LENGTH:
            errors.append(f"Bank transfer: the account holder's name can be at most "
                          f"{MAX_HOLDER_LENGTH} characters.")
        if not clean_iban(iban):
            errors.append("Bank transfer: write your IBAN.")
        elif not iban_is_valid(iban):
            errors.append("Bank transfer: this doesn't look like an IBAN. A Portuguese one is "
                          "PT and 23 digits, for example PT50 0000 0000 0000 0000 0000 0.")
    if not (holder or clean_iban(iban) or cash):
        errors.append("Choose at least one way to get paid: bank transfer or cash.")
    return errors


class PaymentMethodsError(ValueError):
    """The payment details break one or more rules. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def save_payment_methods(db, email: str, *, holder=None, iban=None, cash=False) -> None:
    """Store the ways to get paid on this student's OWN profile (email from the login)."""
    who = nova_email({"email": email})
    if who is None or db.get_profile(who) is None:
        raise PaymentMethodsError(["Fill in your profile first."])
    errors = check_payment_methods(holder=holder, iban=iban, cash=cash)
    if errors:
        raise PaymentMethodsError(errors)
    has_bank = bool(clean_iban(iban))
    db.save_payment_methods(who, {
        "bank_holder": (holder or "").strip() if has_bank else None,
        "iban": clean_iban(iban) if has_bank else None,
        "accepts_cash": bool(cash),
    })


# --- reading ------------------------------------------------------------------------

def methods_of(profile: dict | None) -> list[dict]:
    """The methods this profile accepts, in a fixed order.

    Each: {"key", "label", "details": [(caption, value), ...]}. Cash has no details.
    """
    profile = profile or {}
    out = []
    if profile.get("iban") and (profile.get("bank_holder") or "").strip():
        out.append({"key": BANK, "label": METHOD_LABELS[BANK], "details": [
            ("Account holder", profile["bank_holder"].strip()),
            ("IBAN", show_iban(profile["iban"]))]})
    if profile.get("accepts_cash"):
        out.append({"key": CASH, "label": METHOD_LABELS[CASH], "details": []})
    return out


def can_be_paid(profile: dict | None) -> bool:
    """Does this profile accept at least one way to get paid?"""
    return bool(methods_of(profile))


def accepted_labels(profile: dict | None) -> str:
    """'Bank transfer · Cash in person' (no details), for the item page."""
    return " · ".join(method["label"] for method in methods_of(profile))
