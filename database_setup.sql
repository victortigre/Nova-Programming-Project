-- Nova Marketplace: database setup.
--
-- Run this once in Supabase: SQL Editor -> New query -> paste everything -> Run.
-- It is safe to run it again; nothing that already exists is changed.
-- When a new table is needed, add it here so the whole team has the same setup.

-- One row per student. The email comes from the login and never changes;
-- other tables should point to a student with profiles.id.
create table if not exists profiles (
    id                bigint generated always as identity primary key,
    email             text not null unique,
    name              text not null,
    program           text not null,
    leaving_lisbon_on date,
    photo_path        text,
    created_at        timestamptz not null default now()
);

-- Lock the table. With this switched on and no extra rules added, only our
-- app (which holds the secret key) can read or change the rows.
alter table profiles enable row level security;

-- A private folder for profile photos. "false" means a photo cannot be
-- opened by its address alone; the app has to make a temporary link.
insert into storage.buckets (id, name, public)
values ('profile-photos', 'profile-photos', false)
on conflict (id) do nothing;

-- One row per item a student offers. The seller is a profile; if a profile
-- is deleted, its listings go with it.
create table if not exists listings (
    id           bigint generated always as identity primary key,
    seller_id    bigint not null references profiles(id) on delete cascade,
    title        text not null,
    description  text not null,
    price_cents  integer not null check (price_cents >= 0),  -- 0 means free
    category     text not null,
    condition    text not null,
    pickup_area  text not null,
    status       text not null default 'active'
                 check (status in ('active', 'reserved', 'sold')),
    photo_paths  text[] not null default '{}',  -- the first photo is the cover
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

-- Added later: the text a seller types after choosing "Other" as category or
-- pickup area (empty otherwise). Safe to run again.
alter table listings add column if not exists category_other text;
alter table listings add column if not exists pickup_area_other text;

-- Added later: until when the seller can hand the item over. After this date
-- the listing is hidden from Browse (the seller still sees it). Safe to run again.
alter table listings add column if not exists available_until date;

-- Condition names were renamed ("New" -> "Brand New", "Like new" -> "Like New").
update listings set condition = 'Brand New' where condition = 'New';
update listings set condition = 'Like New' where condition = 'Like new';

create index if not exists listings_seller_idx on listings (seller_id);
create index if not exists listings_feed_idx on listings (status, created_at desc);

-- Locked the same way as profiles: only our app can read or change rows.
alter table listings enable row level security;

-- A private folder for listing photos, like the one for profile photos.
insert into storage.buckets (id, name, public)
values ('listing-photos', 'listing-photos', false)
on conflict (id) do nothing;

-- One row each time a buyer saves a listing (their wishlist). The pair is
-- unique, so saving the same listing twice keeps a single row. If either the
-- buyer's profile or the listing is deleted, the saved row goes with it.
create table if not exists favorites (
    id         bigint generated always as identity primary key,
    profile_id bigint not null references profiles(id) on delete cascade,
    listing_id bigint not null references listings(id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (profile_id, listing_id)
);

create index if not exists favorites_profile_idx on favorites (profile_id);

-- Locked the same way as the other tables: only our app can read or change rows.
alter table favorites enable row level security;
-- One row per report a student sends about a listing or about another
-- student. A report points to exactly one of the two. If that listing or
-- student is deleted, the report goes with it: a report about nothing
-- would break the "exactly one" rule below.
create table if not exists reports (
    id                  bigint generated always as identity primary key,
    reporter_id         bigint not null references profiles(id) on delete cascade,
    listing_id          bigint references listings(id) on delete cascade,
    reported_profile_id bigint references profiles(id) on delete cascade,
    reason              text not null
                        check (reason in ('Forbidden item', 'Scam or fake listing',
                                          'Offensive content', 'Harassment', 'Other')),
    details             text check (char_length(details) <= 500),
    status              text not null default 'open'
                        check (status in ('open', 'removed', 'blocked', 'dismissed')),
    created_at          timestamptz not null default now(),
    handled_at          timestamptz,
    -- Exactly one target: a listing OR a student, never both and never none.
    check ((listing_id is null) <> (reported_profile_id is null))
);

-- For the admin list: only the open reports, oldest first.
create index if not exists reports_open_idx on reports (created_at) where status = 'open';
-- For the check "has this student already reported this?".
create index if not exists reports_reporter_idx on reports (reporter_id, status);

-- Locked the same way as the other tables: only our app can read or change rows.
alter table reports enable row level security;

-- The database itself refuses a second open report by the same student about
-- the same thing, even if "Send" is clicked twice very fast.
create unique index if not exists reports_one_open_per_listing
    on reports (reporter_id, listing_id) where status = 'open' and listing_id is not null;
create unique index if not exists reports_one_open_per_student
    on reports (reporter_id, reported_profile_id) where status = 'open' and reported_profile_id is not null;

-- When an admin blocks a student, the time is stored here. Empty (null)
-- means the student is not blocked. A blocked student cannot use the app,
-- and their listings are no longer shown to others.
alter table profiles add column if not exists blocked_at timestamptz;

-- When a student agreed to the house rules during sign-up, the time is
-- stored here. Empty (null) means they have not agreed yet; app.py then
-- shows only the Welcome steps until they do.
alter table profiles add column if not exists rules_accepted_at timestamptz;

-- One row per request a buyer sends to buy a listing. The seller accepts one,
-- which reserves the item; then BOTH sides confirm the hand-over before it
-- counts as sold (seller_confirmed_at AND buyer_confirmed_at).
create table if not exists purchase_requests (
    id                  bigint generated always as identity primary key,
    listing_id          bigint not null references listings(id) on delete cascade,
    buyer_id            bigint not null references profiles(id) on delete cascade,
    status              text not null default 'requested'
                        check (status in ('requested', 'accepted', 'declined',
                                          'cancelled', 'completed')),
    seller_confirmed_at timestamptz,
    buyer_confirmed_at  timestamptz,
    created_at          timestamptz not null default now()
);

create index if not exists purchase_requests_listing_idx on purchase_requests (listing_id, status);
create index if not exists purchase_requests_buyer_idx on purchase_requests (buyer_id, status);

-- The database itself refuses a second live (requested or accepted) request by
-- the same buyer on the same listing, even on a double-click.
create unique index if not exists purchase_requests_one_live
    on purchase_requests (buyer_id, listing_id)
    where status in ('requested', 'accepted');

-- Locked the same way as the other tables: only our app can read or change rows.
alter table purchase_requests enable row level security;

-- Only ONE accepted buyer per listing, refused by the database itself, even if
-- the seller accepts two buyers in two browser tabs at the same moment.
create unique index if not exists purchase_requests_one_accepted
    on purchase_requests (listing_id) where status = 'accepted';

-- One row per rating after a completed deal: the buyer rates the seller and
-- the seller rates the buyer, once each, with a thumbs up (positive = true)
-- or a thumbs down. If the listing (and with it the deal) is deleted later,
-- the rating stays, so a seller can't erase a bad rating by deleting the item.
create table if not exists reviews (
    id          bigint generated always as identity primary key,
    request_id  bigint references purchase_requests(id) on delete set null,
    reviewer_id bigint not null references profiles(id) on delete cascade,
    reviewee_id bigint not null references profiles(id) on delete cascade,
    positive    boolean not null,
    created_at  timestamptz not null default now(),
    check (reviewer_id <> reviewee_id)
);

-- One rating per person per deal, even on a double-click.
create unique index if not exists reviews_one_per_deal on reviews (request_id, reviewer_id);
create index if not exists reviews_reviewee_idx on reviews (reviewee_id);

-- Locked the same way as the other tables: only our app can read or change rows.
alter table reviews enable row level security;
