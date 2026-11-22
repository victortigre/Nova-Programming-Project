"""Tests for how sellers get paid (payments.py): bank transfer (IBAN) and cash in
person, checking what they type and saving it.

Run them with:  pytest
"""

import pytest

import payments
from deal_helpers import TEST_IBAN
from fake_database import FakeDatabase

JOANA = "joana@novasbe.pt"


@pytest.fixture
def db():
    db = FakeDatabase()
    db.add_profile(JOANA)
    return db


# --- IBAN ----------------------------------------------------------------------------

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


# --- checking everything together --------------------------------------------------------

def test_one_method_is_enough_and_any_one_will_do():
    assert payments.check_payment_methods(holder="Joana Gomes", iban=TEST_IBAN) == []
    assert payments.check_payment_methods(cash=True) == []
    assert payments.check_payment_methods(holder="Joana Gomes", iban=TEST_IBAN, cash=True) == []


def test_at_least_one_method_is_needed():
    assert payments.check_payment_methods() == [
        "Choose at least one way to get paid: bank transfer or cash."]


def test_a_wrong_iban_is_refused_even_if_cash_is_accepted_too():
    errors = payments.check_payment_methods(holder="Joana", iban="PT50 1234", cash=True)
    assert len(errors) == 1 and "isn't valid" in errors[0]


def test_bank_transfer_needs_both_the_name_and_the_iban():
    assert "account holder" in payments.check_payment_methods(iban=TEST_IBAN)[0]
    assert "write your IBAN" in payments.check_payment_methods(holder="Joana")[0]


# --- saving and reading ------------------------------------------------------------------

def test_saving_stores_clean_values_on_your_own_profile(db):
    payments.save_payment_methods(db, JOANA, holder=" Joana Gomes ",
                                  iban="pt50 0002 0123 1234 5678 9015 4", cash=True)
    profile = db.get_profile(JOANA)
    assert profile["iban"] == TEST_IBAN and profile["bank_holder"] == "Joana Gomes"
    assert profile["accepts_cash"] is True
    assert [m["key"] for m in payments.methods_of(profile)] == ["bank", "cash"]
    assert payments.accepted_labels(profile) == "Bank transfer · Cash in person"


def test_cash_only_seller_can_be_paid_and_has_no_details(db):
    payments.save_payment_methods(db, JOANA, cash=True)
    profile = db.get_profile(JOANA)
    assert payments.can_be_paid(profile)
    assert payments.methods_of(profile) == [{"key": "cash", "label": "Cash in person",
                                             "details": []}]


def test_saving_refuses_bad_details_and_unknown_students(db):
    with pytest.raises(payments.PaymentMethodsError):
        payments.save_payment_methods(db, JOANA, holder="Joana", iban="PT50 1234")
    with pytest.raises(payments.PaymentMethodsError):
        payments.save_payment_methods(db, JOANA)  # nothing at all
    with pytest.raises(payments.PaymentMethodsError):
        payments.save_payment_methods(db, "someone@gmail.com", cash=True)
    assert not payments.can_be_paid(db.get_profile(JOANA))
