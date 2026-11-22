"""The payment box of a deal (bank transfer), shown in the chat, on My purchases
and on My listings. The rules are in deals.py; this file only shows them.

    buyer_box(deal, email, where)   where to pay, "I've paid", or the status
    seller_box(deal, email, where)  "Payment received" / "Not received yet", or the status
    show_message()                  the green note after a button press

`where` keeps the button keys apart when a page shows the same deal twice.
"""

import streamlit as st

import database
import deals
import listings


def _do(action, request_id: int, email: str, done: str) -> None:
    """Run a deals.py action, show its error, or reload the page with `done`."""
    try:
        action(database, request_id, email)
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


def _bank_details(deal: dict, email: str) -> None:
    """The seller's account, the amount and the reference, ready to copy."""
    try:
        details = deals.payment_details(database, deal["id"], email)
    except (deals.NotAllowed, deals.NotFound):
        return
    with st.container(border=True):
        st.markdown("**Pay by bank transfer to**")
        st.caption("Account holder")
        st.text(details["holder"] or "-")
        st.caption("IBAN (tap the icon to copy)")
        st.code(details["iban"] or "-", language=None)
        st.caption("Amount")
        st.text(listings.format_price(details["amount_cents"]))
        st.caption("Reference (write it in the transfer)")
        st.code(details["reference"], language=None)


def buyer_box(deal: dict, email: str, where: str) -> None:
    rid = deal["id"]
    status = deal["status"]
    if status == deals.COMPLETED:
        st.success("Payment confirmed by the seller. The item is yours!", icon=":material/check_circle:")
        return
    if status == deals.CANCELLED:
        st.caption("This purchase was cancelled.")
        return
    if status != deals.ACCEPTED:
        return
    if deal.get("paid_at"):
        st.info(f"You said you paid **{_price(deal)}**. Waiting for the seller to confirm "
                "the money arrived.", icon=":material/hourglass_top:")
        return
    if deal.get("payment_missing_at"):
        st.warning("The seller says the payment **hasn't arrived**. Check with your bank and "
                   "talk to them in the chat. When it's sorted, tap “I've paid” again.",
                   icon=":material/error:")
    else:
        due = deals.pay_by_text(deal)
        st.warning(f"Pay **{_price(deal)}** by bank transfer"
                   + (f" by **{due}**. If you don't, the purchase is cancelled automatically."
                      if due else ", then tap “I've paid”."), icon=":material/schedule:")
    _bank_details(deal, email)
    columns = st.columns(2)
    if columns[0].button("I've paid", key=f"{where}-paid-{rid}", type="primary",
                         icon=":material/check:"):
        _do(deals.mark_paid, rid, email, "Thanks! The seller will check their bank and confirm.")
    if not deal.get("payment_missing_at") and columns[1].button(
            "Cancel purchase", key=f"{where}-cancel-{rid}"):
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
    reference = f"Nova Marketplace #{rid}"
    if deal.get("paid_at"):
        st.warning(f"**{buyer_name} says they paid {_price(deal)}.** Check your bank account "
                   f"(reference “{reference}”) and confirm.", icon=":material/account_balance:")
        columns = st.columns(2)
        if columns[0].button("Payment received", key=f"{where}-received-{rid}",
                             type="primary", icon=":material/check:"):
            _do(deals.confirm_payment, rid, email, "Payment confirmed. The item is marked sold.")
        if columns[1].button("Not received yet", key=f"{where}-missing-{rid}"):
            _do(deals.payment_not_received, rid, email,
                "The buyer is asked to check their payment.")
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
