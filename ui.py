"""The look of Nova Marketplace: shared design pieces every page can use.

Colours, font and rounded corners are set in .streamlit/config.toml. This
file adds what the theme alone cannot do:

    apply_style()   extra CSS (white cards, round heart and price buttons)
    card(key)       a white box with round corners, for grouping things
    listing_card()  one item in a grid: photo, badge, title, heart, price
    price_chart()   the small price curve above the price slider

Safety: everything a student typed (titles, names, places) goes through
html.escape before it is put into HTML, so it shows as plain text and can
never add links, images or scripts.
"""

import html

import altair as alt
import pandas as pd
import streamlit as st

import listings

VIOLET = "#5F47F5"
YELLOW = "#F6DF62"
GREY_TEXT = "#8A8AA0"

# How each part looks. "st-key-<name>" is the class Streamlit gives an
# element or container created with key="<name>"; we use the start of the
# key ("card-", "heart-", "price-") to style every one of them.
CSS = f"""
<style>
/* Less empty space between the menu bar and the page. */
[data-testid="stMainBlockContainer"] {{ padding-top: 4.5rem; }}

/* The selected category pill is filled violet. */
button[data-variant="pills"][data-selected="true"],
button[data-variant="pills"][data-selected="true"] p {{
    background: {VIOLET} !important; border-color: {VIOLET} !important; color: #FFFFFF !important;
}}

/* White boxes with round corners on the grey page. */
[class*="st-key-card-"] {{
    background: #FFFFFF;
    border-radius: 22px;
    padding: 16px 16px 18px;
    box-shadow: 0 1px 3px rgba(27, 27, 41, 0.06);
    position: relative;
}}

/* The violet banner on the landing page. */
.st-key-hero {{
    background: linear-gradient(135deg, #7B5CFF 0%, {VIOLET} 55%, #4B32D9 100%);
    border-radius: 28px;
    padding: 40px 36px;
}}
.st-key-hero h1, .st-key-hero p {{ color: #FFFFFF; }}
.st-key-hero button {{
    background: #FFFFFF; color: {VIOLET}; border: none; font-weight: 600;
    padding: 0.6rem 1.6rem;
}}
.st-key-hero button p {{ color: {VIOLET}; font-weight: 600; }}
.st-key-hero button:hover {{ background: #F1EEFF; color: {VIOLET}; }}
.nm-price {{ color: {VIOLET}; font-size: 2rem; font-weight: 700; margin: 0; }}

/* A listing: photo with a badge, then the title. */
.nm-photo {{
    position: relative; height: 210px; border-radius: 16px; overflow: visible;
    background: #F1F2F6; display: flex; align-items: center; justify-content: center;
}}
.nm-photo img {{ width: 100%; height: 100%; object-fit: cover; border-radius: 16px; }}
.nm-photo .nm-empty {{ font-size: 3rem; opacity: 0.5; }}
.nm-badge {{
    position: absolute; left: 50%; bottom: -12px; transform: translateX(-50%);
    padding: 2px 12px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
    white-space: nowrap; background: {YELLOW}; color: #1B1B29;
}}
.nm-badge.free {{ background: {VIOLET}; color: #FFFFFF; }}
.nm-badge.sold {{ background: #1B1B29; color: #FFFFFF; }}
.nm-title {{
    margin-top: 20px; text-align: center; font-weight: 600; font-size: 1.02rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.nm-meta {{
    text-align: center; color: {GREY_TEXT}; font-size: 0.8rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}

/* The round heart button in the top right corner of a listing photo. */
[class*="st-key-heart-"] {{
    position: absolute; top: 26px; right: 26px; z-index: 3; width: auto !important;
}}
[class*="st-key-heart-"] button {{
    width: 40px; height: 40px; min-height: 0; padding: 0; border: none;
    background: #FFFFFF; color: {VIOLET};
    box-shadow: 0 2px 8px rgba(27, 27, 41, 0.15);
}}
[class*="st-key-heart-"] button p {{ font-size: 1.35rem; line-height: 1; }}

/* The price under a listing: an outlined violet pill that opens it. */
[class*="st-key-price-"] button {{
    background: #FFFFFF; color: {VIOLET}; border: 1.5px solid {VIOLET};
    font-weight: 600; padding: 0.25rem 1.1rem; min-height: 0;
}}
[class*="st-key-price-"] button:hover {{ background: {VIOLET}; color: #FFFFFF; }}

/* "✓ Verified Nova student" and similar small labels. */
.nm-chip {{
    display: inline-block; padding: 3px 12px; border-radius: 999px;
    background: #EEEBFF; color: {VIOLET}; font-size: 0.8rem; font-weight: 600;
    margin: 2px 6px 2px 0;
}}
.nm-chip.warm {{ background: #FFF6CC; color: #6B5500; }}
.nm-avatar {{
    width: 120px; height: 120px; border-radius: 50%; object-fit: cover;
    background: #EEEBFF; display: flex; align-items: center; justify-content: center;
    font-size: 2.6rem; font-weight: 600; color: {VIOLET};
}}
.nm-muted {{ color: {GREY_TEXT}; font-size: 0.85rem; }}
</style>
"""


