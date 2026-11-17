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
