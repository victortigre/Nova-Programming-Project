"""Nova Marketplace - the file that starts the app.

Run it with:  streamlit run app.py

Every visit starts here. First it checks who is at the door. Only a
verified Nova student gets through to the pages listed at the bottom.
"""

import streamlit as st

import database
import ui
from accounts import admin_emails, email_is_verified, is_admin, logged_in_user, nova_email
from profiles import DONE, onboarding_step


def login_is_set_up() -> bool:
    """True when .streamlit/secrets.toml holds real login settings."""
    try:
        settings = st.secrets["auth"]["auth0"]
        values = [settings["client_id"], settings["client_secret"], settings["server_metadata_url"]]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return False
    return all(value and "PASTE" not in value for value in values)


def show_landing_page() -> None:
    """The first thing a visitor sees: what the app is, and the sign-in button."""
    with st.container(key="hero"):
        st.html(
            "<h1 style='margin:0;font-size:2.6rem;line-height:1.15'>"
            "Buy and sell with<br>Nova SBE students</h1>"
            "<p style='font-size:1.1rem;opacity:.9;margin:.8rem 0 0'>"
            "Furniture, books, bikes and more, from students on campus and from "
            "everyone who is leaving Lisbon.</p>"
        )
        if st.button("Sign in or create an account", icon=":material/arrow_forward:",
                     icon_position="right"):
            st.login("auth0")
        st.html("<p style='font-size:.85rem;opacity:.8;margin:0'>"
                "Use your @novasbe.pt email. New here? You can create an account "
                "on the next screen.</p>")

    columns = st.columns(3)
    benefits = [
        (":material/verified_user:", "Nova students only",
         "Every account is a confirmed @novasbe.pt address."),
        (":material/handshake:", "Meet on campus",
         "Hand items over on campus or nearby. No shipping."),
        (":material/money_off:", "Free to use",
         "No fees. Putting an item online takes a couple of minutes."),
    ]
    for number, (column, (icon, title, text)) in enumerate(zip(columns, benefits)):
        with column, ui.card(f"benefit-{number}"):
            st.markdown(f"### {icon}")
            st.markdown(f"**{title}**")
            st.caption(text)


# The browser tab shows this name and icon on every page.
st.set_page_config(page_title="Nova Marketplace", page_icon="static/icon.png")
st.logo("static/logo.png", size="large")
ui.apply_style()

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
    show_landing_page()
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
    st.header("Confirm your email")
    st.info(
        f"We sent a confirmation link to **{email}**. "
        "Click it, then come back here and press the button below."
    )
    st.caption(
        "Nothing in your inbox after a few minutes? Look in your Junk or Spam folder. "
        "The email comes from Auth0, the service that handles our sign-in."
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

# 6. A new student first goes through the Welcome steps (profile, house
# rules). Until then this is the only page that exists for them, so the
# other pages cannot be opened, not even by typing their address.
if onboarding_step(profile) != DONE:
    welcome = st.Page("views/welcome.py", title="Welcome", url_path="welcome")
    st.navigation([welcome], position="hidden").run()
    st.stop()

# 7. A verified Nova student who finished the Welcome steps: show the pages.
# Every page of the app is listed here, in the menu bar at the top. The files
# live in the views folder. Sign out is on "My profile".
browse = st.Page("views/browse.py", title="Browse", icon=":material/search:", default=True)
pages = [
    browse,
    st.Page("views/sell_item.py", title="Sell an item", icon=":material/add_circle:"),
    st.Page("views/my_listings.py", title="My listings", icon=":material/inventory_2:"),
    st.Page("views/purchases.py", title="My purchases", icon=":material/shopping_bag:"),
    st.Page("views/sales.py", title="Sales", icon=":material/sell:"),
    st.Page("views/profile.py", title="My profile", icon=":material/person:"),
    st.Page("views/house_rules.py", title="House rules", icon=":material/gavel:"),
    # Opened through links to one student, so it is not shown in the menu.
    st.Page("views/public_profile.py", title="Student profile", url_path="student",
            visibility="hidden"),
    # Opened through the "Report" links on a listing or a profile.
    st.Page("views/report.py", title="Report", url_path="report", visibility="hidden"),
    # The last Welcome step ("You're in!") is shown once, right after the rules.
    st.Page("views/welcome.py", title="Welcome", url_path="welcome", visibility="hidden"),
]
# Only admins get the Admin page. The admin.py functions check it again.
if is_admin(email, admin_emails()):
    pages.append(st.Page("views/admin.py", title="Admin", icon=":material/flag:"))

navigation = st.navigation(pages, position="top")
if st.session_state.pop("onboarding_just_finished", False):
    st.switch_page("views/welcome.py")

# Clicking the logo (or "Browse" in the menu) from another page always shows
# the full list of items, not the listing that happened to be open last time.
came_from = st.session_state.get("last_page")
st.session_state["last_page"] = navigation.url_path
if navigation.url_path == browse.url_path and came_from != browse.url_path:
    st.session_state.pop("view_listing", None)
navigation.run()
