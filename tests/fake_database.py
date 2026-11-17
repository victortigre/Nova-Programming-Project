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
        self.reports = {}  # id -> report
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

    def update_listing(self, listing_id, seller_id, changes):
        listing = self.listings.get(listing_id)
        if listing and listing["seller_id"] == seller_id:
            listing.update(changes)

    def delete_listing(self, listing_id, seller_id):
        listing = self.listings.get(listing_id)
        if listing and listing["seller_id"] == seller_id:
            del self.listings[listing_id]

    def upload_listing_photo(self, picture):
        path = f"photo-{next(self._numbers)}"
        self.photos[path] = picture
        return path

    def delete_listing_photos(self, paths):
        for path in paths:
            self.photos.pop(path, None)

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
