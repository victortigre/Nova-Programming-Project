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

-- One row per item a student is selling. seller_id points to the student who
-- posted it. "status" is 'available' until the item is sold.
create table if not exists listings (
    id          bigint generated always as identity primary key,
    seller_id   bigint not null references profiles(id) on delete cascade,
    title       text not null,
    description text not null default '',
    price       numeric not null default 0 check (price >= 0),
    category    text not null default 'Other',
    status      text not null default 'available' check (status in ('available', 'sold')),
    created_at  timestamptz not null default now()
);

alter table listings enable row level security;

-- One row each time a student saves a listing (their wishlist). The pair is
-- unique, so saving the same listing twice keeps a single row.
create table if not exists favorites (
    id         bigint generated always as identity primary key,
    profile_id bigint not null references profiles(id) on delete cascade,
    listing_id bigint not null references listings(id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (profile_id, listing_id)
);

alter table favorites enable row level security;
