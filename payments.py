"""Bank details for receiving payments (no money goes through the app).

Students pay each other by bank transfer. Every seller keeps their bank
details on their profile: the account holder's name and the IBAN. These are
shown ONLY to a buyer of one of their deals, never on a public profile.

    check_bank_details   what is wrong with a name and IBAN (empty list = fine)
    clean_iban           "pt50 0002 0123..." -> "PT50000201231234567890154"
    show_iban            "PT50000201231234567890154" -> "PT50 0002 0123 1234 5678 9015 4"
    has_bank_details     does this profile have both filled in?
    save_bank_details    check them and store them on the student's own profile

Only save_bank_details touches the database (through `db`, like listings.py);
the rest are plain rules, easy to test.
"""

import re

from accounts import nova_email

MAX_HOLDER_LENGTH = 70


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


def check_bank_details(holder: str | None, iban: str | None) -> list[str]:
    """Every problem with these bank details; an empty list means they are fine."""
    errors = []
    holder = (holder or "").strip()
    if len(holder) < 2:
        errors.append("Write the name of the account holder.")
    elif len(holder) > MAX_HOLDER_LENGTH:
        errors.append(f"The account holder's name can be at most {MAX_HOLDER_LENGTH} characters.")
    if not clean_iban(iban):
        errors.append("Write your IBAN.")
    elif not iban_is_valid(iban):
        errors.append("This IBAN isn't valid. Check it on your bank app, for example "
                      "PT50 0002 0123 1234 5678 9015 4.")
    return errors


def has_bank_details(profile: dict | None) -> bool:
    return bool(profile and profile.get("iban") and (profile.get("bank_holder") or "").strip())


class BankDetailsError(ValueError):
    """The bank details break one or more rules. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def save_bank_details(db, email: str, holder: str, iban: str) -> None:
    """Store the bank details on this student's OWN profile (the email from the login)."""
    who = nova_email({"email": email})
    if who is None or db.get_profile(who) is None:
        raise BankDetailsError(["Fill in your profile first."])
    errors = check_bank_details(holder, iban)
    if errors:
        raise BankDetailsError(errors)
    db.save_bank_details(who, holder.strip(), clean_iban(iban))
