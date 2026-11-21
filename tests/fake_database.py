"""A pretend database for the tests. It lives in memory and needs no internet.

It has the same listing functions as database.py, so listings.py can't tell
the difference. Like the real one, update and delete only touch a listing
when the seller number matches.
"""

import itertools


class FakeDatabase:
    def __init__(self):
        self.profiles = {}  # email -> profile
        self.listings = {}  # id -> listing
        self.photos = {}  # stored name -> picture bytes
        self.favorites = []  # (profile_id, listing_id), in the order they were saved
        self.reports = {}  # id -> report
        self.requests = {}  # id -> purchase request
        self.wallet = []  # wallet lines, oldest first
        self.reviews = []  # every review, in the order they were left
        self._numbers = itertools.count(1)

    def add_profile(self, email: str, name: str = "Test Student") -> dict:
        profile = {"id": next(self._numbers), "email": email, "name": name, "blocked_at": None}
        self.profiles[email] = profile
        return profile

    def add_listing(self, seller_id: int, title: str = "Desk lamp") -> dict:
        """Put a listing straight in, without the checks of listings.py."""
        return self.insert_listing({"seller_id": seller_id, "title": title, "photo_paths": []})

    # --- the same functions as database.py ------------------------------------

    def get_profile(self, email):
        return self.profiles.get(email)

    def get_profile_by_id(self, profile_id):
        for profile in self.profiles.values():
            if profile["id"] == profile_id:
                return dict(profile)
        return None

    def insert_listing(self, row):
        listing = {**row, "id": next(self._numbers), "status": "active"}
        listing["created_at"] = listing["id"]  # a higher number means newer
        self.listings[listing["id"]] = listing
        return dict(listing)

    def get_listing(self, listing_id):
        listing = self.listings.get(listing_id)
        return dict(listing) if listing else None

    def _newest_first(self, rows):
        return [dict(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]

    def listings_of_seller(self, seller_id):
        return self._newest_first(r for r in self.listings.values() if r["seller_id"] == seller_id)

    def _seller_is_blocked(self, listing):
        seller = self.get_profile_by_id(listing["seller_id"])
        return seller is not None and seller["blocked_at"] is not None

    def feed_listings(self, limit, offset):
        shown = self._newest_first(r for r in self.listings.values()
                                   if r["status"] != "sold" and not self._seller_is_blocked(r))
        return shown[offset:offset + limit]

    def get_active_listings(self, profile_id):
        return self._newest_first(r for r in self.listings.values()
                                  if r["seller_id"] == profile_id and r["status"] == "active"
                                  and not self._seller_is_blocked(r))

    def update_listing(self, listing_id, seller_id, changes, only_if_status=None):
        listing = self.listings.get(listing_id)
        if not listing or listing["seller_id"] != seller_id:
            return False
        if only_if_status is not None and listing["status"] != only_if_status:
            return False
        listing.update(changes)
        return True

    def delete_listing(self, listing_id, seller_id):
        listing = self.listings.get(listing_id)
        if listing and listing["seller_id"] == seller_id:
            del self.listings[listing_id]
            self._requests_go_with(listing_id)

    def _requests_go_with(self, listing_id):
        """Like "on delete cascade": a deleted listing's requests go too."""
        self.requests = {i: r for i, r in self.requests.items() if r["listing_id"] != listing_id}

    def upload_listing_photo(self, picture):
        path = f"photo-{next(self._numbers)}"
        self.photos[path] = picture
        return path

    def delete_listing_photos(self, paths):
        for path in paths:
            self.photos.pop(path, None)

    # --- favourites (same functions as database.py) ---------------------------

    def add_favorite(self, profile_id, listing_id):
        if (profile_id, listing_id) not in self.favorites:
            self.favorites.append((profile_id, listing_id))

    def remove_favorite(self, profile_id, listing_id):
        self.favorites = [pair for pair in self.favorites if pair != (profile_id, listing_id)]

    def favorite_ids(self, profile_id):
        return [lid for (pid, lid) in reversed(self.favorites) if pid == profile_id]

    def favorite_listings(self, profile_id):
        return [dict(self.listings[lid]) for lid in self.favorite_ids(profile_id)
                if lid in self.listings]
    def insert_report(self, row):
        report = {**row, "id": next(self._numbers), "status": "open", "handled_at": None}
        report["created_at"] = report["id"]  # a higher number means newer
        self.reports[report["id"]] = report
        return dict(report)

    def open_report(self, reporter_id, listing_id, reported_profile_id):
        for report in self.reports.values():
            if (report["reporter_id"] == reporter_id and report["status"] == "open"
                    and report["listing_id"] == listing_id
                    and report["reported_profile_id"] == reported_profile_id):
                return dict(report)
        return None

    # --- admin ----------------------------------------------------------------

    def get_report(self, report_id):
        report = self.reports.get(report_id)
        return dict(report) if report else None

    def open_reports(self):
        rows = [r for r in self.reports.values() if r["status"] == "open"]
        return [dict(r) for r in sorted(rows, key=lambda r: r["created_at"])]

    def close_reports(self, report_ids, status):
        for report_id in report_ids:
            report = self.reports.get(report_id)
            if report and report["status"] == "open":
                report["status"] = status
                report["handled_at"] = "now"

    def block_profile(self, profile_id):
        for profile in self.profiles.values():
            if profile["id"] == profile_id:
                profile["blocked_at"] = "now"

    def admin_delete_listing(self, listing_id):
        self.listings.pop(listing_id, None)
        # Like "on delete cascade" in the real database: its reports go too.
        self.reports = {i: r for i, r in self.reports.items() if r["listing_id"] != listing_id}
        self._requests_go_with(listing_id)

    # --- buying (purchase requests) -------------------------------------------

    def insert_request(self, row):
        request = {**row, "id": next(self._numbers),
                   "status": row.get("status", "requested"),
                   "seller_confirmed_at": None, "buyer_confirmed_at": None,
                   "returned_at": None, "given_back_at": None, "return_disputed_at": None,
                   "refund_reason": None, "refund_details": None}
        request["created_at"] = request["id"]  # a higher number means newer
        self.requests[request["id"]] = request
        return dict(request)

    def get_request(self, request_id):
        request = self.requests.get(request_id)
        return dict(request) if request else None

    def live_request(self, buyer_id, listing_id):
        for request in self.requests.values():
            if (request["buyer_id"] == buyer_id and request["listing_id"] == listing_id
                    and request["status"] in ("requested", "accepted")):
                return dict(request)
        return None

    def requests_for_listing(self, listing_id, statuses):
        rows = [r for r in self.requests.values()
                if r["listing_id"] == listing_id and r["status"] in statuses]
        return [dict(r) for r in sorted(rows, key=lambda r: r["created_at"])]

    def requests_by_buyer(self, buyer_id, statuses):
        rows = [r for r in self.requests.values()
                if r["buyer_id"] == buyer_id and r["status"] in statuses]
        return [dict(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]

    def update_request(self, request_id, changes, only_if_status=None):
        request = self.requests.get(request_id)
        if not request:
            return False
        if only_if_status is not None and request["status"] != only_if_status:
            return False
        request.update(changes)
        return True

    def requests_for_seller(self, seller_id, statuses):
        rows = []
        for r in sorted(self.requests.values(), key=lambda r: r["created_at"]):
            listing = self.listings.get(r["listing_id"])
            if listing and listing["seller_id"] == seller_id and r["status"] in statuses:
                # Like the real query: the listing comes along as row["listings"].
                rows.append({**r, "listings": {"seller_id": seller_id,
                                               "title": listing.get("title"),
                                               "price_cents": listing.get("price_cents", 0)}})
        return rows

    def disputed_returns(self):
        rows = []
        for r in sorted(self.requests.values(), key=lambda r: r["created_at"]):
            listing = self.listings.get(r["listing_id"])
            if r["status"] == "accepted" and r.get("return_disputed_at") and listing:
                rows.append({**r, "listings": {"seller_id": listing["seller_id"],
                                               "title": listing.get("title"),
                                               "price_cents": listing.get("price_cents", 0)}})
        return rows

    def live_deals_of(self, profile_id):
        live = ["requested", "accepted"]
        return {"selling": self.requests_for_seller(profile_id, live),
                "buying": self.requests_by_buyer(profile_id, live)}

    def names_of(self, profile_ids):
        return {p["id"]: p["name"] for p in self.profiles.values() if p["id"] in set(profile_ids)}

    # --- reviews ----------------------------------------------------------------

    def insert_review(self, row):
        # Like the unique index in the real database: one review per person per deal.
        for review in self.reviews:
            if (review["request_id"], review["reviewer_id"]) == (row["request_id"], row["reviewer_id"]):
                raise ValueError("duplicate review")
        stars = row.get("stars")
        if stars is not None and not 1 <= stars <= 5:  # like the check in the database
            raise ValueError("stars must be 1 to 5")
        review = {"stars": None, "comment": None, **row, "id": next(self._numbers)}
        self.reviews.append(review)
        return dict(review)

    def reviews_about(self, profile_id):
        return [dict(r) for r in self.reviews if r["reviewee_id"] == profile_id]

    def reviews_by(self, reviewer_id):
        return [dict(r) for r in self.reviews if r["reviewer_id"] == reviewer_id]


    # --- wallet (same rules as the two database functions) -------------------

    def wallet_entries_of(self, profile_id):
        rows = [dict(e) for e in self.wallet if e["profile_id"] == profile_id]
        return list(reversed(rows))  # newest first

    def wallet_add_entry(self, row):
        entry = {**row, "id": next(self._numbers)}
        self.wallet.append(entry)
        return dict(entry)

    def _wallet_line(self, request_id, kind):
        return next((e for e in self.wallet
                     if e["request_id"] == request_id and e["kind"] == kind), None)

    def wallet_hold(self, profile_id, request_id, amount_cents, note):
        if self._wallet_line(request_id, "hold"):
            return True
        available = sum(e["amount_cents"] for e in self.wallet if e["profile_id"] == profile_id)
        if available < amount_cents:
            return False
        self.wallet_add_entry({"profile_id": profile_id, "amount_cents": -amount_cents,
                               "kind": "hold", "request_id": request_id, "note": note})
        return True

    def wallet_settle(self, request_id, kind, profile_id):
        assert kind in ("release", "refund")
        held = self._wallet_line(request_id, "hold")
        if held is None:
            return False
        if self._wallet_line(request_id, "release") or self._wallet_line(request_id, "refund"):
            return False
        self.wallet_add_entry({"profile_id": profile_id, "amount_cents": -held["amount_cents"],
                               "kind": kind, "request_id": request_id, "note": held["note"]})
        return True
