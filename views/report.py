"""Report: tell the admins about a bad listing or another student.

The address of this page says what is reported, for example
/report?listing=12 or /report?student=7. Other pages link here like this:

    st.page_link("views/report.py", label="Report", query_params={"listing": 12})

The person who reports is always the logged-in student, never a form field.
reports.create_report checks every rule again before anything is stored.
"""

import streamlit as st

import database
import reports
from accounts import verified_nova_email
from profiles import profile_id_from_text

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(st.user.to_dict())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("Report")

if database.get_profile(email) is None:
    st.info("Fill in your profile first. After that you can send reports.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()

# What is reported? Anybody can type anything in the address, so the number
# is read with profile_id_from_text, which only accepts plain digits.
listing_id = None
reported_profile_id = None
if "listing" in st.query_params:
    listing_id = profile_id_from_text(st.query_params["listing"])
    listing = database.get_listing(listing_id) if listing_id else None
    if listing is None:
        st.write("This listing does not exist (any more).")
        st.stop()
    st.write("You are reporting this listing:")
    st.text(listing["title"])  # st.text shows the title as it is, without formatting
elif "student" in st.query_params:
    reported_profile_id = profile_id_from_text(st.query_params["student"])
    student = database.get_profile_by_id(reported_profile_id) if reported_profile_id else None
    if student is None:
        st.write("This student does not exist.")
        st.stop()
    st.write("You are reporting this student:")
    st.text(student["name"])
else:
    st.write("Open this page with the Report link on a listing or a profile.")
    st.stop()

# After a report was sent, only the thank-you message is shown.
if st.session_state.pop("report_sent", False):
    st.success("Thank you. An admin will look at your report.")
    st.stop()

with st.form("report"):
    reason = st.selectbox("Reason", reports.REASONS, index=None, placeholder="Choose a reason")
    details = st.text_area("Details (optional)", max_chars=reports.MAX_DETAILS_LENGTH)
    sent = st.form_submit_button("Send")

if sent:
    try:
        reports.create_report(
            database,
            email,
            listing_id=listing_id,
            reported_profile_id=reported_profile_id,
            reason=reason,
            details=details,
        )
    except reports.ReportError as exc:
        for message in exc.errors:
            st.error(message)
    except (reports.NotAllowed, reports.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["report_sent"] = True
        st.rerun()
