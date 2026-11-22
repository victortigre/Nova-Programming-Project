"""Tests for bank details (payments.py): checking an IBAN and saving it.

Run them with:  pytest
"""

import pytest

import payments
from deal_helpers import TEST_IBAN
from fake_database import FakeDatabase


@pytest.mark.parametrize("iban", [
    TEST_IBAN,
    "pt50 0002 0123 1234 5678 9015 4",       # spaces and small letters are fine
    "GB82 WEST 1234 5698 7654 32",
    "DE89-3704-0044-0532-0130-00",
])
def test_valid_ibans(iban):
    assert payments.iban_is_valid(iban)


@pytest.mark.parametrize("iban", [
    "PT50000201231234567890155",   # one digit wrong
    "PT05000201231234567890154",   # two digits swapped
    "PT50",                        # too short
    "1234567890123456",            # no country
    "",
])
def test_invalid_ibans(iban):
    assert not payments.iban_is_valid(iban)


def test_iban_is_shown_in_groups_of_four():
    assert payments.show_iban(TEST_IBAN) == "PT50 0002 0123 1234 5678 9015 4"


def test_bank_details_need_a_name_and_a_valid_iban():
    assert payments.check_bank_details("Joana Gomes", TEST_IBAN) == []
    assert payments.check_bank_details("", TEST_IBAN) == ["Write the name of the account holder."]
    assert payments.check_bank_details("Joana", "") == ["Write your IBAN."]
    assert "isn't valid" in payments.check_bank_details("Joana", "PT50 1234")[0]
    assert "at most" in payments.check_bank_details("x" * 71, TEST_IBAN)[0]


def test_saving_stores_the_clean_iban_on_your_own_profile():
    db = FakeDatabase()
    db.add_profile("joana@novasbe.pt")
    payments.save_bank_details(db, "joana@novasbe.pt", "  Joana Gomes ",
                               "pt50 0002 0123 1234 5678 9015 4")
    profile = db.get_profile("joana@novasbe.pt")
    assert profile["bank_holder"] == "Joana Gomes" and profile["iban"] == TEST_IBAN
    assert payments.has_bank_details(profile)


def test_saving_refuses_bad_details_and_unknown_students():
    db = FakeDatabase()
    db.add_profile("joana@novasbe.pt")
    with pytest.raises(payments.BankDetailsError):
        payments.save_bank_details(db, "joana@novasbe.pt", "Joana", "PT50 1234")
    with pytest.raises(payments.BankDetailsError):
        payments.save_bank_details(db, "someone@gmail.com", "Joana", TEST_IBAN)
    assert not payments.has_bank_details(db.get_profile("joana@novasbe.pt"))
