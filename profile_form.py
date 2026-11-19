"""The profile form, used on "My profile" and in the first Welcome step.

It shows the fields, checks them with the rules in profiles.py and saves
the profile of `email`. The email always comes from the login, so a student
can only ever fill in their own profile.
"""

from datetime import date

import streamlit as st

import database
from profiles import (
    MAX_NAME_LENGTH,
    MAX_PHOTO_MB,
    PROGRAMS,
    clean_name,
    prepare_photo,
    profile_problems,
)


def show_profile_form(email: str, profile: dict | None, save_label: str = "Save profile") -> None:
    """Show the profile fields and save them when the button is pressed.

    `profile` is what is stored so far (None for a new student). After a
    save, st.session_state["profile_saved"] is True and the page reloads.
    """
    profile = profile or {}
    saved_program = profile.get("program")
    saved_photo = profile.get("photo_path")
    saved_date = None
    if profile.get("leaving_lisbon_on"):
        saved_date = date.fromisoformat(profile["leaving_lisbon_on"])

    # --- The fields -----------------------------------------------------------

    name = st.text_input(
        "Name",
        value=profile.get("name", ""),
        max_chars=MAX_NAME_LENGTH,
        placeholder="First and last name",
    )

    program = st.selectbox(
        "Program",
        PROGRAMS,
        index=PROGRAMS.index(saved_program) if saved_program in PROGRAMS else None,
        placeholder="Choose your program",
    )

    leaving_lisbon_on = None
    if st.checkbox(
        "I know when I am leaving Lisbon",
        value=saved_date is not None,
        help="Shown on your profile, so buyers know your items must go by then.",
    ):
        leaving_lisbon_on = st.date_input(
            "Leaving Lisbon on", value=saved_date or date.today(), format="DD/MM/YYYY"
        )

    # The upload box gets a new key after every save, which empties it again.
    upload_round = st.session_state.get("photo_upload_round", 0)
    photo_column, upload_column = st.columns([1, 3])
    with upload_column:
        uploaded = st.file_uploader(
            "Profile photo (optional)",
            type=["jpg", "jpeg", "png", "webp"],
            max_upload_size=MAX_PHOTO_MB,
            key=f"photo_upload_{upload_round}",
            help="Students reply more often to someone with a real photo.",
        )
        remove_photo = saved_photo is not None and uploaded is None and st.checkbox(
            "Remove my current photo"
        )
    with photo_column:
        # Show the new photo right away, before it is saved.
        if uploaded is not None:
            st.image(uploaded, width=120, caption="New photo")
        elif saved_photo and not remove_photo:
            st.image(database.photo_url(saved_photo), width=120)

    # --- Saving ---------------------------------------------------------------

    if st.button(save_label, type="primary"):
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
            return

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
