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

-- Added later: 1 to 5 stars and an optional written feedback. Older ratings
-- (thumbs up / down) become 5 or 1 stars. Safe to run again.
alter table reviews add column if not exists stars smallint check (stars between 1 and 5);
alter table reviews add column if not exists comment text check (char_length(comment) <= 500);
update reviews set stars = case when positive then 5 else 1 end where stars is null;
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


begin;

-- Messaging ------------------------------------------------------------------
-- Canonical Messaging SQL lives here, following AGENTS.md. No separate SQL file
-- is required. Run against DEVELOPMENT first; this section adds no checkout.
-- Both tables, indexes and owned triggers/functions can be set up again without
-- changing existing messages or snapshots. Earlier schemas fail closed below.
--
-- Only the trusted server uses these tables. Auth0 identity is verified by
-- messaging_repository; the secret client bypasses RLS. Never expose its key.
-- Listing deletion clears only the live FK and preserves chat history. Original
-- listing ID, title, integer price_cents and participants are immutable snapshots.
-- Profile deletion is restricted while conversations/messages reference it.

-- Fail before creating anything if the existing app roles cannot support the
-- invoker triggers. Do not grant privileges on teammates' tables here.
-- FOR SHARE requires UPDATE privilege on at least one listing column; the
-- existing seller/purchase backend normally already has table UPDATE access.
do $$
begin
    if not pg_catalog.has_table_privilege('service_role', 'public.profiles', 'SELECT')
       or not pg_catalog.has_table_privilege('service_role', 'public.listings', 'SELECT')
       or not pg_catalog.has_any_column_privilege('service_role', 'public.listings', 'UPDATE') then
        raise exception 'Messaging requires existing service_role profile/listing read and listing row-lock privileges. Ask the database owner to review the base setup.';
    end if;
end;
$$;

-- CREATE TABLE IF NOT EXISTS cannot upgrade old schemas. Fail closed rather
-- than silently keeping decimal-euro or demo-reference columns. If an earlier
-- draft was applied, preserve its data and prepare a reviewed upgrade first.
do $$
begin
    if pg_catalog.to_regclass('public.conversations') is not null then
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'conversations'
              and column_name = 'price_cents' and data_type = 'integer'
              and is_nullable = 'NO'
        ) or exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'conversations'
              and column_name in ('listing_price_snapshot', 'demo_listing_ref')
        ) then
            raise exception 'An earlier Messaging schema exists. Preserve its data and ask the database owner for a reviewed upgrade to integer price_cents before rerunning setup.';
        end if;
    end if;
end;
$$;

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    buyer_id bigint not null references public.profiles(id) on delete restrict,
    seller_id bigint not null references public.profiles(id) on delete restrict,
    listing_id bigint references public.listings(id) on delete set null,
    original_listing_id bigint not null check (original_listing_id > 0),
    listing_title_snapshot text not null,
    price_cents integer not null,  -- immutable listing price at first contact
    created_at timestamptz not null default now(),
    constraint conversations_different_participants check (buyer_id <> seller_id),
    constraint conversations_listing_identity check (
        listing_id is null or listing_id = original_listing_id
    ),
    constraint conversations_title_valid check (
        char_length(listing_title_snapshot) between 1 and 200
        and listing_title_snapshot ~ '[^[:space:]]'
    ),
    constraint conversations_price_valid check (
        price_cents >= 0
    ),
    constraint conversations_one_buyer_per_listing
        unique (original_listing_id, buyer_id)
);

create table if not exists public.messages (
    id bigint generated always as identity primary key,
    conversation_id uuid not null references public.conversations(id) on delete restrict,
    sender_id bigint not null references public.profiles(id) on delete restrict,
    client_message_id uuid not null,
    body text not null,
    created_at timestamptz not null default now(),
    constraint messages_body_valid check (
        char_length(body) between 1 and 2000 and body ~ '[^[:space:]]'
    ),
    constraint messages_retry_unique unique (conversation_id, client_message_id)
);

create index if not exists conversations_live_listing_idx on public.conversations (listing_id) where listing_id is not null;
create index if not exists conversations_buyer_idx on public.conversations (buyer_id);
create index if not exists conversations_seller_idx on public.conversations (seller_id);
create index if not exists messages_history_idx
    on public.messages (conversation_id, created_at desc, id desc);
