"""The payment box of a deal, shown in the chat, on My purchases and on My listings.
The rules are in deals.py and payments.py; this file only shows them.

    buyer_box(deal, email, where)   how to pay, "I've paid", or the status
    seller_box(deal, email, where)  "Payment received" / "Not received yet", or the status
    show_message()                  the green note after a button press

`where` keeps the button keys apart when a page shows the same deal twice.
"""

import streamlit as st

import database
import deals
import listings
import payments


def _do(action, request_id: int, email: str, done: str, *extra) -> None:
    """Run a deals.py action, show its error, or reload the page with `done`."""
    try:
        action(database, request_id, email, *extra)
    except deals.ListingError as exc:
        st.error(" ".join(exc.errors))
    except (deals.NotAllowed, deals.NotFound) as exc:
        st.error(str(exc))
    else:
        st.session_state["payment_message"] = done
        st.rerun()


def show_message() -> None:
    if message := st.session_state.pop("payment_message", None):
        st.success(message)


def _price(deal: dict) -> str:
    return listings.format_price(deals.price_of(deal, deal.get("listing")))


def _label(method: str | None) -> str:
    return payments.METHOD_LABELS.get(method or "", "another way")


def _bank_details(method: dict) -> None:
    """The seller's account holder and IBAN, ready to copy."""
    with st.container(border=True):
        for caption, value in method["details"]:
            st.caption(caption)
            st.code(value, language=None)


def _choice_label(key: str) -> str:
    return {payments.BANK: "Bank transfer (within 15 minutes)",
            payments.CASH: "Cash in person (when you meet)"}.get(key, _label(key))


def buyer_box(deal: dict, email: str, where: str) -> None:
    rid = deal["id"]
    status = deal["status"]
    if status == deals.COMPLETED:
        st.success("Payment confirmed by the seller. The item is yours!",
                   icon=":material/check_circle:")
        return
    if status == deals.CANCELLED:
        st.caption("This purchase was cancelled.")
        return
    if status != deals.ACCEPTED:
        return
    if deal.get("paid_at"):
        st.info(f"You said you paid **{_price(deal)}** with "
                f"**{_label(deal.get('payment_method'))}**. Waiting for the seller to confirm "
                "it arrived.", icon=":material/hourglass_top:")
        return
    try:
        details = deals.payment_details(database, rid, email)
    except (deals.NotAllowed, deals.NotFound):
        return
    if deals.paying_cash(deal):
        st.info(f"You'll pay **{_price(deal)} in cash** when you meet. Agree the time and "
                "place in the chat. The seller confirms when they get the money.",
                icon=":material/payments:")
        if st.button("Cancel purchase", key=f"{where}-cancel-{rid}"):
            _do(deals.cancel_deal, rid, email, "Purchase cancelled. The item is back on sale.")
        return
    methods = {m["key"]: m for m in details["methods"]}
    missing = bool(deal.get("payment_missing_at"))
    # First choose how to pay (when the seller accepts both): a bank transfer has
    # 15 minutes, cash is paid in person when you meet, with no deadline.
    if missing or payments.CASH not in methods:
        choice = payments.BANK
    elif payments.BANK not in methods:
        choice = payments.CASH
    else:
        choice = st.radio("How do you want to pay?", [payments.BANK, payments.CASH],
                          format_func=_choice_label, horizontal=True,
                          key=f"{where}-choice-{rid}")
    if choice == payments.BANK and payments.BANK in methods:
        if missing:
            st.warning("The seller says the payment **hasn't arrived**. Check your transfer "
                       "and talk to them in the chat. When it's sorted, tap “I've paid” again.",
                       icon=":material/error:")
        else:
            due = deals.pay_by_text(deal)
            st.warning(f"Pay **{_price(deal)}** by bank transfer"
                       + (f" by **{due}**. If you don't, the purchase is cancelled "
                          "automatically." if due else ", then tap “I've paid”."),
                       icon=":material/schedule:")
        _bank_details(methods[payments.BANK])
        columns = st.columns(2)
        if columns[0].button("I've paid", key=f"{where}-paid-{rid}", type="primary",
                             icon=":material/check:"):
            _do(deals.mark_paid, rid, email,
                "Thanks! The seller will check and confirm.", payments.BANK)
    else:
        st.info(f"Pay **{_price(deal)} in cash** when you meet to pick it up. There's no "
                "deadline: agree the time and place in the chat. Tap the button below to "
                "choose cash, so the 15 minutes for bank transfers don't apply.",
                icon=":material/payments:")
        columns = st.columns(2)
        if columns[0].button("Pay in cash when we meet", key=f"{where}-cash-{rid}",
                             type="primary", icon=":material/check:"):
            _do(deals.choose_cash, rid, email,
                "Cash it is. Agree in the chat where and when to meet.")
    if not missing and columns[1].button("Cancel purchase", key=f"{where}-cancel-{rid}"):
        _do(deals.cancel_deal, rid, email, "Purchase cancelled. The item is back on sale.")


def seller_box(deal: dict, email: str, where: str, buyer_name: str = "The buyer") -> None:
    rid = deal["id"]
    status = deal["status"]
    buyer_name = listings.plain_text(buyer_name)
    if status == deals.COMPLETED:
        st.success("Payment received. Sold!", icon=":material/check_circle:")
        return
    if status == deals.CANCELLED:
        st.caption("This sale was cancelled.")
        return
    if status != deals.ACCEPTED:
        return
    if deal.get("paid_at"):
        method = _label(deal.get("payment_method"))
        st.warning(f"**{buyer_name} says they paid {_price(deal)} with {method}.** Check that "
                   "it arrived and confirm.",
                   icon=":material/account_balance:")
        columns = st.columns(2)
        if columns[0].button("Payment received", key=f"{where}-received-{rid}",
                             type="primary", icon=":material/check:"):
            _do(deals.confirm_payment, rid, email, "Payment confirmed. The item is marked sold.")
        if columns[1].button("Not received yet", key=f"{where}-missing-{rid}"):
            _do(deals.payment_not_received, rid, email,
                "The buyer is asked to check their payment.")
        return
    if deals.paying_cash(deal):
        st.info(f"{buyer_name} will pay **{_price(deal)} in cash** when you meet. Agree the "
                "time and place in the chat, and confirm once you have the money.",
                icon=":material/payments:")
        columns = st.columns(2)
        if columns[0].button("Cash received", key=f"{where}-received-{rid}",
                             type="primary", icon=":material/check:"):
            _do(deals.confirm_payment, rid, email, "Payment confirmed. The item is marked sold.")
        if columns[1].button("Cancel sale", key=f"{where}-cancel-{rid}"):
            _do(deals.cancel_deal, rid, email, "Sale cancelled. The item is back on sale.")
        return
    if deal.get("payment_missing_at"):
        st.info(f"You said the payment hasn't arrived. Waiting for {buyer_name} to check and "
                "pay again. You can talk in the chat, or cancel the sale.",
                icon=":material/hourglass_top:")
    else:
        due = deals.pay_by_text(deal)
        st.info(f"Waiting for {buyer_name} to pay **{_price(deal)}**"
                + (f" by **{due}**. If they don't, the sale is cancelled automatically."
                   if due else "."), icon=":material/hourglass_top:")
    if st.button("Cancel sale", key=f"{where}-cancel-{rid}"):
        _do(deals.cancel_deal, rid, email, "Sale cancelled. The item is back on sale.")
