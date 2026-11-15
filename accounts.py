"""Accounts: who is allowed into Nova Marketplace.

The login itself is done by Auth0, a login service. People sign up there
with an email and a password, and Auth0 sends them a link to confirm the
email address. We never see or store a password.

After a login, Auth0 tells the app who the person is. This file decides
whether that person may come in.
"""

ALLOWED_DOMAIN = "@novasbe.pt"


def nova_email(user_info: dict) -> str | None:
    """Return the person's Nova email, or None if it is not a Nova address.

    `user_info` is what Auth0 sent us after the login.
    """
    email = (user_info.get("email") or "").strip().lower()

    if email.count("@") != 1:
        return None
    if not email.endswith(ALLOWED_DOMAIN) or email == ALLOWED_DOMAIN:
        return None
    return email


def email_is_verified(user_info: dict) -> bool:
    """True only if the person clicked the link Auth0 emailed to them.

    Without this check anybody could type in someone else's Nova address.
    Clicking the link proves they can read that mailbox.
    """
    return user_info.get("email_verified") is True


def verified_nova_email(user_info: dict) -> str | None:
    """Return the email of a person who may use the app, or None.

    This puts the two checks above together: a Nova address AND a confirmed
    email. Every page calls this before it shows or changes anything.
    """
    email = nova_email(user_info)
    if email is None or not email_is_verified(user_info):
        return None
    return email
