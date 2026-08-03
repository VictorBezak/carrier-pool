create table if not exists broker (
    broker_id text primary key,
    name text not null,
    pool_opt_in boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists sync_file (
    broker_id text not null references broker(broker_id),
    source_file text not null,
    filename text not null,
    synced_at timestamptz not null,
    processed_at timestamptz not null default now(),
    primary key (broker_id, source_file)
);

create table if not exists carrier (
    broker_id text not null references broker(broker_id),
    carrier_id text not null,
    name text not null,
    mc_number text,
    dot_number text,
    phone text,
    home_city text,
    home_state text,
    home_zip_code text,
    updated_at timestamptz not null default now(),
    primary key (broker_id, carrier_id)
);

create table if not exists customer (
    broker_id text not null references broker(broker_id),
    customer_id text not null,
    name text not null,
    updated_at timestamptz not null default now(),
    primary key (broker_id, customer_id)
);

create table if not exists load_version (
    id bigserial primary key,
    broker_id text not null references broker(broker_id),
    source_file text not null,
    synced_at timestamptz not null,
    raw_load_id text not null,
    status text not null,
    customer_id text not null,
    customer_name text not null,
    carrier_id text,
    equipment text not null,
    pickup_city text not null,
    pickup_state text not null,
    pickup_zip_code text not null,
    delivery_city text not null,
    delivery_state text not null,
    delivery_zip_code text not null,
    pickup_open_at timestamptz,
    pickup_close_at timestamptz,
    pickup_arrived_at timestamptz,
    pickup_departed_at timestamptz,
    delivery_open_at timestamptz,
    delivery_close_at timestamptz,
    delivery_arrived_at timestamptz,
    delivery_departed_at timestamptz,
    distance_miles double precision not null,
    weight_lbs double precision,
    commodity text,
    customer_rate_usd double precision,
    carrier_rate_usd double precision,
    created_at timestamptz,
    updated_at timestamptz,
    raw jsonb not null,
    unique (broker_id, raw_load_id, source_file)
);

create index if not exists load_version_broker_synced_idx
    on load_version (broker_id, synced_at, raw_load_id);

create index if not exists load_version_broker_status_idx
    on load_version (broker_id, status);

create table if not exists hauldesk_rate (
    broker_id text not null references broker(broker_id),
    rate_id text not null,
    source_file text not null,
    synced_at timestamptz not null,
    load_num text not null,
    side text not null,
    code text not null,
    amount_usd double precision not null,
    raw jsonb not null,
    primary key (broker_id, rate_id)
);

create index if not exists hauldesk_rate_load_synced_idx
    on hauldesk_rate (broker_id, load_num, synced_at);
