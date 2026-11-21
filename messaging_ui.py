"""Messaging presentation only: scoped styles and participant-aware bubbles.

Identity, authorization, history and offer transitions stay in the repository.
There is no checkout or database client in this module.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import contextmanager, nullcontext
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
    st.html("<style>" + CHAT_CSS + COMPACT_CHAT_CSS + "</style>")


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
def message_bubble(event: dict, conversation: dict, *, compact: bool = False, show_avatar: bool = True):
    """Render a message/card from the current authenticated participant's view."""
    own = event["sender_id"] == conversation["own_profile_id"]
    side = "own" if own else "other"
    suffix = f"{event['type']}-{event['id']}"
    row_key = f"dm-event-{side}-{suffix}"
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", row_key):
        raise ValueError("Invalid chat event reference.")
    # Layout wrappers do not alter any message or action widget keys.
    with st.container(key=f"chat-compact-{suffix}") if compact else nullcontext():
        with st.container(key=row_key):
            if not own:
                if show_avatar:
                    image = avatar_background(conversation["other_name"], conversation.get("other_photo_url"))
                    st.html(f"<style>.st-key-{row_key}::before {{ background-image: {image}; }}</style>")
                else:
                    # Keep the avatar gutter so grouped bubbles stay aligned.
                    st.html(f"<style>.st-key-{row_key}::before {{ content: none; }}</style>")
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


INBOX_CSS = """
.st-key-inbox-list {
    background: #FFFFFF;
    border-radius: 18px;
    padding: 8px 20px;
    gap: 0 !important;
}
.st-key-inbox-list [class*="st-key-inbox-row-"] { padding: 12px 0; }
.st-key-inbox-list hr { margin: 0; border-color: #ECEEF2; }
.st-key-inbox-list .inbox-heading,
.st-key-inbox-list .inbox-preview,
.st-key-inbox-list .inbox-listing {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin: 0;
    line-height: 1.5;
}
.st-key-inbox-list .inbox-summary { display: flex; align-items: center; gap: 12px; }
.st-key-inbox-list .inbox-avatar {
    width: 46px; height: 46px; flex: 0 0 46px; border-radius: 50%;
    background-size: cover; background-position: center;
}
.st-key-inbox-list .inbox-information { flex: 1; min-width: 0; }
.st-key-inbox-list .inbox-heading { color: #202433; }
.st-key-inbox-list .inbox-listing { color: #737985; font-size: 0.85rem; display: block; }
.st-key-inbox-list .inbox-preview { color: #626975; font-size: 0.85rem; margin-top: 4px; }
.st-key-inbox-list [data-testid="stColumn"] { min-width: 0; }
.st-key-inbox-list [class*="st-key-inbox-row-"] > [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap; gap: 12px;
}
.st-key-inbox-list [class*="st-key-inbox-row-"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
    flex: 1 1 0 !important; min-width: 0;
}
.st-key-inbox-list [class*="st-key-inbox-row-"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {
    flex: 0 0 112px !important; min-width: 0;
}
.st-key-inbox-list [class*="st-key-inbox-actions-"] {
    width: 100%; align-items: flex-end; gap: 4px !important;
}
.st-key-inbox-list [class*="st-key-inbox-time-"] { width: 100%; text-align: right; }
.st-key-inbox-list [class*="st-key-inbox-time-"] [data-testid="stCaptionContainer"],
.st-key-inbox-list [class*="st-key-inbox-time-"] p { width: 100%; text-align: right; white-space: nowrap; }
.st-key-inbox-list [data-testid="stCaptionContainer"] { color: #737985; font-size: 0.72rem; }
.st-key-inbox-list button[kind="secondary"] {
    background: #F0F1F4; color: #464C57; border: 1px solid #E5E7EB;
    min-height: 1.8rem; padding: 3px 10px; border-radius: 8px;
}
.st-key-inbox-list button[kind="secondary"] p { font-size: 0.78rem; }
@media (max-width: 640px) {
    .st-key-inbox-list { padding: 6px 12px; }
    .st-key-inbox-list [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: 8px; }
    .st-key-inbox-list [data-testid="stColumn"]:first-child { flex: 1 1 0 !important; }
    .st-key-inbox-list [data-testid="stColumn"]:last-child { flex: 0 0 105px !important; }
}
"""


