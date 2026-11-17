"""My profile: a student fills in or changes their own profile."""

from datetime import date

import streamlit as st

import database
from accounts import verified_nova_email
from profiles import (
    MAX_NAME_LENGTH,
    MAX_PHOTO_MB,
    PROGRAMS,
    clean_name,
    prepare_photo,
    profile_problems,
)

# Who is using this page? The email always comes from the login, never from
# a form, so nobody can open or change someone else's profile here.
email = verified_nova_email(st.user.to_dict())
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

# What is stored so far. A new student has nothing stored yet.
if profile is None:
    profile = {}
saved_program = profile.get("program")
saved_photo = profile.get("photo_path")
saved_date = None
if profile.get("leaving_lisbon_on"):
    saved_date = date.fromisoformat(profile["leaving_lisbon_on"])

# --- The fields ---------------------------------------------------------------

if saved_photo:
    st.image(database.photo_url(saved_photo), width=160)

name = st.text_input("Name", value=profile.get("name", ""), max_chars=MAX_NAME_LENGTH)

program = st.selectbox(
    "Program",
    PROGRAMS,
    index=PROGRAMS.index(saved_program) if saved_program in PROGRAMS else None,
    placeholder="Choose your program",
)

leaving_lisbon_on = None
if st.checkbox("I know when I am leaving Lisbon", value=saved_date is not None):
    leaving_lisbon_on = st.date_input(
        "Leaving Lisbon on", value=saved_date or date.today(), format="DD/MM/YYYY"
    )

# The upload box gets a new key after every save, which empties it again.
upload_round = st.session_state.get("photo_upload_round", 0)
uploaded = st.file_uploader(
    "Profile photo (optional)",
    type=["jpg", "jpeg", "png", "webp"],
    max_upload_size=MAX_PHOTO_MB,
    key=f"photo_upload_{upload_round}",
)
remove_photo = saved_photo is not None and st.checkbox("Remove my current photo")

# --- Saving -------------------------------------------------------------------

if st.button("Save profile", type="primary"):
    name = clean_name(name)
    problems = profile_problems(name, program, leaving_lisbon_on, date.today())

    new_photo = None
    if uploaded is not None:
        try:
            new_photo = prepare_photo(uploaded.getvalue())
        except ValueError as error:
            problems.append(str(error))

    if problems:
        for problem in problems:
            st.error(problem)
    else:
        if new_photo is not None:
            photo_path = database.upload_photo(new_photo)
        elif remove_photo:
            photo_path = None
        else:
            photo_path = saved_photo

        database.save_profile(email, name, program, leaving_lisbon_on, photo_path)

        # The old photo is not shown anywhere any more, so remove the file.
        if saved_photo and saved_photo != photo_path:
            database.delete_photo(saved_photo)

        st.session_state["profile_saved"] = True
        st.session_state["photo_upload_round"] = upload_round + 1
        st.rerun()