def apply_style() -> None:
    """Add the extra CSS to the page. app.py calls this once on every visit."""
    st.html(CSS)


def card(key: str):
    """A white box with round corners. Use it with `with ui.card("name"):`."""
    return st.container(key=f"card-{key}")


def _badge(item: dict) -> str:
    """The small label on a photo: Free, Reserved or Sold (or nothing)."""
    if item.get("status") == listings.SOLD:
        return '<span class="nm-badge sold">Sold</span>'
    if item.get("status") == listings.RESERVED:
        return '<span class="nm-badge">Reserved</span>'
    if item.get("price_cents") == 0:
        return '<span class="nm-badge free">Free</span>'
    return ""


def listing_card(item: dict, photo_url: str | None, *, key: str,
                 saved: bool | None = None, on_heart=None) -> bool:
    """Show one listing as a card. Returns True when its price button is clicked.

    `key` must be different for every card on the page. Leave `saved` as
    None to show no heart (for example on your own listing). Otherwise
    `on_heart` is called when the heart is clicked.
    """
    with card(key):
        if photo_url:
            picture = f'<img src="{html.escape(photo_url)}" alt="">'
        else:
            picture = '<span class="nm-empty">🛍️</span>'
        place = listings.pickup_label(item) if item.get("pickup_area") else ""
        condition = item.get("condition", "")
        details = " · ".join(part for part in
                             [listings.category_label(item), condition, place] if part)
        st.html(
            f'<div class="nm-photo">{picture}{_badge(item)}</div>'
            f'<div class="nm-title" title="{html.escape(item["title"])}">{html.escape(item["title"])}</div>'
            f'<div class="nm-meta">{html.escape(details)}</div>'
        )
        if saved is not None:
            st.button("♥" if saved else "♡", key=f"heart-{key}", on_click=on_heart,
                      help="Remove from saved" if saved else "Save for later")
        with st.container(horizontal_alignment="center"):
            return st.button(listings.format_price(item["price_cents"]), key=f"price-{key}",
                             icon=":material/shopping_basket:", help="Open this listing")


def chip(text: str, warm: bool = False) -> str:
    """HTML for a small rounded label. `text` is escaped, so any text is safe."""
    return f'<span class="nm-chip{" warm" if warm else ""}">{html.escape(text)}</span>'


def avatar(photo_url: str | None, name: str) -> str:
    """HTML for a round profile photo, or the first letter of the name."""
    if photo_url:
        return f'<img class="nm-avatar" src="{html.escape(photo_url)}" alt="">'
    return f'<div class="nm-avatar">{html.escape((name or "?")[0].upper())}</div>'


def price_chart(prices_in_euros: list[float]) -> None:
    """A small violet curve showing how many listings there are at each price."""
    if len(prices_in_euros) < 2:
        return
    data = pd.DataFrame({"price": prices_in_euros})
    chart = (
        alt.Chart(data)
        .mark_area(color=VIOLET, opacity=0.35, interpolate="monotone",
                   line={"color": VIOLET})
        .encode(x=alt.X("price:Q", bin=alt.Bin(maxbins=12), axis=None),
                y=alt.Y("count():Q", axis=None))
        .properties(height=70, background="transparent")
        .configure_view(strokeWidth=0, fill=None)
    )
    st.altair_chart(chart, use_container_width=True)
