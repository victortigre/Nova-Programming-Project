"""Nova Marketplace - the file that starts the app.

Run it with:  streamlit run app.py

Every visit starts here. First it checks who is at the door. Only a
verified Nova student gets through to the pages listed at the bottom.
"""

import streamlit as st

import database
import deals
import messaging_repository
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


# Shown along the bottom of the landing page, moving from right to left.
THINGS_STUDENTS_SELL = [
    "Road bikes", "Surfboards", "Beds", "Desks", "Textbooks", "Guitars",
    "Monitors", "Coffee machines", "Wetsuits", "Plants", "Calculators", "Sofas",
]


def show_landing_page() -> None:
    """The first thing a visitor sees: what the app is, and the sign-in button."""
    st.set_page_config(layout="wide")
    st.logo("static/logo-white.png", size="large")  # white, for the dark photo
    st.html(ui.LANDING_CSS)
    with st.container(key="landing"):
        st.html(
            '<span class="nm-dark-badge">ONLY FOR @NOVASBE.PT STUDENTS</span>'
            '<div class="nm-serif">From students, for students.</div>'
            '<p class="nm-sub">Buy and sell second-hand with people on your campus. '
            "The marketplace of Nova SBE, Carcavelos.</p>"
        )
        with st.container(horizontal_alignment="center"):
            if st.button("Sign in or create an account"):
                st.login("auth0")
        st.html('<p class="nm-hint">Use your @novasbe.pt student email to get in.</p>')

        # The list is written twice in a row, so the movement can loop without a jump.
        names = "".join(f"<span>{name}</span>" for name in THINGS_STUDENTS_SELL)
        with st.container(key="landing-items"):
            st.html(f'<div class="nm-items"><div class="nm-items-track">{names}{names}</div></div>')


# The browser tab shows this name and icon on every page.
# "About" in the ⋮ menu names the photographer of the landing page photo,
# which its licence (CC BY-SA 4.0) asks for.
ABOUT = (
    "**Nova Marketplace** is made by Nova SBE students as a course project.\n\n"
    "Landing page photo: Miguelmcorreia, "
    "[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Nova_SBE_3.jpg), "
    "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), cropped."
)
# Every page uses the full width of the screen. Set once here, so the width
# does not change depending on which page was opened first.
st.set_page_config(page_title="Nova Marketplace", page_icon="static/icon.png",
                   layout="wide", menu_items={"About": ABOUT})
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

# 4. Nova address, but the email was not confirmed yet: no entry.
# Auth0 confirms the email with a code typed in while signing up. We do not
# use links for this: the university's mail filter opens every link in an
# email by itself, which confirmed accounts nobody had confirmed.
if not email_is_verified(user_info):
    st.header("Confirm your email")
    st.info(
        f"Your email **{email}** is not confirmed yet. "
        "Sign in again and type in the code we email you."
    )
    st.caption(
        "No code in your inbox after a few minutes? Look in your Junk or Spam folder. "
        "The email comes from Auth0, the service that handles our sign-in."
    )
    st.button("Sign in again", type="primary", on_click=st.login, args=("auth0",))
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
# "My listings (2)" and "My purchases (1)": how many deals wait for this student to
# do something (see deals.to_do). If buying isn't set up in the database yet,
# the menu simply shows no numbers.
def attention_counts():
    """The numbers behind the menu badges and the Browse notifications: deal tasks,
    unread chats (Inbox), and offers waiting for an answer. Each part falls back to
    0/empty if its table isn't set up yet, so the menu still loads."""
    try:
        tasks = deals.to_do(database, email)
    except Exception:
        tasks = {"sales": 0, "purchases": 0}
    # Everything below asks "who is signed in" and "which chats" only once.
    with messaging_repository.checked_once():
        try:
            unread = len(messaging_repository.unread_conversations())
        except Exception:
            unread = 0
        try:
            offers = len(messaging_repository.offers_to_answer())
        except Exception:
            offers = 0
        try:
            answers = messaging_repository.offer_statuses()
        except Exception:
            answers = ()
    return tasks, unread, offers, answers


def attention_signature(tasks, unread, offers, answers=()):
    """A small fingerprint of everything shown in the badges and notifications,
    so the auto-refresh below can tell when something new has arrived. `answers`
    is the status of the offers in this student's chats: it changes when the
    other person accepts or declines, so an open chat then updates by itself."""
    return (unread, offers, tuple(sorted(tasks.items())), answers)


def with_count(title: str, count: int) -> str:
    return f"{title} ({count})" if count else title


# Live updates with no action from the user: every few seconds this quietly
# recomputes the counts and, only if a new message/offer/request has arrived,
# reruns the whole app so the menu badge AND the Browse notifications refresh on
# their own. It's an in-place rerun (not a browser reload) and happens only when
# something changed, so there's no flicker while nothing is going on.
@st.fragment(run_every="5s")
def live_updates():
    # While the whole page loads, the counts were asked for a moment ago (below).
    # Asking again right away would only make every click slower.
    if st.session_state.pop("attention_just_counted", False):
        return
    if attention_signature(*attention_counts()) != st.session_state.get("attention_signature"):
        st.rerun(scope="app")


# One page load = one check of the signed-in student and one request for their
# chats, shared by the menu counts here and by the page that is shown below
# (see checked_once in messaging_repository.py).
with messaging_repository.checked_once():
    # A listing card on a profile page was clicked (ui.open_on_browse): this run
    # only leads to Browse, which counts again. So it shows the counts from a
    # moment ago instead of asking the database twice for one click.
    jump_to_listing = st.session_state.pop("jump_to_listing", None)
    if jump_to_listing is not None and "attention_counts" in st.session_state:
        counts = st.session_state["attention_counts"]
    else:
        counts = st.session_state["attention_counts"] = attention_counts()
    # The Inbox count works like Instagram's direct messages: chats with messages this
    # student hasn't opened yet. 0 (no badge) if messaging isn't set up in the database.
    to_do, unread_inbox, offers_waiting, offer_answers = counts
    # Remember what the menu and notifications show right now, so the timer above only
    # reruns the page when a NEW message/offer/request actually appears.
    st.session_state["attention_signature"] = attention_signature(
        to_do, unread_inbox, offers_waiting, offer_answers)

    browse = st.Page("views/browse.py", title="Browse", icon=":material/search:", default=True)
    pages = [
        browse,
        st.Page("views/sell_item.py", title="Sell an item", icon=":material/add_circle:"),
        # Your own items and the buyers who asked for them, on one page.
        st.Page("views/my_listings.py", title=with_count("My listings", to_do["sales"]),
                icon=":material/inventory_2:"),
        st.Page("views/purchases.py", title=with_count("My purchases", to_do["purchases"]),
                icon=":material/shopping_bag:"),
        st.Page("views/messaging.py", title=with_count("Inbox", unread_inbox),
                icon=":material/chat:"),
        st.Page("views/profile.py", title="My profile", icon=":material/person:"),
        # Linked from "My profile" and "Sell an item", so it is not shown in the menu.
        st.Page("views/house_rules.py", title="House rules", icon=":material/gavel:",
                visibility="hidden"),
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
    if jump_to_listing is not None:
        st.switch_page("views/browse.py", query_params=jump_to_listing)

    # Which listing is open on Browse is part of the address (/?listing=12, see
    # views/browse.py). The logo and "Browse" in the menu lead to the address
    # without it, so they always show the full list of items.

    st.session_state["attention_just_counted"] = True
    live_updates()
    navigation.run()
