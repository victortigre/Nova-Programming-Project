-- FUTURE MIGRATION: review and test in an isolated development project first.
-- Requires public.profiles from database_setup.sql. Apply once, not on app startup.
-- This file creates no users, fixtures, conversations, or messages.
-- No real listings table is assumed.
--
-- Trust boundary: Streamlit authenticates through Auth0, not Supabase Auth.
-- Only database.py on the trusted server may use these tables. It must call
-- verified_nova_email() at each action, resolve that email to profiles.id, and
-- restrict every inbox/history read and send to that profile's conversations.
-- The service_role bypasses RLS: RLS does NOT authenticate its actor parameters.
-- Never expose the secret key or add permissive browser-access policies.
--
-- demo_listing_ref is an opaque key from a server-controlled fixture catalogue,
-- e.g. demo:study-desk-v1. That catalogue must define one fixed seller and listing
-- snapshot per key. The server validates against it before inserting. This SQL
-- validates the reference format, NOT catalogue membership or listing ownership.
-- Never copy numeric mock user IDs into profiles or accept listing metadata from
-- a form. Use consenting test accounts in a development project only.

begin;

create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    buyer_id bigint not null references public.profiles(id) on delete restrict,
    seller_id bigint not null references public.profiles(id) on delete restrict,
    demo_listing_ref text not null,
    listing_title_snapshot text not null,
    listing_price_snapshot numeric(10, 2) not null,
    created_at timestamptz not null default now(),
    constraint conversations_different_participants check (buyer_id <> seller_id),
    constraint conversations_demo_reference check (
        char_length(demo_listing_ref) between 6 and 100
        and demo_listing_ref ~ '^demo:[a-z0-9][a-z0-9_-]*$'
    ),
    constraint conversations_title_valid check (
        char_length(listing_title_snapshot) between 1 and 200
        and listing_title_snapshot ~ '[^[:space:]]'
    ),
    constraint conversations_price_valid check (
        listing_price_snapshot >= 0 and listing_price_snapshot <> 'NaN'::numeric
    ),
    constraint conversations_one_buyer_per_demo_listing
        unique (demo_listing_ref, buyer_id)
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
        where c.id = new.conversation_id
          and new.sender_id in (c.buyer_id, c.seller_id)
    ) then
        raise exception 'Conversation unavailable.' using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger messages_validate_sender
before insert or update on public.messages
for each row execute function public.messaging_validate_sender();

-- Keep historical participants and fixture metadata stable. Deleting a listing
-- or profile must not silently delete its conversations or message history.
create function public.messaging_reject_conversation_update()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
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
grant insert (
    buyer_id, seller_id, demo_listing_ref,
    listing_title_snapshot, listing_price_snapshot
) on public.conversations to service_role;
grant insert (conversation_id, sender_id, client_message_id, body)
    on public.messages to service_role;
grant usage on sequence public.messages_id_seq to service_role;

revoke all on function public.messaging_validate_sender()
    from public, anon, authenticated;
revoke all on function public.messaging_reject_conversation_update()
    from public, anon, authenticated;
grant execute on function public.messaging_validate_sender() to service_role;
grant execute on function public.messaging_reject_conversation_update() to service_role;

-- Backend integration requirements:
-- * Create-or-get using INSERT; on the specific buyer/reference unique conflict,
--   fetch the existing authorized conversation. Do not use update-based upserts.
-- * Generate client_message_id once per send attempt, reuse on network retry,
--   and confirm existing sender/body match before treating a conflict as success.
-- * Trim and validate body with messaging.validate_message() before insertion.
-- * Read latest message by (created_at DESC, id DESC); sort the inbox by that
--   activity, falling back to conversation.created_at for empty conversations.
-- * Pagination and queries must always be restricted to the authenticated actor.
-- * No UPDATE/DELETE privileges are granted; edits, read receipts, retention,
--   and administrative deletion require a separately reviewed migration.
-- * No Realtime publication changes are made. Start with authorized polling.
--
-- Future real listings migration (after its ID type and ownership are agreed):
-- 1. Add nullable listing_id referencing listings with ON DELETE RESTRICT.
-- 2. Make demo_listing_ref nullable and require exactly one of listing_id or
--    demo_listing_ref. Preserve test rows as explicitly marked demo history.
-- 3. Add UNIQUE(listing_id, buyer_id); retain the demo uniqueness constraint.
-- 4. Validate seller_id against the real listing owner during creation, with
--    a database constraint/trigger as well as a backend check. Define ownership
--    transfer rules so an existing conversation never changes participants.
-- 5. Keep title/price snapshots for history when a listing changes or is sold.
-- 6. Update column grants and the immutability trigger only as required for a
--    deliberate migration. Never automatically map demo keys to real listings.

commit;