create index if not exists messages_sender_idx on public.messages (sender_id);

-- Foreign keys establish profile existence. This trigger additionally ensures
-- a message's sender is a participant. It does not prove who is logged in.
create or replace function public.messaging_validate_sender()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if not exists (
        select 1 from public.conversations as c
        join public.profiles as sender on sender.id = new.sender_id
        where c.id = new.conversation_id
          and new.sender_id in (c.buyer_id, c.seller_id)
          and sender.blocked_at is null
          and sender.rules_accepted_at is not null
    ) then
        raise exception 'Conversation unavailable.' using errcode = '23514';
    end if;
    return new;
end;
$$;

drop trigger if exists messages_validate_sender on public.messages;
create trigger messages_validate_sender
before insert or update on public.messages
for each row execute function public.messaging_validate_sender();

-- Capture identity and snapshots in the same transaction as creation. A SHARE
-- lock prevents deletion/ownership/price changes until this transaction commits.
-- If deletion wins the race, SELECT finds no listing and creation is rejected.
create or replace function public.messaging_capture_listing()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    item public.listings%rowtype;
begin
    select * into item from public.listings where id = new.listing_id for share;
    if not found or item.status not in ('active', 'reserved') then
        raise exception 'Listing no longer available.' using errcode = '23514';
    end if;
    if not exists (
        select 1 from public.profiles
        where id = item.seller_id and blocked_at is null and rules_accepted_at is not null
    ) or not exists (
        select 1 from public.profiles
        where id = new.buyer_id and blocked_at is null and rules_accepted_at is not null
    ) then
        raise exception 'Participant unavailable.' using errcode = '23514';
    end if;
    new.seller_id := item.seller_id;
    new.original_listing_id := item.id;
    new.listing_title_snapshot := item.title;
    new.price_cents := item.price_cents;
    return new;
end;
$$;

drop trigger if exists conversations_capture_listing on public.conversations;
create trigger conversations_capture_listing
before insert on public.conversations
for each row execute function public.messaging_capture_listing();

-- Only the nested FK action may clear a live reference, only after the parent
-- has actually disappeared, and only if EVERY other column remains identical.
-- No relinking, snapshot edits, participant edits, or direct updates are allowed.
create or replace function public.messaging_reject_conversation_update()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if pg_catalog.pg_trigger_depth() > 1
       and old.listing_id is not null and new.listing_id is null
       and (pg_catalog.to_jsonb(new) - 'listing_id') = (pg_catalog.to_jsonb(old) - 'listing_id')
       and not exists (select 1 from public.listings where id = old.listing_id) then
        return new;
    end if;
    raise exception 'Conversations are immutable.' using errcode = '23514';
end;
$$;

drop trigger if exists conversations_reject_update on public.conversations;
create trigger conversations_reject_update
before update on public.conversations
for each row execute function public.messaging_reject_conversation_update();

alter table public.conversations enable row level security;
alter table public.messages enable row level security;

-- No anon/authenticated policies: direct end-user access is denied.
-- Clear Supabase default grants, then grant only server reads and inserts.
revoke all on public.conversations, public.messages
    from public, anon, authenticated, service_role;
revoke all on sequence public.messages_id_seq
    from public, anon, authenticated, service_role;

grant select on public.conversations, public.messages to service_role;
-- Snapshot/identity columns are filled only by the INSERT trigger.
grant insert (buyer_id, listing_id) on public.conversations to service_role;
grant insert (conversation_id, sender_id, client_message_id, body)
    on public.messages to service_role;
grant usage on sequence public.messages_id_seq to service_role;

revoke all on function public.messaging_validate_sender()
    from public, anon, authenticated;
revoke all on function public.messaging_reject_conversation_update()
    from public, anon, authenticated;
grant execute on function public.messaging_validate_sender() to service_role;
grant execute on function public.messaging_reject_conversation_update() to service_role;

revoke all on function public.messaging_capture_listing() from public, anon, authenticated;
grant execute on function public.messaging_capture_listing() to service_role;

