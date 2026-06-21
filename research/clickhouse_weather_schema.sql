CREATE DATABASE IF NOT EXISTS pm_weather;

CREATE TABLE IF NOT EXISTS pm_weather.weather_market_catalog
(
    city_slug String,
    city_label String,
    target_date Date,
    event_slug String,
    event_title String,
    end_time_utc DateTime64(3, 'UTC'),
    event_winner_label Nullable(String),
    market_slug String,
    bucket_label String,
    condition_id String,
    yes_token_id String,
    no_token_id Nullable(String),
    is_winner Bool,
    active Bool,
    closed Bool
)
ENGINE = MergeTree
ORDER BY (city_slug, target_date, event_slug, bucket_label);

CREATE TABLE IF NOT EXISTS pm_weather.pmxt_weather_ticks
(
    source_hour DateTime('UTC'),
    timestamp_received DateTime64(3, 'UTC'),
    timestamp Nullable(DateTime64(3, 'UTC')),
    market String,
    event_type Nullable(String),
    asset_id String,
    bids String,
    asks String,
    price Nullable(Float64),
    size Nullable(Float64),
    side Nullable(String),
    best_bid Nullable(Float64),
    best_ask Nullable(Float64),
    fee_rate_bps Nullable(Float64),
    transaction_hash Nullable(String),
    old_tick_size Nullable(Float64),
    new_tick_size Nullable(Float64),
    city_slug String,
    city_label String,
    target_date Date,
    event_slug String,
    event_title String,
    end_time_utc DateTime64(3, 'UTC'),
    event_winner_label Nullable(String),
    market_slug String,
    bucket_label String,
    condition_id String,
    yes_token_id String,
    no_token_id Nullable(String),
    is_winner Bool,
    active Bool,
    closed Bool
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(target_date)
ORDER BY (city_slug, target_date, event_slug, asset_id, timestamp_received);

CREATE TABLE IF NOT EXISTS pm_weather.pmxt_weather_entry_snapshots
(
    city_slug String,
    city_label String,
    target_date Date,
    event_slug String,
    event_title String,
    event_winner_label Nullable(String),
    entry_hours Float64,
    entry_time_utc DateTime64(3, 'UTC'),
    bucket_label String,
    condition_id String,
    yes_token_id String,
    market_slug String,
    is_winner Bool,
    source_hour_key String,
    snapshot_timestamp_received Nullable(DateTime64(3, 'UTC')),
    snapshot_timestamp Nullable(DateTime64(3, 'UTC')),
    snapshot_event_type Nullable(String),
    snapshot_price Nullable(Float64),
    snapshot_best_bid Nullable(Float64),
    snapshot_best_ask Nullable(Float64),
    snapshot_side Nullable(String),
    snapshot_size Nullable(Float64),
    snapshot_fee_rate_bps Nullable(Int32)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(target_date)
ORDER BY (city_slug, target_date, event_slug, entry_hours, bucket_label);

CREATE TABLE IF NOT EXISTS pm_weather.pmxt_weather_backtests
(
    city_slug String,
    target_date Date,
    event_slug String,
    entry_hours Float64,
    entry_time_utc DateTime64(3, 'UTC'),
    selection_mode String,
    selected_labels Array(String),
    selected_prices Array(Float64),
    selected_probability_sum Float64,
    pnl Float64,
    did_hit Bool,
    winner_label Nullable(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(target_date)
ORDER BY (city_slug, target_date, event_slug, entry_hours);
