"""Messaging presentation only: scoped styles and participant-aware bubbles.

Identity, authorization, history and offer transitions stay in the repository.
There is no checkout or database client in this module.
"""

from contextlib import contextmanager
import html
import re
from urllib.parse import quote, urlsplit

import streamlit as st

CHAT_CSS = """
[class*="st-key-dm-own-"], [class*="st-key-dm-other-"] {
    box-sizing: border-box;
    gap: 0.4rem !important;
    width: fit-content !important;
    max-width: 78% !important;
    min-width: 0;
    padding: 14px 18px !important;
    border-radius: 22px !important;
    margin-top: 3px;
    margin-bottom: 9px;
    overflow-wrap: anywhere;
    box-shadow: 0 2px 5px rgba(35, 28, 72, 0.04);
}
[class*="st-key-dm-own-"] {
    margin-left: auto !important;
    margin-right: 0 !important;
    background: linear-gradient(135deg, #5F47F5 0%, #4359D9 100%);
    color: #FFFFFF;
    border-bottom-right-radius: 7px !important;
}
[class*="st-key-dm-other-"] {
    margin-left: 0 !important;
    margin-right: auto !important;
    background: #ECEEF3;
    color: #202433;
    border-bottom-left-radius: 7px !important;
}
[class*="st-key-dm-own-offer-"], [class*="st-key-dm-other-offer-"] {
    width: 78% !important;
}
[class*="st-key-dm-own-"] [data-testid="stVerticalBlock"],
[class*="st-key-dm-other-"] [data-testid="stVerticalBlock"] { gap: 0.4rem; }
[class*="st-key-dm-own-"] [data-testid="stText"],
[class*="st-key-dm-own-"] [data-testid="stText"] *,
[class*="st-key-dm-own-"] h3 { color: #FFFFFF !important; }
[class*="st-key-dm-other-"] [data-testid="stText"],
[class*="st-key-dm-other-"] [data-testid="stText"] *,
[class*="st-key-dm-other-"] h3 { color: #202433 !important; }
[class*="st-key-dm-own-"] [data-testid="stCaptionContainer"] *,
[class*="st-key-dm-own-"] [data-testid="stCaption"] * { color: #F0EDFF !important; }
[class*="st-key-dm-other-"] [data-testid="stCaptionContainer"] *,
[class*="st-key-dm-other-"] [data-testid="stCaption"] * { color: #545C6D !important; }
[class*="st-key-dm-"] [data-testid="stCaptionContainer"] { opacity: 1 !important; }
[class*="st-key-dm-"] h3 { margin: 0.15rem 0 0.55rem !important; padding: 0 !important; line-height: 1.3; }
[class*="st-key-dm-"] [data-testid="stCaptionContainer"] p { font-size: 0.75rem; line-height: 1.4; }
[class*="st-key-dm-"] [data-testid="stText"] { white-space: pre-wrap; line-height: 1.5; }
[class*="st-key-dm-"] button[kind="secondary"] {
    background: #FFFFFF !important;
    color: #4534AD !important;
    border: 1px solid #9386CC !important;
}
[class*="st-key-dm-"] button[kind="secondary"] * { color: #4534AD !important; }
[class*="st-key-dm-"] button[kind="secondary"]:hover { background: #F4F1FF !important; }
[class*="st-key-dm-"] button[kind="primary"] {
    background: #5F47F5 !important;
    color: #FFFFFF !important;
    border: 1px solid #D6CFFF !important;
}
[class*="st-key-dm-"] button[kind="primary"] * { color: #FFFFFF !important; }
[class*="st-key-dm-"] button:disabled { opacity: 1 !important; cursor: not-allowed; }
[class*="st-key-dm-"] button:focus-visible { outline: 3px solid #A898FF; outline-offset: 2px; }
[class*="st-key-dm-original-price-"] { padding-top: 8px !important; }
[class*="st-key-dm-event-"] { gap: 4px !important; }
/* Received bubbles stay light grey. Only their internal sender name is blue. */
[class*="st-key-dm-event-other-"] {
    position: relative;
    padding-left: 48px !important;
}
[class*="st-key-dm-event-other-"]::before {
    content: "";
    position: absolute;
    bottom: 9px;
    left: 0;
    width: 36px;
    height: 36px;
    border: 2px solid #FFFFFF;
    border-radius: 50%;
    background-size: cover;
    background-position: center;
    box-shadow: 0 1px 4px rgba(30, 35, 55, 0.12);
}
[class*="st-key-dm-sender-name-"] [data-testid="stText"],
[class*="st-key-dm-sender-name-"] [data-testid="stText"] * {
    color: #245BB0 !important;
    font-size: 0.8rem !important;
    font-weight: 600;
}
@media (max-width: 600px) {
    [class*="st-key-dm-own-"], [class*="st-key-dm-other-"] {
        max-width: 80% !important;
        padding: 12px 14px !important;
    }
    [class*="st-key-dm-own-offer-"], [class*="st-key-dm-other-offer-"] { width: 80% !important; }
}"""

