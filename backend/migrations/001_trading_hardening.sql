CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS strategy_name VARCHAR DEFAULT '';
ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS signal_key VARCHAR DEFAULT '';
ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS ea_id VARCHAR DEFAULT '';
ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS error_message VARCHAR DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_trade_commands_signal_key ON trade_commands(signal_key);
CREATE INDEX IF NOT EXISTS ix_trade_commands_symbol_status_created ON trade_commands(symbol,status,created_at);
CREATE TABLE IF NOT EXISTS symbol_specs (
 id SERIAL PRIMARY KEY, symbol VARCHAR(32) UNIQUE NOT NULL, digits INTEGER NOT NULL,
 point DOUBLE PRECISION NOT NULL, tick_size DOUBLE PRECISION NOT NULL, tick_value DOUBLE PRECISION NOT NULL,
 volume_min DOUBLE PRECISION NOT NULL, volume_max DOUBLE PRECISION NOT NULL, volume_step DOUBLE PRECISION NOT NULL,
 stops_level_points INTEGER NOT NULL DEFAULT 0, contract_size DOUBLE PRECISION NOT NULL DEFAULT 0,
 updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS risk_state (
 id INTEGER PRIMARY KEY DEFAULT 1, day_key VARCHAR(16) NOT NULL,
 day_start_equity DOUBLE PRECISION NOT NULL DEFAULT 0, high_water_equity DOUBLE PRECISION NOT NULL DEFAULT 0,
 trading_halted BOOLEAN NOT NULL DEFAULT FALSE, halt_reason VARCHAR(255) NOT NULL DEFAULT '',
 updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bot_state (
 id INTEGER PRIMARY KEY DEFAULT 1, is_running BOOLEAN NOT NULL DEFAULT FALSE,
 status VARCHAR(32) NOT NULL DEFAULT 'stopped', updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS position_snapshots (
 account_number BIGINT PRIMARY KEY, last_sync TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS live_positions (
 ticket VARCHAR(64) PRIMARY KEY, account_number BIGINT NOT NULL, symbol VARCHAR(32) NOT NULL,
 side VARCHAR(8) NOT NULL, volume DOUBLE PRECISION NOT NULL, price_open DOUBLE PRECISION NOT NULL,
 stop_loss DOUBLE PRECISION NOT NULL DEFAULT 0, take_profit DOUBLE PRECISION NOT NULL DEFAULT 0,
 profit DOUBLE PRECISION NOT NULL DEFAULT 0, updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_live_positions_account ON live_positions(account_number);
CREATE INDEX IF NOT EXISTS ix_live_positions_symbol ON live_positions(symbol);


CREATE TABLE IF NOT EXISTS pending_orders (
 ticket VARCHAR(64) PRIMARY KEY, account_number BIGINT NOT NULL, symbol VARCHAR(32) NOT NULL,
 side VARCHAR(16) NOT NULL, volume DOUBLE PRECISION NOT NULL, price_open DOUBLE PRECISION NOT NULL,
 stop_loss DOUBLE PRECISION NOT NULL DEFAULT 0, take_profit DOUBLE PRECISION NOT NULL DEFAULT 0,
 updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_pending_orders_account ON pending_orders(account_number);
CREATE INDEX IF NOT EXISTS ix_pending_orders_symbol ON pending_orders(symbol);

-- Market-data hardening: one immutable identity per symbol/timeframe/candle.
CREATE UNIQUE INDEX IF NOT EXISTS uix_candles_symbol_timeframe_open_time
  ON candles(symbol_name,timeframe,open_time);
CREATE INDEX IF NOT EXISTS ix_candles_symbol_timeframe_open_time
  ON candles(symbol_name,timeframe,open_time DESC);
