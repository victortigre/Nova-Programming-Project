"""Tests for the offer notifications on Browse (offers.offers_waiting_for).

Pure rules only: no database, no Streamlit. Run them with:  pytest
"""

from offers import offers_waiting_for

ME, OTHER, THIRD = 7, 8, 9


def chat(cid, buyer=ME, seller=OTHER, title="Bike"):
    return {"id": cid, "buyer_id": buyer, "seller_id": seller, "listing_title_snapshot": title}


def offer(sender, status="pending", amount=4500, parent=None, created="2026-11-21T10:00:00"):
    return {"sender_id": sender, "status": status, "amount_cents": amount,
            "parent_offer_id": parent, "created_at": created}


def waiting(chats, latest):
    return offers_waiting_for(ME, chats, lambda cid: latest.get(cid))


def test_a_counteroffer_from_the_other_side_waits_for_me():
    result = waiting([chat("a")], {"a": offer(OTHER, parent="p1")})
    assert result == [{"conversation_id": "a", "amount_cents": 4500, "counter": True,
                       "sender_id": OTHER, "listing_title": "Bike",
                       "created_at": "2026-11-21T10:00:00"}]


def test_a_first_offer_is_not_a_counteroffer():
    assert waiting([chat("a", buyer=OTHER, seller=ME)], {"a": offer(OTHER)})[0]["counter"] is False


def test_my_own_offer_does_not_notify_me():
    assert waiting([chat("a")], {"a": offer(ME, parent="p1")}) == []


def test_answered_offers_do_not_notify():
    for status in ("accepted", "declined", "superseded"):
        assert waiting([chat("a")], {"a": offer(OTHER, status=status)}) == []


def test_chats_without_offers_or_not_mine_are_skipped():
    chats = [chat("a"), chat("b", buyer=OTHER, seller=THIRD)]
    assert waiting(chats, {"b": offer(OTHER)}) == []


def test_newest_first():
    chats = [chat("a", title="Old"), chat("b", title="New")]
    latest = {"a": offer(OTHER, created="2026-11-20T10:00:00"),
              "b": offer(OTHER, created="2026-11-21T10:00:00")}
    assert [item["listing_title"] for item in waiting(chats, latest)] == ["New", "Old"]
