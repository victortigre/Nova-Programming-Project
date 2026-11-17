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
        self._numbers = itertools.count(1)

    def add_profile(self, email: str) -> dict:
        profile = {"id": next(self._numbers), "email": email}
        self.profiles[email] = profile
        return profile

    # --- the same functions as database.py ------------------------------------

    def get_profile(self, email):
        return self.profiles.get(email)

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

    def feed_listings(self, limit, offset):
        shown = self._newest_first(r for r in self.listings.values() if r["status"] != "sold")
        return shown[offset:offset + limit]

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