def apply_inbox_styles() -> None:
    st.html("<style>" + INBOX_CSS + "</style>")


def inbox_activity_preview(activity: dict | None, actor: int) -> str:
    """Describe the repository-selected chronological activity, without writes."""
    if not activity:
        return "No messages yet"
    own = activity["sender_id"] == actor
    if activity.get("type") != "offer":
        return ("You: " if own else "") + activity["body"]
    from listings import format_price
    from offers import OFFER_STATUS_LABELS
    status = activity["status"]
    kind = "Counteroffer" if activity.get("parent_offer_id") else "Offer"
    # The card sender is not the responder: avoid attributing acceptance/decline
    # to the original offer sender. The authoritative status describes the event.
    prefix = "You: " if own and status not in ("accepted", "declined") else ""
    return f"{prefix}{kind}: {format_price(activity['amount_cents'])} · {OFFER_STATUS_LABELS[status]}"


def inbox_summary(row: dict, activity: dict | None) -> None:
    """Compact escaped summary with an optional real photo above initials fallback."""
    name = html.escape(row["other_name"])
    title = html.escape(row["listing_title_snapshot"])
    preview = html.escape(inbox_activity_preview(activity, row["own_profile_id"]))
    dot = "🔵 " if row.get("unread") else ""  # Preserve the existing unread indicator.
    unavailable = " · Listing no longer available" if row["listing_id"] is None else ""
    background = html.escape(avatar_background(row["other_name"], row.get("other_photo_url")), quote=True)
    st.html(
        f'<div class="inbox-summary"><span class="inbox-avatar" role="img" '
        f'aria-label="{name} profile picture" style="background-image: {background}"></span>'
        f'<div class="inbox-information"><div class="inbox-heading"><strong>{dot}{name}</strong></div>'
        f'<div class="inbox-listing">{title}{unavailable}</div>'
        f'<p class="inbox-preview" title="{preview}">{preview}</p></div></div>'
    )


LISBON = ZoneInfo("Europe/Lisbon")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def inbox_timestamp(value: str, *, now: datetime | None = None) -> str:
    """Calendar labels in Lisbon, independent of server timezone and locale.

    Database timestamps must include an offset. Never guess the zone of a
    naive timestamp, which would be ambiguous at daylight-saving boundaries.
    """
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    current = now if now is not None else datetime.now(LISBON)
    if instant.utcoffset() is None or current.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps are required.")
    local = instant.astimezone(LISBON)
    today = current.astimezone(LISBON).date()
    if local.date() == today:
        return local.strftime("%H:%M")
    if local.date() == today - timedelta(days=1):
        return "Yesterday"
    return f"{local.day:02d} {_MONTHS[local.month - 1]}"


