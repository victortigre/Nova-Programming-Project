"""Login check for the pages in pages/.

Each page in pages/ runs as its own script, so the checks in app.py don't
protect it. Every page that needs a logged-in student calls
require_nova_student() at the top. It uses the same rules as app.py
(accounts.nova_email and accounts.email_is_verified).
"""

import streamlit as st

from accounts import email_is_verified, nova_email


def require_nova_student() -> dict:
    """Return {'email', 'name'} of the verified Nova student, or stop the page."""
    if not st.user.is_logged_in:
        st.info("Sign in with your @novasbe.pt email first.")
        st.page_link("app.py", label="Go to sign in", icon="🔑")
        st.stop()

    user_info = st.user.to_dict()
    email = nova_email(user_info)
    if email is None:
        st.error("Only @novasbe.pt email addresses can use Nova Marketplace.")
        st.stop()
    if not email_is_verified(user_info):
        st.info(f"Confirm your email first: click the link we sent to {email}, "
                "then sign out and sign in again.")
        st.page_link("app.py", label="Back to the start page", icon="🔑")
        st.stop()

    name = (user_info.get("name") or "").strip()
    if not name or "@" in name:  # Auth0 sometimes uses the email as the name
        name = email.split("@")[0]
    return {"email": email, "name": name}
