-- Pocket Approval: shared building-level findings (short yes/no statements; no documents, figures, names or deal details).
create table if not exists public.building_findings (
  id            uuid primary key default gen_random_uuid(),
  building_key  text not null check (char_length(building_key) between 3 and 200),
  address       text check (char_length(address) <= 200),
  market        text check (market in ('nyc','miami','nj')),
  category      text not null check (char_length(category) <= 30),
  tier          text not null check (tier in ('meets','concern','guideline_issue')),
  statement     text not null check (char_length(statement) between 3 and 140 and statement !~ '\$\s?\d'),
  doc_type      text check (char_length(doc_type) <= 30),
  as_of         text check (char_length(as_of) <= 40),
  contributor   uuid not null default auth.uid() references auth.users (id) on delete cascade,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null default (now() + interval '18 months'),
  superseded_at timestamptz
);
create index if not exists building_findings_key_idx on public.building_findings (building_key) where superseded_at is null;
alter table public.building_findings enable row level security;
drop policy if exists "findings: anyone reads current" on public.building_findings;
drop policy if exists "findings: users add their own" on public.building_findings;
drop policy if exists "findings: users delete their own" on public.building_findings;
create policy "findings: anyone reads current" on public.building_findings for select to anon, authenticated using (superseded_at is null and expires_at > now());
create policy "findings: users add their own" on public.building_findings for insert to authenticated with check ((select auth.uid()) = contributor);
create policy "findings: users delete their own" on public.building_findings for delete to authenticated using ((select auth.uid()) = contributor);
revoke all on public.building_findings from anon, authenticated;
grant select (id, building_key, address, market, category, tier, statement, doc_type, as_of, created_at, expires_at) on public.building_findings to anon, authenticated;
grant insert (building_key, address, market, category, tier, statement, doc_type, as_of) on public.building_findings to authenticated;
grant delete on public.building_findings to authenticated;
create or replace function public.supersede_older_findings() returns trigger language plpgsql security definer set search_path = '' as $$
begin
  update public.building_findings set superseded_at = now()
   where building_key = new.building_key and category = new.category and id <> new.id and superseded_at is null;
  return new;
end $$;
revoke execute on function public.supersede_older_findings() from public, anon, authenticated;
drop trigger if exists building_findings_supersede on public.building_findings;
create trigger building_findings_supersede after insert on public.building_findings for each row execute function public.supersede_older_findings();
create or replace function public.limit_findings_per_day() returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if (select count(*) from public.building_findings where contributor = new.contributor and created_at > now() - interval '1 day') >= 60 then
    raise exception 'daily limit reached';
  end if;
  return new;
end $$;
revoke execute on function public.limit_findings_per_day() from public, anon, authenticated;
drop trigger if exists building_findings_limit on public.building_findings;
create trigger building_findings_limit before insert on public.building_findings for each row execute function public.limit_findings_per_day();