-- Use INSERT, not update-based UPSERT. A buyer/listing unique conflict is read
-- back and validated by the repository; the immutable original ID remains unique
-- even after the live FK becomes NULL. There is no FK on original_listing_id.
-- Send retries reuse client_message_id and must match the original sender/body.
-- History reads and sends use conversation membership, not live listing existence.
-- No UPDATE/DELETE grants, no Realtime publication changes, no fake fixtures.
-- Future schema changes must retain these restrictions and history snapshots.
-- The sender's status is checked again during INSERT; it does not replace the
-- uncached server-side profile check for reads or authenticate the supplied ID.
-- Profile deletion is intentionally RESTRICTed by buyer/seller/sender FKs. Agree
-- a separate retention/anonymization policy before introducing account deletion.
-- Database/table owners can bypass these ordinary-role protections; this is not
-- a security boundary against a project administrator or leaked server key.


-- Structured price offers -----------------------------------------------------
-- Offer notes live on the offer itself; no duplicate messages are inserted.
-- The pending/accepted row is the single actionable proposal per conversation.
-- Accepting is price agreement ONLY: no listing, purchase or payment is changed.
-- The 500000-cent cap matches listings.MAX_PRICE_CENTS; update both together.
create table if not exists public.offers (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete restrict,
    sender_id bigint not null references public.profiles(id) on delete restrict,
    amount_cents integer not null check (amount_cents between 1 and 500000),
    note text check (note is null or char_length(note) between 1 and 2000),
    parent_offer_id uuid,
    status text not null default 'pending'
        check (status in ('pending', 'accepted', 'declined', 'superseded')),
    created_at timestamptz not null default now(),
    responded_at timestamptz,
    unique (id, conversation_id),
    foreign key (parent_offer_id, conversation_id)
        references public.offers(id, conversation_id) on delete restrict,
    check (parent_offer_id is null or parent_offer_id <> id),
    check ((status = 'pending') = (responded_at is null))
);
create unique index if not exists offers_one_actionable
    on public.offers(conversation_id) where status in ('pending', 'accepted');
create index if not exists offers_history_idx on public.offers(conversation_id, created_at desc, id desc);
create index if not exists offers_sender_idx on public.offers(sender_id);
create index if not exists offers_parent_idx on public.offers(parent_offer_id, conversation_id);

-- Private idempotency records serialize retries even if they target different
-- conversations. Store normalized arguments, so reusing a key for another action
-- or a different price/note is rejected. A retry returns the offer's CURRENT row.
create table if not exists public.offer_operations (
    actor_id bigint not null references public.profiles(id) on delete restrict,
    operation_id uuid not null,
    payload jsonb not null,
    offer_id uuid not null references public.offers(id) on delete restrict,
    created_at timestamptz not null default now(),
    primary key (actor_id, operation_id)
);
create index if not exists offer_operations_offer_idx on public.offer_operations(offer_id);
alter table public.offers enable row level security;
alter table public.offer_operations enable row level security;
revoke all on public.offers, public.offer_operations from public, anon, authenticated, service_role;
grant select on public.offers to service_role;

-- Defense against edits to historical cards. Mutable fields have only one
-- transition: pending -> accepted/declined/superseded. No reopening or repricing.
create or replace function public.messaging_guard_offer_update()
returns trigger language plpgsql security invoker set search_path = ''
as $$
begin
    if (pg_catalog.to_jsonb(new) - 'status' - 'responded_at')
       is distinct from (pg_catalog.to_jsonb(old) - 'status' - 'responded_at')
       or old.status <> 'pending'
       or new.status not in ('accepted', 'declined', 'superseded')
       or new.responded_at is null then
        raise exception 'Offer history is immutable.' using errcode = '23514';
    end if;
    return new;
end;
$$;
drop trigger if exists offers_guard_update on public.offers;
create trigger offers_guard_update before update on public.offers
for each row execute function public.messaging_guard_offer_update();
revoke all on function public.messaging_guard_offer_update() from public, anon, authenticated, service_role;

-- SECURITY DEFINER is needed because service_role has no direct offer writes.
-- Execute only from database.py after deriving actor from verified Auth0 login.
-- This function checks membership/status; it cannot authenticate an actor ID.
-- Fixed search_path and fully-qualified objects prevent name substitution.
create or replace function public.messaging_offer_action(
    p_conversation_id uuid, p_actor_id bigint, p_action text, p_operation_id uuid,
    p_offer_id uuid default null, p_amount_cents integer default null,
    p_note text default null
) returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
    c public.conversations%rowtype;
    item public.listings%rowtype;
    current_offer public.offers%rowtype;
    result_offer public.offers%rowtype;
    previous_operation public.offer_operations%rowtype;
    normalized_note text := nullif(btrim(p_note), '');
    arguments jsonb;
