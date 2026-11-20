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

-- When the buyer gave the item back after the hand-over (empty = not returned).
-- The seller then has 48 hours to confirm before the buyer is refunded.
alter table purchase_requests add column if not exists returned_at timestamptz;

-- Nova credits (pretend money, see wallet.py). One row per change, like a
-- bank statement: + for added credits, a sale or a refund, - for money held
-- when a seller accepts a request. A student's balance is the sum of their rows.
-- If a deal is deleted later, its rows stay (request_id becomes empty), so the
-- history and the balance never change by themselves.
create table if not exists wallet_entries (
    id           bigint generated always as identity primary key,
    profile_id   bigint not null references profiles(id) on delete cascade,
    amount_cents integer not null,
    kind         text not null check (kind in ('top_up', 'hold', 'release', 'refund')),
    request_id   bigint references purchase_requests(id) on delete set null,
    note         text,  -- the item's title, for the history
    created_at   timestamptz not null default now()
);
create index if not exists wallet_entries_profile_idx on wallet_entries (profile_id, created_at desc);

-- Each deal can be held once, and released or refunded once, never both:
-- the database refuses a second row of the same kind for the same deal.
create unique index if not exists wallet_entries_once_per_deal
    on wallet_entries (request_id, kind) where request_id is not null;

-- Locked the same way as the other tables: only our app can read or change rows.
alter table wallet_entries enable row level security;

-- Hold the price from the buyer, ONLY if their balance is enough, in one step.
-- The lock makes two holds for the same student wait for each other, so the
-- same credits can never be spent twice. Returns true when the money is held.
create or replace function wallet_hold(p_profile bigint, p_request bigint,
                                       p_amount integer, p_note text)
returns boolean language plpgsql as $$
declare available integer;
begin
    perform pg_advisory_xact_lock(1, p_profile::integer);
    if exists (select 1 from wallet_entries
               where request_id = p_request and kind = 'hold') then
        return true;  -- already held (a double click)
    end if;
    select coalesce(sum(amount_cents), 0) into available
        from wallet_entries where profile_id = p_profile;
    if available < p_amount then
        return false;
    end if;
    insert into wallet_entries (profile_id, amount_cents, kind, request_id, note)
        values (p_profile, -p_amount, 'hold', p_request, p_note);
    return true;
end;
$$;

-- Move a deal's held money to the seller ('release') or back to the buyer
-- ('refund'), only if it is still held: never both, never twice.
create or replace function wallet_settle(p_request bigint, p_kind text, p_profile bigint)
returns boolean language plpgsql as $$
declare held integer;
declare held_note text;
begin
    if p_kind not in ('release', 'refund') then
        raise exception 'unknown kind %', p_kind;
    end if;
    perform pg_advisory_xact_lock(2, p_request::integer);
    select -amount_cents, note into held, held_note from wallet_entries
        where request_id = p_request and kind = 'hold';
    if not found then
        return false;  -- nothing was held (a free item)
    end if;
    if exists (select 1 from wallet_entries where request_id = p_request
               and kind in ('release', 'refund')) then
        return false;  -- already settled
    end if;
    insert into wallet_entries (profile_id, amount_cents, kind, request_id, note)
        values (p_profile, held, p_kind, p_request, held_note);
    return true;
end;
$$;

-- Only our app (with the secret key) may run these two, not visitors.
revoke execute on function wallet_hold(bigint, bigint, integer, text) from public, anon, authenticated;
revoke execute on function wallet_settle(bigint, text, bigint) from public, anon, authenticated;
