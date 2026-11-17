"""Public profile: what other students see about one student.

The address of this page ends in ?id= and the number of a profile, for
example /student?id=7. Other pages link to a student like this:

    st.page_link("views/public_profile.py", label="Maria Silva", query_params={"id": 7})

Without a number the page shows the visitor's own profile.
"""

from datetime import date

import streamlit as st

import database
from accounts import verified_nova_email
from listings import format_price
from profiles import profile_id_from_text, public_profile

# Only verified Nova students may look at profiles.
email = verified_nova_email(st.user.to_dict())
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

if profile["email"] == email:
    st.info("This is your own profile, as other students see it.")
    st.page_link("views/profile.py", label="Edit my profile")

photo_column, text_column = st.columns([1, 3])
with photo_column:
    if shown["photo_path"]:
        st.image(database.photo_url(shown["photo_path"]), width=160)
with text_column:
    st.header(shown["name"])
    st.write(shown["program"])
    if shown["leaving_lisbon_on"]:
        st.write(f"Leaving Lisbon on {shown['leaving_lisbon_on']:%d %B %Y}")
    st.caption(f"Member since {shown['member_since']:%B %Y}")

# Nobody reports themselves, so the Report links only show on other profiles.
is_own_profile = profile["email"] == email
if not is_own_profile:
    st.page_link("views/report.py", label="Report this student",
                 query_params={"student": shown["id"]})

st.subheader("Active listings")
listings = database.get_active_listings(shown["id"])
if not listings:
    st.write("No active listings at the moment.")
for listing in listings:
    title_column, link_column = st.columns([4, 1])
    # st.text shows the title as it is, so a title can't add links or formatting.
    title_column.text(f"{listing['title']} - {format_price(listing['price_cents'])}")
    if not is_own_profile:
        link_column.page_link("views/report.py", label="Report",
                              query_params={"listing": listing["id"]})
