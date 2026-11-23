"""Browse: search the marketplace and save listings — BUYER side (area 3).

Reads the feed and saved listings through database.py; the search and sort rules
live in browsing.py. app.py already lets only verified Nova students in, and we
check again, because the rule is to check where the action happens.
"""

import html
import re
from datetime import date
from functools import partial

import streamlit as st

import browsing
import database
import deals
import listings
import messaging_repository
import messaging_ui
import offer_ui
import payments
import ui
from accounts import logged_in_user, verified_nova_email
from profiles import DONE, onboarding_step

FEED_LIMIT = 500  # the marketplace is small; fetch the newest listings and filter here

email = verified_nova_email(logged_in_user())
if email is None or not st.user.is_logged_in:
    st.error("Please sign in with your @novasbe.pt email first.")
    st.stop()

me = database.get_profile(email)
if me is None:
    st.info("Fill in your profile first. After that you can browse and save items.")
    st.page_link("views/profile.py", label="Fill in my profile")
    st.stop()
my_id = me["id"]
offer_ui.sync_account(email)
messaging_ui.apply_listing_action_styles()


@st.cache_data(ttl=300, show_spinner=False)
def free_unpaid_items() -> None:
    """Put items back on sale whose buyer did not pay in time. At most once every
    five minutes (that is what the ttl does), so Browse stays fast."""
    try:
        deals.cancel_all_overdue(database)
    except Exception:  # buying isn't set up in the database yet
        pass


free_unpaid_items()

# Saving needs the favorites table. If it isn't in the database yet, the rest of
# Browse still works and saving is quietly turned off with a clear note.
try:
    saved = browsing.saved_ids(database, my_id)
    saving_ready = True
except Exception:
    saved = set()
    saving_ready = False


