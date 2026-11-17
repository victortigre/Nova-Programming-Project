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

create index if not exists listings_seller_idx on listings (seller_id);
create index if not exists listings_feed_idx on listings (status, created_at desc);

-- Locked the same way as profiles: only our app can read or change rows.
alter table listings enable row level security;

-- A private folder for listing photos, like the one for profile photos.
insert into storage.buckets (id, name, public)
values ('listing-photos', 'listing-photos', false)
on conflict (id) do nothing;

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
