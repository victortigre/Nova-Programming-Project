"""How a seller gets paid: bank transfer, Revolut, PayPal, MB WAY or cash.

The app never moves money. Students pay each other directly, with one of the
ways the seller accepts. Every seller keeps them on My profile (at least one
is needed to sell something for money; free items need none):

    bank     bank transfer: account holder's name and IBAN
    revolut  Revolut: @username or phone number
    paypal   PayPal: email or paypal.me link
    mbway    MB WAY: Portuguese mobile number
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

BANK, REVOLUT, PAYPAL, MBWAY, CASH = "bank", "revolut", "paypal", "mbway", "cash"
METHOD_LABELS = {BANK: "Bank transfer", REVOLUT: "Revolut", PAYPAL: "PayPal",
                 MBWAY: "MB WAY", CASH: "Cash in person"}
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
    """The international check every bank uses (ISO 13616, "mod 97").

    Catches almost every typo: a wrong or swapped digit makes it fail.
    """
    iban = clean_iban(iban)
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban):
        return False
    moved = iban[4:] + iban[:4]
    as_number = "".join(str(int(ch, 36)) for ch in moved)  # A=10, B=11, ... Z=35
    return int(as_number) % 97 == 1


# --- the other methods --------------------------------------------------------------

def clean_mbway(phone: str | None) -> str:
    """'912 345 678' or '+351 912345678' -> '+351 912 345 678' ('' if empty)."""
    digits = re.sub(r"[\s().-]", "", phone or "")
    if digits.startswith("+351"):
        digits = digits[4:]
    elif digits.startswith("00351"):
        digits = digits[5:]
    if not digits:
        return ""
    return f"+351 {digits[:3]} {digits[3:6]} {digits[6:]}" if len(digits) == 9 else digits


def mbway_is_valid(phone: str | None) -> bool:
    """A Portuguese mobile number: 9 digits starting with 9 (with or without +351)."""
    return bool(re.fullmatch(r"\+351 9\d{2} \d{3} \d{3}", clean_mbway(phone)))


def revolut_is_valid(value: str | None) -> bool:
    """A Revolut @username (3 to 32 letters, digits, . _ -) or a phone number."""
    value = (value or "").strip()
    return bool(re.fullmatch(r"@?[A-Za-z0-9._-]{3,32}", value)
                or re.fullmatch(r"\+?[0-9 ]{9,16}", value))


def paypal_is_valid(value: str | None) -> bool:
    """A PayPal email address or a paypal.me link."""
    value = (value or "").strip()
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", value)
                or re.fullmatch(r"(https?://)?(www\.)?paypal\.me/[A-Za-z0-9._-]{1,40}/?", value))


# --- checking and saving ---------------------------------------------------------------

def check_payment_methods(*, holder=None, iban=None, revolut=None, paypal=None,
                          mbway=None, cash=False) -> list[str]:
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
            errors.append("Bank transfer: this IBAN isn't valid. Check it on your bank app, "
                          "for example PT50 0002 0123 1234 5678 9015 4.")
    if (revolut or "").strip() and not revolut_is_valid(revolut):
        errors.append("Revolut: write your @username or your phone number.")
    if (paypal or "").strip() and not paypal_is_valid(paypal):
        errors.append("PayPal: write your PayPal email or your paypal.me link.")
    if (mbway or "").strip() and not mbway_is_valid(mbway):
        errors.append("MB WAY: write a Portuguese mobile number, for example 912 345 678.")
    nothing = not (holder or clean_iban(iban) or (revolut or "").strip()
                   or (paypal or "").strip() or (mbway or "").strip() or cash)
    if nothing:
        errors.append("Choose at least one way to get paid.")
    return errors


class PaymentMethodsError(ValueError):
    """The payment details break one or more rules. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def save_payment_methods(db, email: str, *, holder=None, iban=None, revolut=None,
                         paypal=None, mbway=None, cash=False) -> None:
    """Store the ways to get paid on this student's OWN profile (email from the login)."""
    who = nova_email({"email": email})
    if who is None or db.get_profile(who) is None:
        raise PaymentMethodsError(["Fill in your profile first."])
    errors = check_payment_methods(holder=holder, iban=iban, revolut=revolut,
                                   paypal=paypal, mbway=mbway, cash=cash)
    if errors:
        raise PaymentMethodsError(errors)
    has_bank = bool(clean_iban(iban))
    db.save_payment_methods(who, {
        "bank_holder": (holder or "").strip() if has_bank else None,
        "iban": clean_iban(iban) if has_bank else None,
        "revolut": (revolut or "").strip() or None,
        "paypal": (paypal or "").strip() or None,
        "mbway": clean_mbway(mbway) or None,
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
    if profile.get("revolut"):
        out.append({"key": REVOLUT, "label": METHOD_LABELS[REVOLUT],
                    "details": [("Revolut", profile["revolut"])]})
    if profile.get("paypal"):
        out.append({"key": PAYPAL, "label": METHOD_LABELS[PAYPAL],
                    "details": [("PayPal", profile["paypal"])]})
    if profile.get("mbway"):
        out.append({"key": MBWAY, "label": METHOD_LABELS[MBWAY],
                    "details": [("MB WAY number", profile["mbway"])]})
    if profile.get("accepts_cash"):
        out.append({"key": CASH, "label": METHOD_LABELS[CASH], "details": []})
    return out


def can_be_paid(profile: dict | None) -> bool:
    """Does this profile accept at least one way to get paid?"""
    return bool(methods_of(profile))


def accepted_labels(profile: dict | None) -> str:
    """'MB WAY · Revolut · Cash in person' (no details), for the item page."""
    return " · ".join(method["label"] for method in methods_of(profile))
