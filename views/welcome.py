"""Welcome: the first steps of a new student.

Until a student has a profile and has agreed to the house rules, app.py
shows only this page, so nobody can sell, message or report before that.

    Step 1  fill in the profile
    Step 2  read the house rules and agree to them
    Step 3  "You're in!" with a button to browse and one to sell
"""

import streamlit as st

import database
import ui
from accounts import logged_in_user, verified_nova_email
from house_rules_text import show_house_rules
from profile_form import show_profile_form
from profiles import DONE, PROFILE_STEP, RULES_STEP, onboarding_step

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

profile = database.get_profile(email)
step = onboarding_step(profile)
st.session_state.pop("profile_saved", None)  # step 2 itself shows the profile was saved

STEP_NUMBERS = {PROFILE_STEP: 1, RULES_STEP: 2, DONE: 3}
st.progress(STEP_NUMBERS[step] / 3, text=f"Step {STEP_NUMBERS[step]} of 3")

if step == PROFILE_STEP:
    st.header("Welcome to Nova Marketplace!")
    st.write(
        "First, tell other students who you are. It takes about a minute. "
        "Your email is never shown to anyone."
    )
    with ui.card("welcome-profile"):
        show_profile_form(email, None, save_label="Continue")

elif step == RULES_STEP:
    st.header("Our house rules")
    st.write(f"Thanks, {profile['name'].split()[0]}! One last thing before you start.")
    with ui.card("welcome-rules"):
        with st.container(height=360, border=False):
            show_house_rules()
        agreed = st.checkbox("I have read the house rules and will keep to them")
        continued = st.button("Continue", type="primary", disabled=not agreed)
    if continued:
        database.accept_house_rules(email)
        # app.py opens all pages now, and sends the student back here for step 3.
        st.session_state["onboarding_just_finished"] = True
        st.rerun()

else:
    st.header("You're in! 🎉")
    st.write("Your profile is ready. What would you like to do first?")
    browse_column, sell_column = st.columns(2)
    with browse_column:
        with ui.card("welcome-browse"):
            st.markdown("**Find something**")
            st.caption("See what other students are selling or giving away.")
            st.page_link("views/browse.py", label="Start browsing", icon=":material/search:")
    with sell_column:
        with ui.card("welcome-sell"):
            st.markdown("**Sell or give away**")
            st.caption("Put your first item online in a couple of minutes.")
            st.page_link("views/sell_item.py", label="Sell an item", icon=":material/sell:")
    st.page_link("views/public_profile.py", label="See my profile as others see it",
                 icon=":material/person:")

# There is no menu during the Welcome steps, so signing out is offered here.
st.write("")
st.button("Sign out", icon=":material/logout:", type="tertiary", on_click=st.logout)
