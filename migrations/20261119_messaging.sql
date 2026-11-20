-- UNAPPLIED initial Messaging migration for the real Listings schema.
-- Requires profiles and listings from database_setup.sql. Apply ONCE in a
-- development database first. Existing demo-schema tables deliberately cause
-- failure rather than silently losing data: if that earlier draft was applied,
-- a separately reviewed upgrade is required. This migration inserts no data.
--
-- Only the trusted server uses these tables. Auth0 identity is verified by
-- messaging_repository; the secret client bypasses RLS. Never expose its key.
-- Public roles have no access. Participant checks still belong at each action.
-- Existing profile deletion remains restricted while conversations reference it.
-- Listing deletion (seller or admin) remains unchanged and preserves chat history.

begin;

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

create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    buyer_id bigint not null references public.profiles(id) on delete restrict,
    seller_id bigint not null references public.profiles(id) on delete restrict,
    listing_id bigint references public.listings(id) on delete set null,
    original_listing_id bigint not null check (original_listing_id > 0),
    listing_title_snapshot text not null,
    listing_price_snapshot numeric(10, 2) not null,
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
        listing_price_snapshot >= 0 and listing_price_snapshot <> 'NaN'::numeric
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
    new.listing_price_snapshot := item.price_cents::numeric / 100;
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

commit;
