"""Tests for the rule "only verified Nova addresses may come in".

Run them with:  pytest
"""

from accounts import (email_is_verified, is_admin, nova_email, verified_nova_email,
                      with_fresh_verification)


# --- is_admin: is this email on the admin list? -------------------------------


def test_admin_on_the_list_is_accepted():
    assert is_admin("boss@novasbe.pt", ["boss@novasbe.pt"]) is True


def test_admin_check_ignores_case_and_spaces():
    assert is_admin(" Boss@NovaSBE.pt ", ["boss@novasbe.pt"]) is True
    assert is_admin("boss@novasbe.pt", ["BOSS@novasbe.pt "]) is True


def test_student_not_on_the_list_is_not_admin():
    assert is_admin("ana@novasbe.pt", ["boss@novasbe.pt"]) is False


def test_no_list_or_no_email_means_no_admin():
    assert is_admin("boss@novasbe.pt", None) is False
    assert is_admin("boss@novasbe.pt", []) is False
    assert is_admin(None, ["boss@novasbe.pt"]) is False
    assert is_admin("", ["boss@novasbe.pt", ""]) is False
    assert is_admin("boss@novasbe.pt", [None]) is False

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


# --- verified_nova_email: both checks together --------------------------------


def test_verified_nova_student_may_use_the_app():
    user_info = {"email": "12345@novasbe.pt", "email_verified": True}
    assert verified_nova_email(user_info) == "12345@novasbe.pt"


def test_unverified_nova_student_may_not():
    user_info = {"email": "12345@novasbe.pt", "email_verified": False}
    assert verified_nova_email(user_info) is None


def test_verified_outsider_may_not():
    user_info = {"email": "someone@gmail.com", "email_verified": True}
    assert verified_nova_email(user_info) is None


def test_nobody_logged_in_may_not():
    assert verified_nova_email({"is_logged_in": False}) is None
    assert verified_nova_email({}) is None


# --- with_fresh_verification: Auth0 says the link was clicked -----------------

STALE = {"sub": "auth0|abc", "email": "12345@novasbe.pt", "email_verified": False}


def test_confirmed_email_lets_the_student_in_without_signing_in_again():
    answer = {"sub": "auth0|abc", "email": "12345@novasbe.pt", "email_verified": True}
    assert verified_nova_email(with_fresh_verification(STALE, answer)) == "12345@novasbe.pt"


def test_still_unconfirmed_email_stays_out():
    answer = {"sub": "auth0|abc", "email": "12345@novasbe.pt", "email_verified": False}
    assert verified_nova_email(with_fresh_verification(STALE, answer)) is None


def test_answer_about_another_account_is_ignored():
    answer = {"sub": "auth0|other", "email": "12345@novasbe.pt", "email_verified": True}
    assert verified_nova_email(with_fresh_verification(STALE, answer)) is None


def test_answer_about_another_email_is_ignored():
    answer = {"sub": "auth0|abc", "email": "99999@novasbe.pt", "email_verified": True}
    assert verified_nova_email(with_fresh_verification(STALE, answer)) is None


def test_no_answer_from_auth0_changes_nothing():
    assert with_fresh_verification(STALE, {}) == STALE
    assert with_fresh_verification({"email_verified": False}, {"email_verified": True}) == {"email_verified": False}
