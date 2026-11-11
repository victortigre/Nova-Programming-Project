"""Tests for the rule "only verified Nova addresses may come in".

Run them with:  pytest
"""

from accounts import email_is_verified, nova_email

# --- nova_email: is it a Nova address? ----------------------------------------


def test_nova_student_is_accepted():
    assert nova_email({"email": "12345@novasbe.pt"}) == "12345@novasbe.pt"


def test_email_is_cleaned_up():
    assert nova_email({"email": "  Maria.Silva@NovaSBE.pt "}) == "maria.silva@novasbe.pt"


def test_other_email_domain_is_rejected():
    assert nova_email({"email": "someone@gmail.com"}) is None


def test_lookalike_domains_are_rejected():
    assert nova_email({"email": "someone@novasbe.pt.evil.com"}) is None
    assert nova_email({"email": "someone@evilnovasbe.pt"}) is None
    assert nova_email({"email": "someone@students.novasbe.pt"}) is None


def test_two_at_signs_are_rejected():
    assert nova_email({"email": "someone@gmail.com@novasbe.pt"}) is None


def test_missing_or_empty_email_is_rejected():
    assert nova_email({}) is None
    assert nova_email({"email": None}) is None
    assert nova_email({"email": ""}) is None
    assert nova_email({"email": "@novasbe.pt"}) is None


# --- email_is_verified: did they click the emailed link? ----------------------


def test_verified_email_is_accepted():
    assert email_is_verified({"email_verified": True}) is True


def test_unverified_email_is_rejected():
    assert email_is_verified({"email_verified": False}) is False


def test_missing_verification_is_rejected():
    assert email_is_verified({}) is False


def test_only_a_real_true_counts():
    # Anything that is not exactly True must not open the door.
    assert email_is_verified({"email_verified": "true"}) is False
    assert email_is_verified({"email_verified": 1}) is False
