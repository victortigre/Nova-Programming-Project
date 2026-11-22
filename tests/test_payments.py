"""Tests for how sellers get paid (payments.py): bank transfer (IBAN), Revolut,
PayPal, MB WAY and cash, checking what they type and saving it.

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


# --- the other methods ------------------------------------------------------------------

@pytest.mark.parametrize("phone", ["912345678", "912 345 678", "+351 912 345 678",
                                   "00351912345678", "961234567"])
def test_valid_mbway_numbers(phone):
    assert payments.mbway_is_valid(phone)


@pytest.mark.parametrize("phone", ["212345678", "91234567", "+44 7911 123456", "abc"])
def test_invalid_mbway_numbers(phone):
    assert not payments.mbway_is_valid(phone)


def test_mbway_is_stored_the_same_way_however_it_was_typed():
    assert payments.clean_mbway("912345678") == payments.clean_mbway("+351 912 345 678")


@pytest.mark.parametrize("value,ok", [("@joana", True), ("joana.g", True), ("+351 912345678", True),
                                      ("@j", False), ("joana gomes!", False)])
def test_revolut(value, ok):
    assert payments.revolut_is_valid(value) is ok


@pytest.mark.parametrize("value,ok", [("joana@example.com", True), ("paypal.me/joana", True),
                                      ("https://www.paypal.me/joana", True),
                                      ("joana", False), ("paypal.com/joana", False)])
def test_paypal(value, ok):
    assert payments.paypal_is_valid(value) is ok


# --- checking everything together --------------------------------------------------------

def test_one_method_is_enough_and_any_one_will_do():
    assert payments.check_payment_methods(holder="Joana Gomes", iban=TEST_IBAN) == []
    assert payments.check_payment_methods(mbway="912345678") == []
    assert payments.check_payment_methods(revolut="@joana") == []
    assert payments.check_payment_methods(paypal="joana@example.com") == []
    assert payments.check_payment_methods(cash=True) == []


def test_at_least_one_method_is_needed():
    assert payments.check_payment_methods() == ["Choose at least one way to get paid."]


def test_each_filled_in_method_must_be_right():
    errors = payments.check_payment_methods(holder="Joana", iban="PT50 1234", mbway="123",
                                            revolut="!", paypal="nope", cash=True)
    assert [e.split(":")[0] for e in errors] == ["Bank transfer", "Revolut", "PayPal", "MB WAY"]


def test_bank_transfer_needs_both_the_name_and_the_iban():
    assert "account holder" in payments.check_payment_methods(iban=TEST_IBAN)[0]
    assert "write your IBAN" in payments.check_payment_methods(holder="Joana")[0]


# --- saving and reading ------------------------------------------------------------------

def test_saving_stores_clean_values_on_your_own_profile(db):
    payments.save_payment_methods(db, JOANA, holder=" Joana Gomes ",
                                  iban="pt50 0002 0123 1234 5678 9015 4",
                                  mbway="912345678", cash=True)
    profile = db.get_profile(JOANA)
    assert profile["iban"] == TEST_IBAN and profile["bank_holder"] == "Joana Gomes"
    assert profile["mbway"] == "+351 912 345 678" and profile["accepts_cash"] is True
    assert profile["revolut"] is None and profile["paypal"] is None
    assert [m["key"] for m in payments.methods_of(profile)] == ["bank", "mbway", "cash"]
    assert payments.accepted_labels(profile) == "Bank transfer · MB WAY · Cash in person"


def test_cash_only_seller_can_be_paid_and_has_no_details(db):
    payments.save_payment_methods(db, JOANA, cash=True)
    profile = db.get_profile(JOANA)
    assert payments.can_be_paid(profile)
    assert payments.methods_of(profile) == [{"key": "cash", "label": "Cash in person",
                                             "details": []}]


def test_saving_refuses_bad_details_and_unknown_students(db):
    with pytest.raises(payments.PaymentMethodsError):
        payments.save_payment_methods(db, JOANA, mbway="123")
    with pytest.raises(payments.PaymentMethodsError):
        payments.save_payment_methods(db, JOANA)  # nothing at all
    with pytest.raises(payments.PaymentMethodsError):
        payments.save_payment_methods(db, "someone@gmail.com", cash=True)
    assert not payments.can_be_paid(db.get_profile(JOANA))
