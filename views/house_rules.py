"""House rules: what students may and may not do on Nova Marketplace."""

import streamlit as st

from accounts import logged_in_user, verified_nova_email
from house_rules_text import show_house_rules

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("House rules")
show_house_rules()
