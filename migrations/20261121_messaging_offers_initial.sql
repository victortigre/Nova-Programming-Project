-- Nova Marketplace Messaging + Offers: initial installation for an EXISTING app.
-- Prepared from feature/messaging a24444f, 2026-11-21. DO NOT EXECUTE UNTIL APPROVED.
-- Requested standalone deployment artifact; database_setup.sql stays canonical.
-- No wallet, purchase, rating, Admin or listing-policy definitions are replaced.
-- No checkout, negotiated Buy Now, alternate payments, disputes or sample data.
--
-- PREREQUISITES / EXECUTION ORDER
-- 1. Coordinate with the project owner: identify DEVELOPMENT versus shared/live
--    project, back up the database, and confirm whether Messaging was ever set up.
-- 2. Existing main app schema must already be installed (profiles/listings and
--    Wallet/purchases/ratings). Do not rerun the entire setup just for this file.
-- 3. Use an authorized database-owner/migration role in Supabase SQL Editor.
--    This file uses service_role, anon and authenticated Supabase roles.
--    Keep the server secret key out of browsers, SQL text, tickets and chat.
-- 4. Inspect existing tables, functions, triggers, grants and migration history.
--    If ANY of the four Messaging tables already exists, STOP: this file will
--    refuse to run, even if empty/compatible. Preserve data and prepare a separate
--    reviewed upgrade; NEVER drop tables or bypass the preflight to make it run.
--    Decimal snapshots/demo refs and partial prior installations need that review.
-- 5. Run the WHOLE file in a separate DEVELOPMENT project first. BEGIN/COMMIT makes
--    this migration atomic. Any error requires ROLLBACK if the editor leaves the
--    session in an aborted transaction. Do not execute statements piecemeal.
-- 6. Verify using real test Auth0 accounts and the Streamlit app (checklist below).
--    After team review, apply once to the agreed target, before using the page.
--
-- SECURITY / RETENTION
-- RLS is enabled on all four new tables. Intentionally NO anon/authenticated
-- policies: Auth0 users do not have Supabase user sessions. Only the trusted
-- Streamlit server may access data; its repository derives the actor and checks
-- membership/account status. The service role bypasses RLS. The offer RPC trusts
-- its server-supplied actor ID; never expose that key or RPC as a public endpoint.
-- Offers are mutated only by the restricted SECURITY DEFINER function.
-- Listing deletion remains permitted under main's existing rules: it clears the
-- conversation live FK and keeps immutable chat/offer snapshots and history.
-- Profile deletion is restricted while Messaging history references a profile;
-- agree retention/anonymization before introducing account deletion.
--
-- DEVELOPMENT VERIFICATION AFTER COMMIT (no test data is inserted by this file)
-- * Inspect the four tables, constraints, indexes, trigger/function definitions,
--   RLS flags and grants. anon/authenticated must have no table/RPC access.
-- * Two verified, onboarded Nova test users, neither blocked; seller creates an
--   active listing. Buyer Contact Seller twice -> one conversation. A third user
--   cannot open it. Self-contact and blocked/unverified actions must fail.
-- * Send text, refresh/restart -> persisted history. Retry an uncertain send with
--   the same client message ID -> one message; changed retry payload must fail.
-- * Send an offer without a note and with a note -> one card each, no text clone.
--   Recipient alone may accept/decline/counter the CURRENT pending offer.
--   Counter creates a new card; old card is Superseded, never deleted/repriced.
-- * Inbox reflects messages, offers and responses. Reserve/sell listing -> offer
--   actions unavailable, ordinary chat still works. Exercise availability-failure
--   fallback through mocked tests; no need to break a shared database.
-- * Acceptance changes NO credits, purchase or listing status. Buy Now disabled.
-- * Exercise normal Request to Buy, hold, delivery, return/refund and ratings to
--   confirm main behaviour. Test seller/Admin deletion using disposable listings
--   under EXISTING rules; chats survive and say Listing no longer available.
-- * Test simultaneous Contact Seller/offer responses and stable operation-ID
--   retries. Python mock tests alone do not prove SQL concurrency/permissions.
-- * No automatic Realtime delivery is configured: use Refresh chat/inbox.
--
-- FUTURE EXTENSION
-- Add Wallet-backed Buy Now in a separate reviewed migration. Preserve existing
-- conversation/offer IDs, amount_cents, statuses and offer history. Do not drop,
-- truncate, reset or reprice old messages/offers. New purchase references must
-- respect main's deletion rules and must not unexpectedly block existing deletes.

begin;

-- Serialize this migration with itself; all checks precede Messaging DDL.
select pg_catalog.pg_advisory_xact_lock(714211, 20261121);

do $preflight$
declare
    object_name text;
    requirement record;