begin
    if p_actor_id is null or p_operation_id is null or p_conversation_id is null
       or p_action is null or p_action not in ('send', 'counter', 'accept', 'decline') then
        raise exception 'Invalid offer operation.' using errcode = '23514';
    end if;
    -- Identity and membership are checked before any idempotency result is read.
    select * into c from public.conversations where id = p_conversation_id;
    if not found or p_actor_id not in (c.buyer_id, c.seller_id) then
        raise exception 'Conversation unavailable.' using errcode = '23514';
    end if;
    if not exists (select 1 from public.profiles where id = p_actor_id
                   and blocked_at is null and rules_accepted_at is not null) then
        raise exception 'Account unavailable.' using errcode = '23514';
    end if;
    if (p_action in ('send', 'counter') and
        (p_amount_cents is null or p_amount_cents < 1 or p_amount_cents > 500000
         or char_length(normalized_note) > 2000))
       or (p_action in ('accept', 'decline') and (p_amount_cents is not null or normalized_note is not null))
       or (p_action = 'send' and p_offer_id is not null)
       or (p_action <> 'send' and p_offer_id is null) then
        raise exception 'Invalid offer payload.' using errcode = '23514';
    end if;
    arguments := jsonb_build_object('conversation_id', p_conversation_id,
        'action', p_action, 'offer_id', p_offer_id, 'amount_cents', p_amount_cents, 'note', normalized_note);
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_actor_id::text || ':' || p_operation_id::text, 0));
    select * into previous_operation from public.offer_operations
        where actor_id = p_actor_id and operation_id = p_operation_id;
    if found then
        if previous_operation.payload is distinct from arguments then
            raise exception 'Offer retry does not match the original action.' using errcode = '23514';
        end if;
        select * into result_offer from public.offers where id = previous_operation.offer_id;
        return pg_catalog.to_jsonb(result_offer);
    end if;

    -- Lock order is listing -> conversation -> offer, matching listing deletion's
    -- FK update. Never take the conversation lock before the live listing lock.
    select * into item from public.listings where id = c.listing_id for share;
    if not found or item.status <> 'active' or item.seller_id <> c.seller_id then
        raise exception 'Listing is unavailable for offers.' using errcode = '23514';
    end if;
    select * into c from public.conversations where id = p_conversation_id for update;
    if c.listing_id is distinct from item.id then
        raise exception 'Listing is unavailable for offers.' using errcode = '23514';
    end if;
    if (select count(*) from public.profiles
        where id in (c.buyer_id, c.seller_id)
          and blocked_at is null and rules_accepted_at is not null) <> 2 then
        raise exception 'Participant unavailable.' using errcode = '23514';
    end if;
    select * into current_offer from public.offers
        where conversation_id = c.id and status in ('pending', 'accepted') for update;
    if p_action = 'send' then
        if p_actor_id <> c.buyer_id or current_offer.id is not null then
            raise exception 'Only the buyer can start a new negotiation when no offer is current.' using errcode = '23514';
        end if;
    else
        if current_offer.id is null or current_offer.id <> p_offer_id
           or current_offer.status <> 'pending' or current_offer.sender_id = p_actor_id then
            raise exception 'Only the recipient can respond to the current pending offer.' using errcode = '23514';
        end if;
        update public.offers set status = case p_action
            when 'accept' then 'accepted' when 'decline' then 'declined' else 'superseded' end,
            responded_at = now() where id = current_offer.id returning * into result_offer;
    end if;
    if p_action in ('send', 'counter') then
        insert into public.offers(conversation_id, sender_id, amount_cents, note, parent_offer_id)
        values (c.id, p_actor_id, p_amount_cents, normalized_note,
                case when p_action = 'counter' then p_offer_id else null end)
        returning * into result_offer;
    end if;
    insert into public.offer_operations(actor_id, operation_id, payload, offer_id)
        values (p_actor_id, p_operation_id, arguments, result_offer.id);
    return pg_catalog.to_jsonb(result_offer);
end;
$$;
revoke all on function public.messaging_offer_action(uuid, bigint, text, uuid, uuid, integer, text)
    from public, anon, authenticated;
grant execute on function public.messaging_offer_action(uuid, bigint, text, uuid, uuid, integer, text)
    to service_role;

commit;
