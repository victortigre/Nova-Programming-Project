"""Nova Marketplace - start page.

Run it with:  streamlit run app.py

Right now this page only tests the login.
"""

import streamlit as st

from accounts import email_is_verified, nova_email


def login_is_set_up() -> bool:
    """True when .streamlit/secrets.toml holds real login settings."""
    try:
        settings = st.secrets["auth"]["auth0"]
        values = [settings["client_id"], settings["client_secret"], settings["server_metadata_url"]]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return False
    return all(value and "PASTE" not in value for value in values)


st.title("Nova Marketplace")

# 1. The login has to be configured on this computer first.
if not login_is_set_up():
    st.warning(
        "The login is not set up on this computer yet. "
        "Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` "
        "and fill in the three values from Auth0."
    )
    st.stop()

# 2. Nobody is logged in: show the sign-in button and nothing else.
if not st.user.is_logged_in:
    st.write("Sign in or sign up with your @novasbe.pt email to continue.")
    if st.button("Sign in / Sign up"):
        st.login("auth0")
    st.stop()

user_info = st.user.to_dict()
email = nova_email(user_info)

# 3. Logged in, but not with a Nova address: no entry.
if email is None:
    st.error("Only @novasbe.pt email addresses can use Nova Marketplace.")
    st.button("Sign out", on_click=st.logout)
    st.stop()

# 4. Nova address, but the emailed link was not clicked yet: no entry.
if not email_is_verified(user_info):
    st.info(
        f"We sent a confirmation link to {email}. "
        "Click it, then sign out here and sign in again."
    )
    st.button("Sign out", on_click=st.logout)
    st.stop()

# 5. A verified Nova student is logged in.
st.success(f"Signed in as {email}")
st.button("Sign out", on_click=st.logout)

# Test only - remove before the real app goes live.
with st.expander("What Auth0 told the app about you (test only)"):
    st.json(user_info)
