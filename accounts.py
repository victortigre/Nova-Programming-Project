"""Accounts: who is allowed into Nova Marketplace.

The login itself is done by Auth0, a login service. People sign up there
with an email and a password, and Auth0 sends them a link to confirm the
email address. We never see or store a password.

After a login, Auth0 tells the app who the person is. This file decides
whether that person may come in.
"""

ALLOWED_DOMAIN = "@novasbe.pt"


def nova_email(user_info: dict) -> str | None:
    """Return the person's Nova email, or None if it is not a Nova address.

    `user_info` is what Auth0 sent us after the login.
    """
    email = (user_info.get("email") or "").strip().lower()

    if email.count("@") != 1:
        return None
    if not email.endswith(ALLOWED_DOMAIN) or email == ALLOWED_DOMAIN:
        return None
    return email


def email_is_verified(user_info: dict) -> bool:
    """True only if the person clicked the link Auth0 emailed to them.

    Without this check anybody could type in someone else's Nova address.
    Clicking the link proves they can read that mailbox.
    """
    return user_info.get("email_verified") is True


def verified_nova_email(user_info: dict) -> str | None:
    """Return the email of a person who may use the app, or None.

    This puts the two checks above together: a Nova address AND a confirmed
    email. Every page calls this before it shows or changes anything.
    """
    email = nova_email(user_info)
    if email is None or not email_is_verified(user_info):
        return None
    return email


# --- After the confirmation link is clicked -----------------------------------
#
# When someone signs in, Streamlit keeps a copy of what Auth0 said about them
# in a cookie. If they had not clicked the link yet, that copy says
# "email_verified: false" and it does not change when they click the link
# later. Instead of making them sign out and in again, we ask Auth0 directly
# whether the email is confirmed now.


def with_fresh_verification(user_info: dict, auth0_answer: dict) -> dict:
    """Return `user_info`, marked as verified if Auth0 now says it is.

    `auth0_answer` is what Auth0 just told us about the person. We only trust
    it if it is about the same account and the same email address.
    """
    same_account = auth0_answer.get("sub") is not None and auth0_answer.get("sub") == user_info.get("sub")
    same_email = nova_email(auth0_answer) is not None and nova_email(auth0_answer) == nova_email(user_info)
    if same_account and same_email and email_is_verified(auth0_answer):
        return {**user_info, "email_verified": True}
    return user_info


def ask_auth0_about_user() -> dict:
    """Ask Auth0 who is logged in right now. Returns {} if that fails.

    This uses the "access" token from the login, which Streamlit only hands
    to us when `expose_tokens = "access"` is set in .streamlit/secrets.toml.
    """
    import requests
    import streamlit as st

    token = st.user.tokens.get("access")
    if not token:
        return {}
    metadata_url = st.secrets["auth"]["auth0"]["server_metadata_url"]
    userinfo_url = metadata_url.replace("/.well-known/openid-configuration", "/userinfo")
    try:
        response = requests.get(userinfo_url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except requests.RequestException:
        return {}
    if response.status_code != 200:
        return {}
    return response.json()


def logged_in_user() -> dict:
    """What we know about the person using the app, with the email check up to date.

    Pages pass this to `verified_nova_email()` instead of `st.user.to_dict()`.
    Auth0 is asked at most once per visit after the email is confirmed.
    """
    import streamlit as st

    user_info = st.user.to_dict()
    if not st.user.is_logged_in or email_is_verified(user_info):
        return user_info
    # Remember a confirmed email for this visit, so we do not ask Auth0 again.
    if st.session_state.get("email_confirmed_for") == user_info.get("sub"):
        return {**user_info, "email_verified": True}
    user_info = with_fresh_verification(user_info, ask_auth0_about_user())
    if email_is_verified(user_info):
        st.session_state["email_confirmed_for"] = user_info.get("sub")
    return user_info


# --- Sending the confirmation email again --------------------------------------
#
# Auth0's sign-in page has no "send the email again" button, so the app offers
# one. Asking Auth0 to send it needs a second Auth0 application of the type
# "Machine to Machine", allowed only "update:users" on the Auth0 Management API.
# Its ID and secret are in the [auth0_management] section of
# .streamlit/secrets.toml.

RESEND_WAIT_SECONDS = 60


def may_resend(last_sent_at: float | None, now: float) -> bool:
    """True if the email was not sent again in the last minute.

    This stops one person from filling someone's inbox by pressing the button
    over and over. `last_sent_at` and `now` are times in seconds.
    """
    return last_sent_at is None or now - last_sent_at >= RESEND_WAIT_SECONDS


def may_ask_for_new_email(user_info: dict) -> bool:
    """True for a logged-in Nova student whose email is not confirmed yet."""
    return bool(user_info.get("sub")) and nova_email(user_info) is not None and not email_is_verified(user_info)


def resend_verification_email(user_info: dict) -> bool:
    """Ask Auth0 to send the confirmation email again. True if Auth0 agreed.

    The account comes from the login (`sub`), never from a form, so nobody can
    send emails to someone else's address.
    """
    import requests
    import streamlit as st

    if not may_ask_for_new_email(user_info):
        return False
    try:
        management = st.secrets["auth0_management"]
        login_app_id = st.secrets["auth"]["auth0"]["client_id"]
        metadata_url = st.secrets["auth"]["auth0"]["server_metadata_url"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return False
    auth0_address = metadata_url.replace("/.well-known/openid-configuration", "")

    try:
        # 1. Get a short-lived pass for the Management API.
        token_response = requests.post(
            f"{auth0_address}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": management["client_id"],
                "client_secret": management["client_secret"],
                "audience": f"{auth0_address}/api/v2/",
            },
            timeout=10,
        )
        if token_response.status_code != 200:
            return False
        token = token_response.json()["access_token"]

        # 2. Ask Auth0 to send the email. "client_id" makes the link in the
        #    email lead back to our app.
        send_response = requests.post(
            f"{auth0_address}/api/v2/jobs/verification-email",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_id": user_info["sub"], "client_id": login_app_id},
            timeout=10,
        )
    except (requests.RequestException, KeyError, ValueError):
        return False
    return send_response.status_code == 201


# --- Admins -------------------------------------------------------------------
#
# Admins handle the reports students send. Who is an admin is written in
# .streamlit/secrets.toml, not in the code:
#
#     [admin]
#     emails = ["someone@novasbe.pt"]


def is_admin(email: str | None, admin_emails: list[str] | None) -> bool:
    """True if `email` is on the list of admin emails (upper/lower case does not matter)."""
    email = (email or "").strip().lower()
    if not email:
        return False
    admins = [(admin or "").strip().lower() for admin in (admin_emails or [])]
    return email in admins


def admin_emails() -> list[str]:
    """The admin emails from .streamlit/secrets.toml. No [admin] section = no admins."""
    import streamlit as st

    try:
        return list(st.secrets["admin"]["emails"])
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return []
