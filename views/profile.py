"""My profile: a student fills in or changes their own profile, and sees the
listings they saved (tapped ♡ on)."""

from functools import partial

import streamlit as st

import browsing
import database
import ui
from accounts import logged_in_user, verified_nova_email
from profile_form import show_profile_form

# Who is using this page? The email always comes from the login, never from
# a form, so nobody can open or change someone else's profile here.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("My profile")

profile = database.get_profile(email)

if st.session_state.pop("profile_saved", False):
    st.success("Your profile is saved.")
elif profile is None:
    st.info("Welcome! Fill in your profile so other students know who they are dealing with.")

if profile is not None:
    st.page_link(
        "views/public_profile.py",
        label="See my profile as other students see it",
        query_params={"id": profile["id"]},
    )

with ui.card("profile-form"):
    show_profile_form(email, profile)

# --- Saved items ---------------------------------------------------------------
# The listings this student liked. Tapping ♥ removes one; tapping the price
# opens it on Browse, the same way a student's public profile does.
SAVED_COLUMNS = 3


def unsave(listing_id: int) -> None:
    browsing.toggle_saved(database, profile["id"], listing_id)


if profile is not None:
    with ui.card("saved-items"):
        try:
            saved_items = browsing.saved_listings(database, profile["id"])
        except Exception:
            saved_items = None
        st.html(f'<p style="font-weight: 600; margin: 0;">{ui.heart_icon(18)} '
                f"Saved items ({len(saved_items or [])})</p>")
        if saved_items is None:
            st.caption("Saving isn't set up in the database yet. Whoever manages the "
                       "database needs to run `database_setup.sql`.")
        elif not saved_items:
            ui.hint_with_heart("You haven't saved anything yet. "
                               "Tap {heart} on a listing to keep it here.")
            st.page_link("views/browse.py", label="Browse items", icon=":material/search:")
        else:
            # One request for all cover photo links, instead of one per card.
            links = database.listing_photo_urls(
                [item["photo_paths"][0] for item in saved_items if item["photo_paths"]])
            for start in range(0, len(saved_items), SAVED_COLUMNS):
                row = st.columns(SAVED_COLUMNS, gap="medium")
                for column, item in zip(row, saved_items[start:start + SAVED_COLUMNS]):
                    cover = item["photo_paths"][0] if item["photo_paths"] else None
                    with column:
                        clicked = ui.listing_card(
                            item, links.get(cover), key=f"saved-{item['id']}",
                            saved=True, on_heart=partial(unsave, item["id"]))
                    if clicked:
                        st.session_state["open_listing"] = item["id"]
                        st.switch_page("views/browse.py")

# The menu bar has no room for the account, so signing out is here.
with ui.card("account"):
    st.markdown("**Account**")
    st.caption(f"Signed in as {email}")
    st.page_link("views/house_rules.py", label="House rules", icon=":material/gavel:")
    st.button("Sign out", icon=":material/logout:", on_click=st.logout)
