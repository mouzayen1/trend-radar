-- Trend Radar 2.0 Database Schema
-- Uses IF NOT EXISTS to preserve data across restarts

-- Signals table: raw data from all platforms
CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    platform VARCHAR(50) NOT NULL,
    entity_raw TEXT NOT NULL,
    entity_normalized TEXT,
    metric_type VARCHAR(50) NOT NULL,
    metric_value NUMERIC NOT NULL,
    url TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Indexes for signals
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_platform ON signals(platform);
CREATE INDEX IF NOT EXISTS idx_signals_entity_normalized ON signals(entity_normalized);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp_entity ON signals(timestamp, entity_normalized);

-- Velocity metrics table: computed trend data
CREATE TABLE IF NOT EXISTS velocity_metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entity_normalized TEXT NOT NULL,
    platform VARCHAR(50),
    current_value NUMERIC,
    velocity_1h NUMERIC,
    velocity_6h NUMERIC,
    velocity_24h NUMERIC,
    acceleration NUMERIC,
    platform_count INT DEFAULT 1,
    platforms_seen TEXT[],
    trend_score NUMERIC,
    novelty_score NUMERIC,
    confidence_score NUMERIC
);

-- Indexes for velocity_metrics
CREATE INDEX IF NOT EXISTS idx_velocity_timestamp ON velocity_metrics(timestamp);
CREATE INDEX IF NOT EXISTS idx_velocity_entity ON velocity_metrics(entity_normalized);
CREATE INDEX IF NOT EXISTS idx_velocity_trend_score ON velocity_metrics(trend_score DESC);

-- Alerts table: sent notifications
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    entity_normalized TEXT NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    trend_score NUMERIC,
    platforms TEXT[],
    message TEXT,
    sent_to TEXT[]
);

-- Indexes for alerts
CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_entity_type ON alerts(entity_normalized, alert_type);

-- System state table: tracks warmup status and other flags
CREATE TABLE IF NOT EXISTS system_state (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Initialize warmup state if not exists
INSERT INTO system_state (key, value, updated_at)
VALUES ('warmup_started', NULL, NOW())
ON CONFLICT (key) DO NOTHING;

INSERT INTO system_state (key, value, updated_at)
VALUES ('warmup_complete', 'false', NOW())
ON CONFLICT (key) DO NOTHING;
