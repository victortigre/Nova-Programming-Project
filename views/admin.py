"""Admin: handle the reports students sent, oldest first.

This page is only listed in app.py for admins. Even so, every button calls
a function in admin.py, which checks again that you are an admin before
changing anything.
"""

import streamlit as st

import admin
import database
from accounts import admin_emails, is_admin, logged_in_user, verified_nova_email

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

if not is_admin(email, admin_emails()):
    st.error("Only admins can open this page.")
    st.stop()

st.header("Admin: open reports")

# A message from the last button press survives the page reload.
if "admin_message" in st.session_state:
    st.success(st.session_state.pop("admin_message"))


def run(action, report_id: int, done_message: str) -> None:
    """Call an admin.py function, show any error, reload the page on success."""
    try:
        action(database, email, report_id)
    except (admin.NotAllowed, admin.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["admin_message"] = done_message
        st.rerun()


def report_box(report: dict) -> None:
    rid = report["id"]
    with st.container(border=True):
        # st.text shows what students typed exactly as typed, without formatting.
        st.caption(f"Reported {report['kind']}")
        st.text(report["what"])
        st.write(f"**Reason:** {report['reason']}")
        if report["details"]:
            st.caption("Details")
            st.text(report["details"])
        st.caption("Reported by")
        st.text(report["reporter"])
        st.caption(f"Sent on {str(report['created_at'])[:16].replace('T', ' ')}")

        buttons = st.columns(3)
        if report["kind"] == "listing":
            with buttons[0].popover("Remove listing"):
                st.write("Delete this listing and its photos for good?")
                if st.button("Yes, remove", key=f"remove-{rid}", type="primary"):
                    run(admin.remove_listing, rid, "Listing removed.")
        with buttons[1].popover("Block user"):
            st.write("Block this student? They can no longer use the app, "
                     "and their listings are hidden.")
            if st.button("Yes, block", key=f"block-{rid}", type="primary"):
                run(admin.block_user, rid, "Student blocked. Their open reports are closed.")
        if buttons[2].button("Dismiss", key=f"dismiss-{rid}"):
            run(admin.dismiss_report, rid, "Report dismissed.")


open_reports = admin.open_reports(database, email)
if not open_reports:
    st.info("No open reports.")
for report in open_reports:
    report_box(report)