def chat_header(row: dict, *, divider: bool = True) -> None:
    """Participant photo and immutable listing details; no new data reads."""
    from listings import format_price
    with st.container(key="chat-participant-header"):
        st.html("<style>.st-key-chat-participant-header [data-testid='stHorizontalBlock'] "
                "{flex-wrap:nowrap;gap:12px;} "
                ".st-key-chat-participant-header [data-testid='stColumn']:first-child "
                "{flex:0 0 46px!important;min-width:46px;} "
                ".st-key-chat-participant-header [data-testid='stColumn']:last-child "
                "{flex:1 1 0!important;min-width:0;} "
                # Streamlit captions compensate paragraph spacing with a negative
                # bottom margin. Reset both margins before using our compact gap.
                ".st-key-chat-participant-header [data-testid='stCaptionContainer'] "
                "{color:#737985;margin:0;} "
                ".st-key-chat-participant-header [data-testid='stCaptionContainer'] p "
                "{margin:0;line-height:1.4;} "
                ".st-key-chat-participant-header [data-testid='stVerticalBlock'] "
                "{gap:0.25rem;}</style>")
        photo, details = st.columns([1, 10], gap="small", vertical_alignment="center")
        with photo:
            background = html.escape(avatar_background(row["other_name"], row.get("other_photo_url")), quote=True)
            name = html.escape(row["other_name"], quote=True)
            st.html(f'<div role="img" aria-label="{name} profile picture" '
                    f'style="width:46px;height:46px;border-radius:50%;background-size:cover;'
                    f'background-position:center;background-image:{background}"></div>')
        with details:
            st.subheader(row["other_name"])
            st.caption(row["listing_title_snapshot"])
            st.caption(format_price(row["price_cents"]))
            if row["listing_id"] is None:
                st.caption("Listing no longer available")
    if divider:
        st.divider()


# Compact rules only match explicit layout wrappers. Button styling remains
# in the existing base stylesheet; no callbacks or state are managed here.
COMPACT_CHAT_CSS = """
[class*="st-key-chat-compact-"] { gap: 0 !important; }
[class*="st-key-chat-compact-"] [class*="st-key-dm-own-"],
[class*="st-key-chat-compact-"] [class*="st-key-dm-other-"] {
    padding: 9px 13px !important; margin-top: 0; margin-bottom: 4px;
    max-width: min(72%, 580px) !important; gap: 0.3rem !important;
}
[class*="st-key-chat-compact-offer-"] [class*="st-key-dm-own-offer-"],
[class*="st-key-chat-compact-offer-"] [class*="st-key-dm-other-offer-"] {
    width: 68% !important; max-width: 640px !important;
}
[class*="st-key-chat-compact-"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }
[class*="st-key-chat-compact-"] h3 { margin-bottom: 0.25rem !important; }
[class*="st-key-chat-compact-"] [class*="st-key-dm-original-price-"] { padding-top: 3px !important; }
[class*="st-key-chat-compact-"] [class*="st-key-dm-event-other-"]::before { bottom: 4px; }
[class*="st-key-chat-time-"] { width: 100%; text-align: right; }
[class*="st-key-chat-time-"] p { text-align: right; white-space: nowrap; }
.chat-date-separator {
    display: flex; align-items: center; gap: 12px;
    color: #737985; font-size: 0.75rem; margin: 10px 0 6px;
}
.chat-date-separator::before, .chat-date-separator::after {
    content: ""; flex: 1; height: 1px; background: #E3E5EB;
}
@media (max-width: 700px) {
    [class*="st-key-chat-compact-"] [class*="st-key-dm-own-"],
    [class*="st-key-chat-compact-"] [class*="st-key-dm-other-"] { max-width: 92% !important; }
    [class*="st-key-chat-compact-offer-"] [class*="st-key-dm-own-offer-"],
    [class*="st-key-chat-compact-offer-"] [class*="st-key-dm-other-offer-"] {
        width: 96% !important; max-width: 100% !important;
    }
    [class*="st-key-chat-compact-offer-"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    [class*="st-key-chat-compact-offer-"] [data-testid="stColumn"] { min-width: 80px; }
}
"""

_FULL_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December")


def lisbon_datetime(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps are required.")
    return instant.astimezone(LISBON)


def chat_date_label(value: str, *, now: datetime | None = None) -> str:
    day = lisbon_datetime(value).date()
    current = now if now is not None else datetime.now(LISBON)
    if current.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps are required.")
    today = current.astimezone(LISBON).date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day.day} {_FULL_MONTHS[day.month - 1]} {day.year}"


