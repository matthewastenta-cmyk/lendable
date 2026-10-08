-- Pocket Approval: per-user saved data (profile, My buildings, My deals, lender contacts).
-- Paste into Supabase > SQL Editor > New query, then Run. Safe to run more than once.

create table if not exists public.user_state (
  user_id    uuid        not null references auth.users (id) on delete cascade,
  kind       text        not null check (kind in ('profile', 'mine', 'deals', 'lendercontacts')),
  data       jsonb       not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, kind)
);

-- Row Level Security: each signed-in user can only see and change their own rows.
alter table public.user_state enable row level security;

drop policy if exists "user_state: read own"   on public.user_state;
drop policy if exists "user_state: insert own" on public.user_state;
drop policy if exists "user_state: update own" on public.user_state;
drop policy if exists "user_state: delete own" on public.user_state;

create policy "user_state: read own"   on public.user_state for select to authenticated using ((select auth.uid()) = user_id);
create policy "user_state: insert own" on public.user_state for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "user_state: update own" on public.user_state for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "user_state: delete own" on public.user_state for delete to authenticated using ((select auth.uid()) = user_id);

-- Signed-out visitors get nothing.
revoke all on public.user_state from anon;
grant select, insert, update, delete on public.user_state to authenticated;