def plain(text: str) -> str:
    """Show user-written text literally, so a title can't add links or formatting."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~<$:])", r"\\\1", text or "")


def status_note(status: str) -> str:
    if status == listings.RESERVED:
        return " · :orange[🔒 Reserved]"
    if status == listings.SOLD:
        return " · :red[Sold]"
    return ""


# Which listing is open is written in the address (/?listing=12), not kept in
# memory. So "Browse" or the logo in the menu (address without ?listing=) always
# shows the full list again, and the browser's Back button closes the listing.
def open_listing(listing_id: int) -> None:
    st.query_params["listing"] = str(listing_id)


def close_listing() -> None:
    st.query_params.clear()


def listing_in_address() -> int | None:
    """The listing number from the address, or None if there is none (or nonsense)."""
    text = str(st.query_params.get("listing", ""))
    # Only plain digits, and not more than the database can hold as a number.
    if not (text.isascii() and text.isdigit()) or len(text) > 15:
        return None
    return int(text)


def turn_photo(listing_id: int, step: int) -> None:
    key = f"photo-number-{listing_id}"
    st.session_state[key] = st.session_state.get(key, 0) + step


def pick_photo(listing_id: int, number: int) -> None:
    st.session_state[f"photo-number-{listing_id}"] = number


@st.fragment  # a click redraws only the photos, not the whole page
def photo_viewer(listing_id: int, urls: list[str]) -> None:
    """Show one photo large; arrows and small photos switch to the others."""
    # After the last photo comes the first one again, and the other way round.
    number = st.session_state.get(f"photo-number-{listing_id}", 0) % len(urls)
    with st.container(key="photo-frame"):
        with st.container(key="photo-big"):
            st.image(urls[number], width="stretch")
        if len(urls) > 1:
            st.button("", icon=":material/chevron_left:", key=f"photo-back-{listing_id}",
                      on_click=turn_photo, args=(listing_id, -1))
            st.button("", icon=":material/chevron_right:", key=f"photo-next-{listing_id}",
                      on_click=turn_photo, args=(listing_id, 1))
            with st.container(key="photo-count"):
                st.html(f'<span class="nm-photo-count">{number + 1} / {len(urls)}</span>')
    if len(urls) > 1:
        with st.container(horizontal=True, key="photo-thumbs"):
            for place, url in enumerate(urls):
                state = "on" if place == number else "off"
                with st.container(key=f"thumb-{state}-{place}", width=84):
                    st.image(url, width="stretch")
                    st.button(f"Photo {place + 1}", key=f"thumbpick-{listing_id}-{place}",
                              on_click=pick_photo, args=(listing_id, place))


def flip_saved(listing_id: int, tab: str = "browse") -> None:
    browsing.toggle_saved(database, my_id, listing_id)
    # The tab is called "Saved (2)". Removing a heart changes that number, and
    # Streamlit then opens the first tab again. Remember to stay on Saved.
    if tab == "saved":
        st.session_state["stay_on_saved_tab"] = True


# --- Buy Now (on the item page) ------------------------------------------------------
def buy_now(listing_id: int) -> None:
    """Buy at the listed price: open (or reuse) the chat with the seller, start
    the purchase there (deals.py checks everything again, including that the
    seller can be paid) and go to the chat, which shows how to pay."""
    try:
        with st.spinner("Reserving it for you…"):
            conversation = messaging_repository.get_or_create_conversation(listing_id)
            deals.buy_at_listed_price(database, email, conversation["id"])
    except deals.ListingError as exc:
        st.error(" ".join(exc.errors))
    except (deals.NotAllowed, deals.NotFound, ValueError) as exc:
        st.error(str(exc))
    except Exception:
        st.error("Buying isn't available right now. Please try again later.")
    else:
        if st.session_state.get("messaging_account") != email:
            st.session_state.pop("messaging_pending", None)
        st.session_state["messaging_account"] = email
        st.session_state["messaging_selected"] = conversation["id"]
        st.session_state["messaging_history_limit"] = 50
        st.session_state["payment_message"] = "Reserved for you! See below how to pay the seller."
        st.switch_page("views/messaging.py")


def save_button(listing_id: int, *, where: str) -> None:
    if not saving_ready:
        return
    is_saved = listing_id in saved
    # The heart picture is added by ui.py (keys starting with "heartlabel-on/off-").
    state = "on" if is_saved else "off"
    st.button("Saved" if is_saved else "Save", key=f"heartlabel-{state}-{where}-{listing_id}",
              help="Remove from saved" if is_saved else "Save for later",
              on_click=flip_saved, args=(listing_id,))


# --- detail view --------------------------------------------------------------
# Another page (a student's profile) can ask Browse to open one listing.
if "open_listing" in st.session_state:
    open_listing(st.session_state.pop("open_listing"))
viewing = listing_in_address()
if viewing is not None:
    item = listings.get_listing(database, viewing)
    if item is None:
        close_listing()
        st.rerun()
    offer_ui.retry_panel()
    st.button("Back to results", icon=":material/arrow_back:", type="tertiary",
              on_click=close_listing)
    with ui.card("detail"):
        photo_col, info_col = st.columns([1, 1], gap="large")
        with photo_col:
            links = database.listing_photo_urls(item["photo_paths"])
            urls = [links[path] for path in item["photo_paths"] if path in links]
            if urls:
                photo_viewer(item["id"], urls)
            else:
                st.html('<div class="nm-photo"><span class="nm-empty">🛍️</span></div>')
        with info_col:
            st.subheader(plain(item["title"]))
            st.html(f'<p class="nm-price">{listings.format_price(item["price_cents"])}</p>')
            if item["status"] != listings.ACTIVE:
                st.markdown(status_note(item["status"]).lstrip(" ·"))
            st.html(ui.chip(listings.category_label(item)) + ui.chip(item["condition"])
                    + ui.chip(listings.pickup_label(item), warm=True))
            available_note = listings.availability_text(item, date.today())
            if available_note:
                st.markdown(f"📅 **{available_note}**")
            seller = database.get_profile_by_id(item["seller_id"])
            if seller and my_id != item["seller_id"]:
                # Clicking "Sold by <name>" opens that seller's profile.
                st.page_link("views/public_profile.py",
                             label=f"Sold by **{plain(seller['name'])}**",
                             icon=":material/storefront:",
                             query_params={"id": item["seller_id"]})
            listed_note = listings.listed_text(item)
            if listed_note:
                st.caption(f"🗓️ {listed_note}")
            # st.text shows it exactly as typed: no formatting, and a web
            # address in it does not become a link.
            st.text(item["description"])
            if message := st.session_state.pop("deal_message", None):
                st.success(message)
            if error := st.session_state.pop("deal_error", None):
                st.error(error)
            if my_id != item["seller_id"]:
                accepted = payments.accepted_labels(seller)
                if item["status"] == listings.ACTIVE and item["price_cents"]:
                    st.caption("**Buy Now** at this price, or make an offer to agree a "
                               "different one in the chat. You pay the seller directly"
                               + (f": {accepted}." if accepted else "."))
                elif item["status"] == listings.ACTIVE:
                    st.caption("This item is free: contact the seller to arrange the pickup.")
                can_contact = (not me.get("blocked_at") and onboarding_step(me) == DONE
                               and seller and not seller.get("blocked_at")
                               and onboarding_step(seller) == DONE)
                with st.container(key="listing-actions"):
                    # Always shown for priced items on sale. If the seller can't be
                    # paid yet, deals.py refuses and the reason appears here.
                    if can_contact and item["status"] == listings.ACTIVE and item["price_cents"]:
                        # Buy at the listed price: open (or reuse) the chat with the
                        # seller, start the purchase there (deals.py checks everything
                        # again) and show where to pay.
                        if st.button("Buy Now", key=f"buy-now-{item['id']}", type="primary",
                                     icon=":material/shopping_bag:", width="stretch"):
                            buy_now(item["id"])
                    if can_contact:
                        offer_column, contact_column = st.columns(2)
                        # A free item has no price to negotiate.
                        if item["status"] == listings.ACTIVE and item["price_cents"]:
                            if offer_column.button("Make an Offer", key=f"offer-{item['id']}",
                                                   type="secondary", icon=":material/local_offer:", width="stretch"):
                                st.session_state.messaging_offer_browse = item["id"]
                        if contact_column.button("Contact Seller", key=f"contact-{item['id']}",
                                     type="secondary", icon=":material/chat:", width="stretch"):
                            try:
                                with st.spinner("Opening conversation…"):
                                    conversation = messaging_repository.get_or_create_conversation(item["id"])
                            except ValueError as exc:
                                st.warning(str(exc))
                            except Exception:
                                st.error("Messaging is not available right now. It may still need database setup. Please try again later.")
                            else:
                                # Establish account ownership before the Messages
                                # page runs its account-change reset. Never carry
                                # another account's pending message into this chat.
                                if st.session_state.get("messaging_account") != email:
                                    st.session_state.pop("messaging_pending", None)
                                st.session_state["messaging_account"] = email
                                st.session_state["messaging_selected"] = conversation["id"]
                                st.session_state["messaging_history_limit"] = 50
                                st.switch_page("views/messaging.py")
                    if item["status"] == listings.RESERVED:
                        # The buyer who tapped Buy Now is the one it is reserved for.
                        try:
                            mine = database.live_request(my_id, item["id"]) is not None
                        except Exception:  # buying isn't set up in the database yet
                            mine = False
                        st.caption("This item is reserved for you. See My purchases for how to pay."
                                   if mine else "This item is reserved for another buyer.")
                    if (can_contact and item["status"] == listings.ACTIVE
                            and st.session_state.get("messaging_offer_browse") == item["id"]):
                        st.caption("Send a price offer directly to the chat. A personal message is optional.")
                        offer_ui.show_form(f"browse-{item['id']}", default_cents=item["price_cents"], listing_id=item["id"])
                save_button(item["id"], where="detail")
                st.page_link("views/public_profile.py",
                             label="View the seller's profile to get in touch",
                             icon=":material/person:",
                             query_params={"id": item["seller_id"]})
                st.page_link("views/report.py", label="Report this listing",
                             icon=":material/flag:", query_params={"listing": item["id"]})
            else:
                st.caption("This is your own listing.")
    st.stop()


# --- the grid of results -----------------------------------------------------
# A saved listing shows up in both tabs, so "tab" goes into each key:
# Streamlit refuses two buttons with the same key on one page.
def listing_grid(items: list[dict], tab: str, columns: int = 3) -> None:
    # One request for all cover photo links, instead of one per card.
    links = database.listing_photo_urls(
        [item["photo_paths"][0] for item in items if item["photo_paths"]])
    for start in range(0, len(items), columns):
        row = st.columns(columns, gap="medium")
        for column, item in zip(row, items[start:start + columns]):
            cover = item["photo_paths"][0] if item["photo_paths"] else None
            with column:
                own = my_id == item["seller_id"]
                # on_open runs before the page is drawn again, so one click
                # draws the listing straight away instead of the list first.
                ui.listing_card(
                    item,
                    links.get(cover),
                    key=f"{tab}-{item['id']}",
                    saved=None if (own or not saving_ready) else item["id"] in saved,
                    on_heart=partial(flip_saved, item["id"], tab),
                    on_open=partial(open_listing, item["id"]),
                )


# --- What needs your attention ------------------------------------------------
# The same numbers as in the menu ("My listings (2)"), spelled out, with a link.
def plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


try:
    to_do = deals.to_do(database, email)
except Exception:  # buying isn't set up in the database yet
    to_do = {"answer": 0, "pay": 0, "check_payment": 0}
SALES, PURCHASES = "views/my_listings.py", "views/purchases.py"

# Offers and counteroffers waiting for an answer (Inbox). Empty if messaging
# isn't set up in the database yet.
try:
    offers_waiting = messaging_repository.offers_to_answer()
except Exception:
    offers_waiting = []

# Build every card that applies, in order. The count (or an offer's amount) is
# part of each key, so a card that was dismissed comes back when there is new
# activity (another buyer, a new offer).
notices = []
# Who exactly is waiting: one card per deal, with the other student's name.
try:
    waiting = deals.waiting_on_me(database, email)
except Exception:  # buying isn't set up in the database yet
    waiting = {"pay": [], "check_payment": []}
for deal in waiting["check_payment"]:
    name, title = html.escape(deal["buyer_name"]), html.escape(deal["title"])
    price = listings.format_price(deal["price_cents"])
    if deal["paid"]:
        notices.append(dict(
            key=f"check-payment-{deal['request_id']}-paid", emoji="💶",
            title=f"{name} says they paid you {price}",
            text=f"For {title}. Check that it arrived, then confirm on My listings.",
            page=SALES, label="Confirm", section="reserved"))
    else:
        notices.append(dict(
            key=f"check-payment-{deal['request_id']}-cash", emoji="💶",
            title=f"{name} will pay you {price} in cash",
            text=f"For {title}. Agree where to meet in the chat, and confirm on My listings "
                 "once you have the money.",
            page=SALES, label="Open", section="reserved"))
if to_do.get("answer"):
    notices.append(dict(
        key=f"answer-{to_do['answer']}", emoji="🛍️",
        title=f"{plural(to_do['answer'], 'old request', 'old requests')} to buy your items",
        text="Buying now works through the chat. Decline these on My listings.",
        page=SALES, label="Open"))
for item in offers_waiting:
    kind = "a counteroffer" if item["counter"] else "an offer"
    notices.append(dict(
        key=f"offer-{item['conversation_id']}-{item['amount_cents']}", emoji="💬",
        title=f"{html.escape(item['sender_name'])} sent you {kind}: "
              f"{listings.format_price(item['amount_cents'])}",
        text=f"For {html.escape(item['listing_title'])}. "
             "Accept, decline or counter in your Inbox.",
        page="views/messaging.py", label="See offer", open_chat=item["conversation_id"]))
for deal in waiting["pay"]:
    name, title = html.escape(deal["seller_name"]), html.escape(deal["title"])
    price = listings.format_price(deal["price_cents"])
    notices.append(dict(
        key=f"pay-{deal['request_id']}-{'cash' if deal['cash'] else 'bank'}", emoji="🏦",
        title=(f"Meet {name} and pay {price} in cash" if deal["cash"]
               else f"Pay {name} {price}"),
        text=(f"For {title}. Agree the time and place in the chat." if deal["cash"]
              else f"For {title}. Pay within 15 minutes (bank transfer), or choose cash "
                   "in person, then confirm."),
        page=PURCHASES, label="Pay", tone="green"))

# Dismissals last for this session only; the task itself is unchanged.
dismissed = st.session_state.setdefault("dismissed_notices", set())
visible = [card for card in notices if card["key"] not in dismissed]


def dismiss_notice(key: str) -> None:
    st.session_state["dismissed_notices"].add(key)


def show_notice(card: dict) -> None:
    ui.notice(card["key"], card["emoji"], card["title"], card["text"], card["page"],
              card["label"], tone=card.get("tone", "violet"),
              open_chat=card.get("open_chat"), on_dismiss=dismiss_notice,
              section=card.get("section"))


# Show the first two; keep the rest behind an "expand" toggle, so a long list
# doesn't take over the whole page.
NOTICES_SHOWN = 2
for card in visible[:NOTICES_SHOWN]:
    show_notice(card)
if len(visible) > NOTICES_SHOWN:
    with st.expander(f"Show {len(visible) - NOTICES_SHOWN} more notification(s)"):
        for card in visible[NOTICES_SHOWN:]:
            show_notice(card)


# --- Browse and Saved tabs ----------------------------------------------------
# In a keyed container, so ui.py can put the heart picture in front of "Saved".
with st.container(key="browse-tabs"):
    saved_label = f"Saved ({len(saved)})"
    # After removing a heart on the Saved tab, open that tab again (see flip_saved).
    stay_on_saved = st.session_state.pop("stay_on_saved_tab", False)
    browse_tab, saved_tab = st.tabs(["All items", saved_label],
                                    default=saved_label if stay_on_saved else None)

with browse_tab:
    query = st.text_input("Search", placeholder="Search desks, books, bikes...",
                          icon=":material/search:", label_visibility="collapsed")
    category = st.pills("Category", ["All"] + listings.CATEGORIES, default="All",
                        label_visibility="collapsed") or "All"
    feed = listings.feed_listings(database, limit=FEED_LIMIT)
    filters_col, grid_col = st.columns([1, 3], gap="medium")

    with filters_col:
        # Always €0 to the highest price a listing may have, so the range is the
        # same for everyone, whatever is on sale right now.
        max_euros = listings.MAX_PRICE_CENTS // 100
        # Two boxes to type a price (Min, Max) and a slider under them. Choosing a
        # range (typing it or moving the slider) zooms the slider into it: choose 10
        # and 30, and the slider goes from €10 at the left end to €30 at the right
        # end, to fine-tune inside it. "Any price" goes back to every price.
        # Without a typed range it covers every price, with bigger steps as prices
        # grow, so €0-€100 (most items) uses most of its length.
        wide_steps = sorted({0, 5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200,
                             250, 300, 400, 500, 750, 1000, 1500, 2000, 3000, max_euros})

        def slider_steps(bottom: int, top: int) -> list[int]:
            """The prices the slider can stop at, from `bottom` to `top`."""
            if top - bottom <= 60:
                return list(range(bottom, top + 1))
            if top - bottom <= 300:
                return sorted(set(range(bottom, top + 1, 5)) | {top})
            return [bottom] + [step for step in wide_steps if bottom < step < top] + [top]

        prices = st.session_state
        prices.setdefault("price-min", 0)
        prices.setdefault("price-max", max_euros)
        prices.setdefault("price-scale", (0, max_euros))  # the slider's two ends
        # A new slider (new key) each time the ends change: that is how Streamlit
        # lets one widget follow another.
        prices.setdefault("price-version", 0)
        slider_key = f"price-slider-{prices['price-version']}"

        def prices_typed() -> None:
            if prices["price-min"] > prices["price-max"]:  # typed the wrong way round
                prices["price-min"], prices["price-max"] = prices["price-max"], prices["price-min"]
            prices["price-scale"] = (prices["price-min"], prices["price-max"])
            prices["price-version"] += 1

        def prices_slid() -> None:
            # The chosen range becomes the slider's new ends too.
            prices["price-min"], prices["price-max"] = prices[slider_key]
            prices["price-scale"] = prices[slider_key]
            prices["price-version"] += 1

        def any_price() -> None:
            prices["price-min"], prices["price-max"] = 0, max_euros
            prices["price-scale"] = (0, max_euros)
            prices["price-version"] += 1

        bottom, top = prices["price-scale"]
        options = slider_steps(bottom, top)

        def on_slider(euros: int) -> int:
            return min(options, key=lambda option: abs(option - euros))

        with ui.card("price-range"):
            heading, reset = st.columns(2, vertical_alignment="center")
            heading.markdown("**Price**")
            if (bottom, top) != (0, max_euros):
                reset.button("Any price", key="price-reset", type="tertiary",
                             on_click=any_price)
            min_col, max_col = st.columns(2, gap="small")
            min_col.number_input("Min (€)", min_value=0, max_value=max_euros, step=5,
                                 key="price-min", on_change=prices_typed)
            max_col.number_input("Max (€)", min_value=0, max_value=max_euros, step=5,
                                 key="price-max", on_change=prices_typed)
            if len(options) > 1:
                # Shows the price on each handle while you move it.
                st.select_slider("Price (€)", options=options, key=slider_key,
                                 value=(on_slider(prices["price-min"]),
                                        on_slider(prices["price-max"])),
                                 format_func=lambda euros: f"€{euros}",
                                 on_change=prices_slid, label_visibility="collapsed")
        # The boxes hold the exact prices.
        low, high = prices["price-min"], prices["price-max"]
        with ui.card("sort"):
            st.markdown("**Sort by**")
            sort_label = st.radio("Sort by", list(browsing.SORTS),
                                  label_visibility="collapsed")
        # One tick box per line, like "Sort by". Several can be ticked; none = all.
        with ui.card("location"):
            st.markdown("**Location**")
            pickup_areas = [area for area in listings.PICKUP_AREAS
                            if st.checkbox(area, key=f"location-{area}")]
        with ui.card("condition"):
            st.markdown("**Condition**")
            conditions = [condition for condition in listings.CONDITIONS
                          if st.checkbox(condition, key=f"condition-{condition}")]

    results = browsing.search_and_sort(
        feed, query=query, category=category,
        min_cents=low * 100, max_cents=high * 100,
        conditions=conditions, pickup_areas=pickup_areas,
        sort=browsing.SORTS[sort_label],
    )
    with grid_col:
        st.caption(f"{len(results)} listing(s)")
        if not results:
            st.info("No listings match your filters. Try clearing the search, "
                    "category, price range, location or condition.")
        listing_grid(results, tab="browse")

with saved_tab:
    if not saving_ready:
        st.info("Saving isn't set up in the database yet. Whoever manages the database "
                "needs to run `database_setup.sql` (it adds the favorites table).")
    else:
        saved_items = browsing.saved_listings(database, my_id)
        if not saved_items:
            with st.container(border=True):
                ui.hint_with_heart("You haven't saved anything yet. "
                                   "Tap {heart} on a listing to keep it here.")
        listing_grid(saved_items, tab="saved", columns=4)
