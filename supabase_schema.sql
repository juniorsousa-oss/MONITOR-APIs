-- MONITOR DE APIs / CENTRAL DE DADOS SETTA
-- Execute no SQL Editor do Supabase.

create extension if not exists pgcrypto;

create table if not exists public.monitor_apis (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    app_name text,
    endpoint text not null,
    method text not null default 'GET',
    expected_status integer not null default 200,
    timeout_seconds integer not null default 10,
    warning_latency_ms integer not null default 1000,
    active boolean not null default true,
    secret_ref text,
    status text not null default 'SEM DADOS',
    last_check_at timestamptz,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    last_http_status integer,
    last_latency_ms numeric,
    consecutive_failures integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.api_checks (
    id uuid primary key default gen_random_uuid(),
    api_id uuid not null references public.monitor_apis(id) on delete cascade,
    checked_at timestamptz not null default now(),
    status text not null,
    http_status integer,
    latency_ms numeric,
    success boolean not null default false,
    error_message text
);

create index if not exists api_checks_api_time_idx
    on public.api_checks(api_id, checked_at desc);

create table if not exists public.api_incidents (
    id uuid primary key default gen_random_uuid(),
    api_id uuid not null references public.monitor_apis(id) on delete cascade,
    api_name text,
    kind text not null,
    message text,
    status text not null default 'ABERTO',
    started_at timestamptz not null default now(),
    resolved_at timestamptz
);

create index if not exists api_incidents_api_status_idx
    on public.api_incidents(api_id, status, started_at desc);

create table if not exists public.data_sources (
    source_key text primary key,
    name text not null,
    status text not null default 'AGUARDANDO',
    last_update_at timestamptz,
    rows_count integer not null default 0,
    origin text,
    last_file_name text,
    updated_at timestamptz not null default now()
);

create table if not exists public.data_imports (
    id uuid primary key default gen_random_uuid(),
    source_key text not null references public.data_sources(source_key) on delete cascade,
    file_name text not null,
    storage_path text not null,
    rows_count integer not null default 0,
    origin text,
    imported_at timestamptz not null default now()
);

create index if not exists data_imports_source_time_idx
    on public.data_imports(source_key, imported_at desc);

insert into storage.buckets (id, name, public)
values ('setta-data', 'setta-data', false)
on conflict (id) do nothing;

alter table public.monitor_apis enable row level security;
alter table public.api_checks enable row level security;
alter table public.api_incidents enable row level security;
alter table public.data_sources enable row level security;
alter table public.data_imports enable row level security;
