"""House rules: what students may and may not do on Nova Marketplace."""

import streamlit as st

from accounts import logged_in_user, verified_nova_email

# Who is using this page? The email always comes from the login, never from a form.
email = verified_nova_email(logged_in_user())
if email is None:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

st.header("House rules")
st.write("Nova Marketplace works because we trust each other. Please keep to these rules.")

st.subheader("Who can use it")
st.markdown("- Only Nova SBE students with a verified **@novasbe.pt** email.")

st.subheader("Listing an item")
st.markdown(
    """
- Describe the item honestly, including any damage or missing parts.
- Use real photos of the actual item you are selling, not pictures from the internet.
"""
)

st.subheader("Items you may not sell or give away")
st.markdown(
    """
- Weapons
- Drugs
- Alcohol
- Tobacco and vapes
- Counterfeit (fake) goods
- Stolen items
- Prescription medicine
- Academic work: exam answers, essays or assignments
"""
)

st.subheader("Meeting and messaging")
st.markdown(
    """
- Meet on campus or in a busy public place.
- Be respectful in messages. No insults, threats or spam.
"""
)

st.subheader("Reporting a problem")
st.markdown(
    """
- See a listing or a student that breaks these rules? Use the **Report** button
  on the student's public profile or next to their listings.
- Admins may remove listings and block accounts that break the rules.
"""
)