begin
    foreach object_name in array array['service_role', 'anon', 'authenticated'] loop
        if not exists (select 1 from pg_catalog.pg_roles where rolname = object_name) then
            raise exception 'Missing Supabase role %. Run only in the reviewed Supabase project.', object_name;
        end if;
    end loop;
    if pg_catalog.to_regclass('public.profiles') is null
       or pg_catalog.to_regclass('public.listings') is null then
        raise exception 'Existing public.profiles and public.listings are required. Install/review main app schema first.';
    end if;
    for requirement in select * from (values
        ('profiles', 'id', 'bigint'),
        ('profiles', 'email', 'text'),
        ('profiles', 'blocked_at', 'timestamp with time zone'),
        ('profiles', 'rules_accepted_at', 'timestamp with time zone'),
        ('listings', 'id', 'bigint'),
        ('listings', 'seller_id', 'bigint'),
        ('listings', 'title', 'text'),
        ('listings', 'price_cents', 'integer'),
        ('listings', 'status', 'text')
    ) as expected(table_name, column_name, data_type) loop
        if not exists (
            select 1 from information_schema.columns as c
            where c.table_schema = 'public' and c.table_name = requirement.table_name
              and c.column_name = requirement.column_name and c.data_type = requirement.data_type
        ) then
            raise exception 'Base schema mismatch: %.% must be %. Review with database owner.',
                requirement.table_name, requirement.column_name, requirement.data_type;
        end if;
    end loop;
    foreach object_name in array array['conversations', 'messages', 'offers', 'offer_operations'] loop
        if pg_catalog.to_regclass('public.' || object_name) is not null then
            raise exception 'Messaging object public.% already exists. Preserve its data and use a reviewed upgrade migration.', object_name;
        end if;
        -- Catch standalone composite/domain types that would collide with tables.
        if pg_catalog.to_regtype('public.' || object_name) is not null then
            raise exception 'Type public.% already exists. Review the name conflict before execution.', object_name;
        end if;
    end loop;
    if exists (
        select 1 from pg_catalog.pg_proc as p
        join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname in (
            'messaging_validate_sender', 'messaging_capture_listing',
            'messaging_reject_conversation_update', 'messaging_guard_offer_update',
            'messaging_offer_action'
        )
    ) then
        raise exception 'A Messaging function already exists. Inspect its callers/owner/grants; do not overwrite it with this initial migration.';
    end if;
    if pg_catalog.to_regprocedure('pg_catalog.gen_random_uuid()') is null then
        raise exception 'gen_random_uuid() is required. Ask the database owner to review PostgreSQL compatibility.';
    end if;
end;
$preflight$;

-- Messaging ------------------------------------------------------------------
-- Definitions extracted from database_setup.sql at commit a24444f.
-- This is an initial installation, not an upgrade or a rerunnable setup.
-- It creates Messaging/Offers objects only and adds no checkout.
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

create table public.conversations (
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

create table public.messages (
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

create index conversations_live_listing_idx on public.conversations (listing_id) where listing_id is not null;
create index conversations_buyer_idx on public.conversations (buyer_id);
create index conversations_seller_idx on public.conversations (seller_id);
create index messages_history_idx
    on public.messages (conversation_id, created_at desc, id desc);
create index messages_sender_idx on public.messages (sender_id);

-- Foreign keys establish profile existence. This trigger additionally ensures
-- a message's sender is a participant. It does not prove who is logged in.
create function public.messaging_validate_sender()
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

create trigger messages_validate_sender
before insert or update on public.messages
for each row execute function public.messaging_validate_sender();

-- Capture identity and snapshots in the same transaction as creation. A SHARE
-- lock prevents deletion/ownership/price changes until this transaction commits.
-- If deletion wins the race, SELECT finds no listing and creation is rejected.
create function public.messaging_capture_listing()
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

create trigger conversations_capture_listing
before insert on public.conversations
for each row execute function public.messaging_capture_listing();

-- Only the nested FK action may clear a live reference, only after the parent
-- has actually disappeared, and only if EVERY other column remains identical.
-- No relinking, snapshot edits, participant edits, or direct updates are allowed.
create function public.messaging_reject_conversation_update()
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
create table public.offers (
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
create unique index offers_one_actionable
    on public.offers(conversation_id) where status in ('pending', 'accepted');
create index offers_history_idx on public.offers(conversation_id, created_at desc, id desc);
create index offers_sender_idx on public.offers(sender_id);
create index offers_parent_idx on public.offers(parent_offer_id, conversation_id);

-- Private idempotency records serialize retries even if they target different
-- conversations. Store normalized arguments, so reusing a key for another action
-- or a different price/note is rejected. A retry returns the offer's CURRENT row.
create table public.offer_operations (
    actor_id bigint not null references public.profiles(id) on delete restrict,
    operation_id uuid not null,
    payload jsonb not null,
    offer_id uuid not null references public.offers(id) on delete restrict,
    created_at timestamptz not null default now(),
    primary key (actor_id, operation_id)
);
create index offer_operations_offer_idx on public.offer_operations(offer_id);
alter table public.offers enable row level security;
alter table public.offer_operations enable row level security;
revoke all on public.offers, public.offer_operations from public, anon, authenticated, service_role;
grant select on public.offers to service_role;

-- Defense against edits to historical cards. Mutable fields have only one
-- transition: pending -> accepted/declined/superseded. No reopening or repricing.
create function public.messaging_guard_offer_update()
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
create trigger offers_guard_update before update on public.offers
for each row execute function public.messaging_guard_offer_update();
revoke all on function public.messaging_guard_offer_update() from public, anon, authenticated, service_role;

-- SECURITY DEFINER is needed because service_role has no direct offer writes.
-- Execute only from database.py after deriving actor from verified Auth0 login.
-- This function checks membership/status; it cannot authenticate an actor ID.
-- Fixed search_path and fully-qualified objects prevent name substitution.
create function public.messaging_offer_action(
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