def chat_event_groups(events: list[dict], *, now: datetime | None = None):
    """Decorate the supplied ordered window; never reorder, fetch or store it."""
    current = now if now is not None else datetime.now(LISBON)
    previous_day = previous_sender = None
    for event in events:
        day = lisbon_datetime(event["created_at"]).date()
        new_day = day != previous_day
        yield event, chat_date_label(event["created_at"], now=current) if new_day else None, (
            new_day or event["sender_id"] != previous_sender)
        previous_day, previous_sender = day, event["sender_id"]


def date_separator(label: str) -> None:
    st.html(f'<div class="chat-date-separator" role="separator" aria-label="{html.escape(label, quote=True)}">'
            f'<span>{html.escape(label)}</span></div>')


def chat_timestamp(event: dict) -> None:
    with st.container(key=f"chat-time-{event['type']}-{event['id']}"):
        st.caption(lisbon_datetime(event["created_at"]).strftime("%H:%M"))


# Applied only by the open-chat fragment; no Inbox, navigation or button rules.
OPEN_CHAT_CSS = """
.st-key-open-chat-surface {
    background: #FFFFFF; border-radius: 16px; padding: 14px 18px;
    gap: 0.65rem !important; min-width: 0;
}
.st-key-open-chat-surface .st-key-chat-toolbar > [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap; align-items: center; gap: 12px;
}
.st-key-open-chat-surface .st-key-chat-toolbar > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    min-width: 0;
}
.st-key-open-chat-surface .st-key-chat-participant-header h3 {
    font-size: 1rem !important; line-height: 1.3; padding: 0; margin: 0;
}
.st-key-open-chat-surface .st-key-chat-participant-header [data-testid="stCaptionContainer"] {
    font-size: 0.78rem; line-height: 1.3; overflow-wrap: anywhere;
}
.st-key-open-chat-surface .st-key-chat-header-divider hr {
    border-color: #E5E7EB; margin: 0 0 4px;
}
.st-key-open-chat-surface [class*="st-key-chat-compact-"] [class*="st-key-dm-own-"],
.st-key-open-chat-surface [class*="st-key-chat-compact-"] [class*="st-key-dm-other-"] {
    padding: 8px 12px !important; max-width: min(66%, 460px) !important;
    border-radius: 18px !important;
}
.st-key-open-chat-surface [class*="st-key-chat-compact-offer-"] [class*="st-key-dm-own-offer-"],
.st-key-open-chat-surface [class*="st-key-chat-compact-offer-"] [class*="st-key-dm-other-offer-"] {
    width: 62% !important; max-width: 500px !important;
}
.st-key-open-chat-surface [class*="st-key-chat-compact-"] [data-testid="stText"] {
    font-size: 0.88rem; line-height: 1.4;
}
.st-key-open-chat-surface [class*="st-key-chat-compact-"] h3 {
    font-size: 1.15rem !important; line-height: 1.3;
}
.st-key-open-chat-surface [class*="st-key-chat-time-"] { text-align: right; }
@media (max-width: 700px) {
    .st-key-open-chat-surface { padding: 10px; }
    .st-key-open-chat-surface .st-key-chat-toolbar > [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap; gap: 8px;
    }
    .st-key-open-chat-surface .st-key-chat-toolbar > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) {
        flex: 1 1 45% !important;
    }
    .st-key-open-chat-surface [class*="st-key-chat-compact-"] [class*="st-key-dm-own-"],
    .st-key-open-chat-surface [class*="st-key-chat-compact-"] [class*="st-key-dm-other-"] {
        max-width: 100% !important;
    }
    .st-key-open-chat-surface [class*="st-key-chat-compact-offer-"] [class*="st-key-dm-own-offer-"],
    .st-key-open-chat-surface [class*="st-key-chat-compact-offer-"] [class*="st-key-dm-other-offer-"] {
        width: 100% !important; max-width: 100% !important;
    }
}
"""


def apply_open_chat_styles() -> None:
    st.html("<style>" + OPEN_CHAT_CSS + "</style>")
