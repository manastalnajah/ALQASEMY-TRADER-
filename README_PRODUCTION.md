# ALQASEMY TRADER — Production v11 MTF

Rule-based automated trading system using a Python/FastAPI backend, PostgreSQL/Supabase and an MT5 Expert Advisor.

**No AI. No machine learning. No profitability guarantee.** The system provides engineering and risk controls; trading performance still depends on the strategy and market.

## 1. Final architecture

```text
MT5 EA
  │
  ├── account / heartbeat
  ├── positions / pending orders
  ├── broker symbol specifications
  └── closed candles
          │
          ▼
     FastAPI Backend
          │
          ├── Candle Store / Synchronization
          ├── H1 Direction
          ├── M15 Confirmation
          ├── M5 Entry
          ├── Strategy Evaluator
          ├── Risk Manager
          ├── Duplicate / Exposure Guards
          └── Trade Commands
                    │
                    ▼
                 MT5 EA
                    │
                    ▼
             Broker execution
```

## 2. Multi-timeframe model

The production roles are fixed by default:

- **H1:** market direction using MA10/MA50 context.
- **M15:** confirmation; it must agree with H1.
- **M5:** entry trigger using the enabled event-based strategy.

Pipeline:

`H1 Direction -> M15 Confirmation -> M5 Entry -> Risk Manager -> Trade Command -> MT5 -> Position Manager`

Existing positions are not closed merely because a timeframe setting changes. Breakeven/trailing management is broker/tick based and independent of the entry timeframe.

## 3. Candle policy — final

### Initial synchronization

When the backend has no history for a symbol/timeframe, the EA requests:

| Timeframe | Initial candles | Purpose |
|---|---:|---|
| H1 | 200 | direction context |
| M15 | 300 | confirmation context |
| M5 | 500 | entry context |

The backend blocks new entries until at least `MIN_CANDLES_REQUIRED=60` candles exist for every configured role.

### Live synchronization

The EA does **not** resend the complete history on every cycle.

1. Ask the backend for the latest stored candle for each symbol/timeframe.
2. If current, send nothing.
3. If a new closed candle exists, send the missing candle(s).
4. If the EA or connection was offline, recover the gap in batches.
5. The final currently-open candle is never sent as a trading candle.

The recovery batch is 1,000 candles by default and is bounded by `CandleRecoveryRoundsPerSync=20` on the EA. A large historical gap therefore recovers progressively rather than creating an unbounded HTTP payload.

### Database retention

The database keeps bounded historical market data:

- H1: 5,000 candles per symbol.
- M15: 10,000 candles per symbol.
- M5: 20,000 candles per symbol.

Retention is deliberately larger than the indicator windows so the system has enough history for restarts, recovery and diagnostics without creating an unlimited table.

### Duplicate protection

The candle identity is:

`symbol + timeframe + open_time`

A unique database constraint/index and PostgreSQL `ON CONFLICT` make candle synchronization idempotent. Sending the same candle twice cannot create duplicate rows.

## 4. Closed-candle rule

Signals are evaluated from the latest **closed** candle only.

For M5, for example, the candle currently forming from 10:20 to 10:25 is not an entry candle at 10:23. The previous closed candle is used.

The same rule applies to H1 and M15.

## 5. Strategy rules

### MA crossover

The signal is event-based:

- BUY only when M5 fast MA crosses above slow MA on the closed candle.
- SELL only when M5 fast MA crosses below slow MA.
- Direction must agree with the H1/M15 MTF bias.

The strategy does not repeatedly return BUY merely because fast MA remains above slow MA.

### RSI reversal

- BUY when RSI crosses back above 30.
- SELL when RSI crosses back below 70.
- Direction must agree with the H1/M15 MTF bias.

### Disabled by default

Smart Limits and Scalping remain disabled by default because conservative live deployment requires additional validation of their behavior.

## 6. Risk controls

- 0.5% default risk per trade.
- Maximum 1 open position.
- Maximum 1 pending order.
- Maximum 1.0 lot symbol exposure.
- 3% daily loss halt.
- 10% high-water drawdown halt.
- Minimum 300% margin level.
- Maximum 50% margin usage.
- Fresh account and position snapshots required.
- Broker tick size/value and volume specifications are required.
- Lot size is calculated from equity, risk percentage and actual SL monetary distance.
- The system never increases a position to the broker minimum when doing so would exceed the calculated risk budget.
- Every order requires SL and TP.
- PostgreSQL advisory locking closes the SELECT-then-INSERT race for duplicate trade commands.
- Persistent signal keys prevent repeated commands after worker restarts.
- The MT5 EA applies a second broker-side safety gate.

## 7. Command lifecycle

```text
pending -> processing -> executed
                     ├-> failed
                     ├-> cancelled
                     ├-> expired
                     └-> ignored
```

The EA must atomically ACK a command before execution and then report the final broker result.

## 8. MT5 synchronization endpoints

The EA uses:

- `/api/v1/mt5/account/sync`
- `/api/v1/mt5/heartbeat`
- `/api/v1/mt5/positions/sync`
- `/api/v1/mt5/pending-orders/sync`
- `/api/v1/mt5/specs/sync`
- `/api/v1/mt5/candles/status`
- `/api/v1/mt5/candles/sync`
- `/api/v1/mt5/commands`
- `/api/v1/mt5/commands/{id}/ack`
- `/api/v1/mt5/commands/{id}/report`

All MT5 endpoints can require the shared `X-MT5-Key` secret.

## 9. Deployment

1. Create the Supabase/PostgreSQL database.
2. Apply `backend/migrations/001_trading_hardening.sql` if the existing database is being upgraded.
3. Copy `backend/.env.example` to `.env` and set real secrets.
4. `SUPABASE_DB_URL` must point to the PostgreSQL database used by the project.
5. Configure `MT5_API_KEY` and `CONTROL_API_KEY` with long random secrets.
6. Add the backend URL to MT5 WebRequest allowed URLs.
7. Compile `ALQASEMY_TRADER_EA_v11.0.mq5` in MetaEditor.
8. Set `BackendURL`, `EAToken`, `EAId`, symbols and MTF inputs.
9. Verify account, positions, specifications and candle synchronization before starting the bot.
10. Test on Demo first.
11. Do not run an older EA/backend version in parallel against the same account.
12. Only after stable forward testing should a live account be considered.

## 10. Important production assumptions

The existing project database may already contain a `trading_accounts` table. The hardening migration intentionally does not invent or replace that existing business schema.

The backend expects the existing account table to provide the fields used by the risk engine, including account number, balance, equity, margin, free margin, profit, margin level, connection state and synchronization timestamps.

## 11. Docker

The backend includes a functional Dockerfile. `docker-compose.yml` runs one backend worker process and expects an external PostgreSQL/Supabase database through `.env`.

## 12. Final safety statement

This system can be engineered to reject stale data, duplicate commands, excessive risk, invalid broker geometry and unsafe account conditions. It cannot guarantee profits or eliminate market risk. Demo and forward testing remain mandatory before live deployment.
