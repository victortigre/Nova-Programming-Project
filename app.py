"""Nova Marketplace - the file that starts the app.

Run it with:  streamlit run app.py

Every visit starts here. First it checks who is at the door. Only a
verified Nova student gets through to the pages listed at the bottom.
"""

import streamlit as st

import database
from accounts import admin_emails, email_is_verified, is_admin, logged_in_user, nova_email


def login_is_set_up() -> bool:
    """True when .streamlit/secrets.toml holds real login settings."""
    try:
        settings = st.secrets["auth"]["auth0"]
        values = [settings["client_id"], settings["client_secret"], settings["server_metadata_url"]]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return False
    return all(value and "PASTE" not in value for value in values)


st.title("Nova Marketplace")

# 1. The login and the database have to be configured on this computer first.
if not login_is_set_up():
    st.warning(
        "The login is not set up on this computer yet. "
        "Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` "
        "and fill in the three values from Auth0."
    )
    st.stop()

if not database.database_is_set_up():
    st.warning(
        "The database is not set up on this computer yet. "
        "Add the two `[supabase]` values to `.streamlit/secrets.toml` "
        "(see `.streamlit/secrets.toml.example`)."
    )
    st.stop()

# 2. Nobody is logged in: show the sign-in button and nothing else.
if not st.user.is_logged_in:
    st.write("Sign in or sign up with your @novasbe.pt email to continue.")
    if st.button("Sign in / Sign up"):
        st.login("auth0")
    st.stop()

user_info = logged_in_user()
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
        "Click it, then come back here and press the button below."
    )
    # Pressing the button runs this file again, and logged_in_user() then
    # asks Auth0 whether the email is confirmed now.
    if st.button("I clicked the link", type="primary"):
        st.caption(
            "Your email is not confirmed yet. If you did click the link, "
            "sign in again to finish."
        )
        st.button("Sign in again", on_click=st.login, args=("auth0",))
    st.button("Sign out", on_click=st.logout)
    st.stop()

# 5. An admin blocked this student: no entry.
profile = database.get_profile(email)
if profile is not None and profile.get("blocked_at"):
    st.error("Your account has been blocked because it broke the house rules.")
    st.button("Sign out", on_click=st.logout)
    st.stop()

# 6. A verified Nova student is logged in: show the pages.
with st.sidebar:
    st.write(f"Signed in as {email}")
    st.button("Sign out", on_click=st.logout)

# Every page of the app is listed here. The files live in the views folder.
pages = [
    st.Page("views/profile.py", title="My profile"),
    st.Page("views/sell_item.py", title="Sell an item"),
    st.Page("views/my_listings.py", title="My listings"),
    st.Page("views/house_rules.py", title="House rules"),
    # Opened through links to one student, so it is not shown in the menu.
    st.Page(
        "views/public_profile.py",
        title="Student profile",
        url_path="student",
        visibility="hidden",
    ),
    # Opened through the "Report" links on a listing or a profile.
    st.Page(
        "views/report.py",
        title="Report",
        url_path="report",
        visibility="hidden",
    ),
]
# Only admins get the Admin page. The admin.py functions check it again.
if is_admin(email, admin_emails()):
    pages.append(st.Page("views/admin.py", title="Admin"))
st.navigation(pages).run()