LISTING_ACTION_CSS = """

.st-key-listing-actions button { min-height: 3rem; border-radius: 14px; }
.st-key-listing-actions [class*="st-key-offer-"] button {
    background: #ECEEF3;
    color: #202433;
    border: 1px solid #DDE0E7;
}
.st-key-listing-actions [class*="st-key-offer-"] button p { color: #202433; }
.st-key-listing-actions [class*="st-key-offer-"] button:hover {
    background: #E0E3EB;
    border-color: #9C96B2;
}
.st-key-listing-actions [class*="st-key-contact-"] button {
    background: #FFFFFF;
    color: #202433;
    border: 1px solid #C9CDD7;
}
.st-key-listing-actions [class*="st-key-contact-"] button p { color: #202433; }
.st-key-listing-actions [class*="st-key-contact-"] button:hover {
    background: #F5F4FA;
    border-color: #8E83BB;
}
.st-key-listing-actions [class*="st-key-buy-"] button {
    background: #5F47F5;
    color: #FFFFFF;
    border: 1px solid #5F47F5;
}
.st-key-listing-actions [class*="st-key-buy-"] button p { color: #FFFFFF; }
.st-key-listing-actions [class*="st-key-buy-"] button:hover { background: #5039DD; }
"""

def apply_chat_styles() -> None:
    st.html("<style>" + CHAT_CSS + "</style>")


def apply_listing_action_styles() -> None:
    st.html("<style>" + LISTING_ACTION_CSS + "</style>")


def avatar_background(name: str, photo_url: str | None) -> str:
    """A real photo above an initials image: failed images reveal the fallback.

    CSS background layers provide a browser-side fallback without JavaScript,
    fetching private images in Python, or making chat depend on image loading.
    """
    initials = "".join(part[0] for part in name.split()[:2]).upper() or "?"
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80">'
           '<rect width="80" height="80" rx="40" fill="#E3E7F1"/>'
           '<text x="40" y="43" text-anchor="middle" dominant-baseline="middle" '
           'font-family="sans-serif" font-size="27" font-weight="600" fill="#4C5568">'
           + html.escape(initials) + '</text></svg>')
    layers = ['url("data:image/svg+xml,' + quote(svg, safe="") + '")']
    if isinstance(photo_url, str):
        try:
            parsed = urlsplit(photo_url)
            valid = parsed.scheme in ("https", "http") and bool(parsed.netloc) and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if valid:
            # Preserve signed URL punctuation, encode stylesheet/HTML delimiters.
            safe_url = quote(photo_url, safe=":/?&=%@+;,~!$*.-_#")
            layers.insert(0, 'url("' + safe_url + '")')
    return ", ".join(layers)


@contextmanager
def message_bubble(event: dict, conversation: dict):
    """Render a message/card from the current authenticated participant's view."""
    own = event["sender_id"] == conversation["own_profile_id"]
    side = "own" if own else "other"
    suffix = f"{event['type']}-{event['id']}"
    row_key = f"dm-event-{side}-{suffix}"
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", row_key):
        raise ValueError("Invalid chat event reference.")
    with st.container(key=row_key):
        if not own:
            image = avatar_background(conversation["other_name"], conversation.get("other_photo_url"))
            st.html(f"<style>.st-key-{row_key}::before {{ background-image: {image}; }}</style>")
        with st.container(key=f"dm-{side}-{suffix}"):
            if not own:
                with st.container(key=f"dm-sender-name-{suffix}"):
                    st.text(conversation["other_name"])
            yield own


def accepted_offer_description(offer: dict, conversation: dict) -> str:
    buyer_view = conversation["own_profile_id"] == conversation["buyer_id"]
    buyer_proposal = offer["sender_id"] == conversation["buyer_id"]
    if buyer_view:
        return ("The seller has accepted your offer." if buyer_proposal
                else "You have accepted the seller's counteroffer.")
    return ("You have accepted the buyer's offer." if buyer_proposal
            else "The buyer has accepted your offer.")
