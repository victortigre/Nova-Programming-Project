"""Public profile: what other students see about one student.

The address of this page ends in ?id= and the number of a profile, for
example /student?id=7. Other pages link to a student like this:

    st.page_link("views/public_profile.py", label="Maria Silva", query_params={"id": 7})

Without a number the page shows the visitor's own profile.
"""

from datetime import date

import streamlit as st

import database
import ui
from accounts import logged_in_user, verified_nova_email
from listings import plain_text
from profiles import profile_id_from_text, public_profile

# Only verified Nova students may look at profiles.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

# Which profile? The number in the address, or else the visitor's own.
if "id" in st.query_params:
    profile_id = profile_id_from_text(st.query_params["id"])
    profile = database.get_profile_by_id(profile_id) if profile_id else None
else:
    profile = database.get_profile(email)
    if profile is None:
        st.header("My public profile")
        st.info("You have not filled in your profile yet.")
        st.page_link("views/profile.py", label="Fill in my profile")
        st.stop()

if profile is None:
    st.header("Profile not found")
    st.write("This profile does not exist.")
    st.stop()

# From here on only the public parts are used, so the email cannot slip out.
shown = public_profile(profile, date.today())
is_own_profile = profile["email"] == email

# The listings are shown as a grid, which needs the full width of the screen.
st.set_page_config(layout="wide")

if is_own_profile:
    st.info("This is your own profile, as other students see it.")
    st.page_link("views/profile.py", label="Edit my profile", icon=":material/edit:")

listings = database.get_active_listings(shown["id"])

with ui.card("profile-head"):
    photo_column, text_column = st.columns([1, 5], vertical_alignment="center")
    with photo_column:
        st.html(ui.avatar(database.photo_url(shown["photo_path"]), shown["name"]))
    with text_column:
        st.header(plain_text(shown["name"]))
        chips = ui.chip("✓ Verified Nova student") + ui.chip(shown["program"])
        if shown["leaving_lisbon_on"]:
            days = (shown["leaving_lisbon_on"] - date.today()).days
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            chips += ui.chip(
                f"Leaving Lisbon on {shown['leaving_lisbon_on']:%d %B} ({when})", warm=True
            )
        st.html(chips)
        st.caption(f"Member since {shown['member_since']:%B %Y} · "
                   f"{len(listings)} active listing{'s' if len(listings) != 1 else ''}")

st.subheader("Active listings")
if not listings:
    st.write("No active listings at the moment.")
columns_per_row = 4
for start in range(0, len(listings), columns_per_row):
    row = st.columns(columns_per_row, gap="medium")
    for column, listing in zip(row, listings[start:start + columns_per_row]):
        cover = listing["photo_paths"][0] if listing.get("photo_paths") else None
        with column:
            clicked = ui.listing_card(
                listing, database.listing_photo_url(cover) if cover else None,
                key=f"profile-{listing['id']}",
            )
        # The price button opens the listing on Browse, where it can be saved or reported.
        if clicked:
            st.session_state["open_listing"] = listing["id"]
            st.switch_page("views/browse.py")

# Nobody reports themselves, so the Report link only shows on other profiles.
if not is_own_profile:
    st.write("")
    st.page_link("views/report.py", label="Report this student", icon=":material/flag:",
                 query_params={"student": shown["id"]})
