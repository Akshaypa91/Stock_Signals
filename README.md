# Stock Signals 📈

A live trading signal dashboard for Indian equity markets (NSE).  
Scans all 2600+ NSE equities → runs two strategies → displays Entry / SL / T1 / T2 levels on a real-time React dashboard.

**Live:** https://stock-signals-beta.vercel.app  
**API:** https://stock-signals-4fec.onrender.com/docs

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Daily Usage](#daily-usage)
- [Environment Variables](#environment-variables)
- [Upstox Authentication](#upstox-authentication)
- [Strategy Logic](#strategy-logic)
- [API Reference](#api-reference)
- [Frontend Pages](#frontend-pages)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Full NSE scan** — scans all 2600+ NSE equity stocks (not just Nifty 500)
- **Chartink webhook** — optional: receive scanner alerts automatically
- **Manual scan** — Scan Now button on dashboard scans entire NSE universe
- **yfinance fallback** — fetches OHLCV from Yahoo Finance if Upstox token missing
- **Two strategies** — S1 (Near 52-week High) and S2 (Fresh 52-week Breakout)
- **Indian market tuned** — weekly/daily mode, SL gate (skip if >12%), NSE liquidity filters
- **Auto levels** — Entry, Stop-Loss, Target 1, Target 2 calculated with ATR
- **SL quality label** — Good (≤8%) / OK (≤12%) / Wide—Skip (>12%)
- **Live LTP** — Upstox WebSocket feed with auto-reconnect
- **Auto status** — signals update to Hit T1 / Hit T2 / Stopped as LTP moves
- **Trade journal** — log entries and exits, track P&L, equity curve chart
- **Real-time dashboard** — React frontend updates live without page refresh
- **Redis cache** — OHLCV cached 1 hour intraday / 24 hours post-market
- **Auto DB migration** — new columns added automatically on startup

---

## Tech Stack

| Layer     | Technology                              |
|-----------|-----------------------------------------|
| Backend   | Python 3.11 + FastAPI + Uvicorn         |
| Database  | PostgreSQL 15 + SQLAlchemy (asyncpg)    |
| Cache     | Redis 7                                 |
| Data      | Upstox API v2 + yfinance fallback       |
| Scheduler | APScheduler (daily auto-login + scan)   |
| Frontend  | React 18 + Vite + Tailwind CSS          |
| Deploy    | Render (backend) + Vercel (frontend)    |

---

## Project Structure

```
Stock_Signals/
├── backend/
│   ├── main.py                  # FastAPI app + scheduler startup
│   ├── database.py              # Async SQLAlchemy + auto-migrations
│   ├── scheduler.py             # APScheduler: auto-login 6:30AM + scan 9:20AM IST
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── upstox/
│   │   ├── auth.py              # Token manager — save-token + OAuth2
│   │   ├── instruments.py       # Symbol→instrument_key (bundles NSE_instruments.csv)
│   │   ├── NSE_instruments.csv  # Bundled Upstox instruments master (2600+ equities)
│   │   ├── historical.py        # OHLCV fetch: Upstox primary + yfinance fallback
│   │   └── realtime.py          # WebSocket LTP feed with auto-reconnect
│   │
│   ├── engine/
│   │   ├── levels.py            # Entry/SL/T1/T2/ATR/RR/Qty + SL gate
│   │   ├── strategy1.py         # S1: Near 52-week High
│   │   ├── strategy2.py         # S2: Fresh 52-week Breakout
│   │   └── data_fetch.py        # Pipeline orchestrator + LTP monitor
│   │
│   ├── api/
│   │   ├── webhook.py           # POST /webhook/chartink
│   │   ├── stocks.py            # GET /signals
│   │   ├── trades.py            # GET/POST/PUT /trades
│   │   ├── scanner.py           # POST /scanner/run (scans ALL_NSE_SYMBOLS)
│   │   └── websocket_manager.py # Broadcast to React clients
│   │
│   ├── migrations/
│   │   ├── 001_add_sl_label_timeframe.sql
│   │   └── run_migration.py
│   │
│   └── models/
│       ├── signal.py            # Signal ORM (sl_label, timeframe fields)
│       └── trade.py             # Trade ORM model
│
├── frontend/
│   └── src/
│       └── pages/
│           ├── Dashboard.jsx    # Today's signals grid
│           ├── Signals.jsx      # Signal history + sl_label + timeframe badge
│           └── Trades.jsx       # Trade journal + P&L
│
├── .env.example
└── README.md
```

---

## Daily Usage

### Every morning (2 minutes)

**Step 1 — Get fresh Upstox token:**
```
account.upstox.com → Login → Developer Apps → your app → copy Access Token
```

**Step 2 — Save token:**
```bash
curl -X POST https://stock-signals-4fec.onrender.com/upstox/save-token \
  -H "Content-Type: application/json" \
  -d '{"access_token": "YOUR_TOKEN_HERE"}'
```

**Step 3 — Run scan (after 9:15 AM IST):**
```bash
curl -X POST "https://stock-signals-4fec.onrender.com/scanner/run?universe=both"
```

Or just click **Scan Now** on the dashboard.

**Step 4 — View signals:**

Open https://stock-signals-beta.vercel.app

---

### Updating NSE instruments (monthly)

Upstox updates their instruments list. Refresh it monthly:

```bash
cd backend/upstox
curl -L "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz" \
  -o NSE_instruments.csv.gz && gunzip -f NSE_instruments.csv.gz

# Re-extract all symbols
cd ../..
python3 extract_and_update.py

git add backend/upstox/NSE_instruments.csv backend/upstox/instruments.py
git commit -m "update NSE instruments master"
git push
```

---

## Environment Variables

| Variable              | Default          | Description                              |
|-----------------------|------------------|------------------------------------------|
| `UPSTOX_API_KEY`      | —                | Upstox API key (required)                |
| `UPSTOX_API_SECRET`   | —                | Upstox API secret (required)             |
| `UPSTOX_REDIRECT_URI` | —                | Must match Upstox app settings           |
| `DATABASE_URL`        | —                | PostgreSQL connection URL                |
| `REDIS_URL`           | —                | Redis connection URL                     |
| `CAPITAL`             | `200000`         | Total capital in Rs. for position sizing |
| `RISK_PCT`            | `1.0`            | Risk per trade as % of capital           |
| `ATR_LEN`             | `14`             | ATR period for target calculation        |
| `WEEKLY_MODE`         | `false`          | `true` = weekly chart filters            |
| `SL_MAX_PCT`          | `12.0`           | Skip signals with SL wider than this %   |
| `T1_MULT`             | `1.5` (daily) / `2.0` (weekly) | ATR multiplier for T1     |
| `T2_MULT`             | `3.0` (daily) / `4.0` (weekly) | ATR multiplier for T2     |
| `OHLCV_LOOKBACK_DAYS` | `400`            | Days of OHLCV history to fetch           |
| `ALLOWED_ORIGINS`     | —                | CORS allowed origins (comma-separated)   |

---

## Upstox Authentication

### Simple method (recommended) — Manual token

No OAuth flow needed. Just paste the token directly:

```bash
curl -X POST https://your-backend.onrender.com/upstox/save-token \
  -H "Content-Type: application/json" \
  -d '{"access_token": "eyJ..."}'
```

Token is valid for 23 hours. Do this every morning before scanning.

**Check status:**
```bash
curl https://your-backend.onrender.com/upstox/status
```

### Alternative — OAuth2 flow

```
Browser → GET /upstox/login
       → Upstox consent page
       → Login and approve
       → Redirects to /upstox/callback
       → Token saved in Redis automatically
```

---

## Strategy Logic

### Indian Market Filters (both strategies)

All strategies apply these NSE-specific filters:

| Filter | Daily | Weekly |
|--------|-------|--------|
| SL lookback bars | 5 | 10 |
| Volume multiplier | 2.0× | 1.5× |
| Min liquidity | ₹2 Cr | ₹5 Cr |
| ATR T1 multiplier | 1.5× | 2.0× |
| ATR T2 multiplier | 3.0× | 4.0× |
| Max SL% allowed | 12% | 12% |

### Strategy 1 — Near 52-Week High (S1)

| Condition   | Formula                                                     |
|-------------|-------------------------------------------------------------|
| `trend_ok`  | close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200) |
| `near_high` | close ≥ highest(high, 250) × 0.97 AND ≤ × 1.03             |
| `rsi_ok`    | 55 < RSI(14) < 78                                           |
| `vol_ok`    | volume > SMA(vol, 20) × vol_mult                            |
| `month_ok`  | close > close[21] × 1.08                                    |
| `liq_ok`    | volume × close > liq_min                                    |
| `fresh_ok`  | close > close[1] × 1.005                                    |
| `price_ok`  | close > ₹50                                                 |
| `sl_width`  | SL% ≤ SL_MAX_PCT (12%)                                      |

### Strategy 2 — Fresh 52-Week Breakout (S2)

| Condition     | Formula                                                      |
|---------------|--------------------------------------------------------------|
| `trend_ok`    | close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200) |
| `fresh_break` | close ≥ highest(high, 52/252)[yesterday] AND close[yesterday] < that level |
| `vol_ok`      | volume > SMA(vol, 50) × vol_mult                             |
| `move_ok`     | close > close[1] × 1.005                                     |
| `liq_ok`      | volume × close > liq_min                                     |
| `price_ok`    | close > ₹50                                                  |
| `sl_width`    | SL% ≤ SL_MAX_PCT (12%)                                       |

### Levels Calculator

```
entry    = close × 1.001
sl       = max(low, lowest(low, SL_LOOKBACK)) × 0.995
sl_dist  = entry − sl
sl_pct   = (sl_dist / entry) × 100

sl_label = "Good"       if sl_pct ≤ 8%
           "OK"         if sl_pct ≤ 12%
           "Wide—Skip"  if sl_pct > 12%  → signal blocked

t1       = entry + T1_MULT × ATR(14)
t2       = entry + T2_MULT × ATR(14)
rr1      = (t1 − entry) / sl_dist
rr2      = (t2 − entry) / sl_dist
qty      = floor((CAPITAL × RISK_PCT%) / sl_dist)
qty_half = floor(qty / 2)
```

---

## API Reference

### Auth

| Method | Endpoint                  | Description                        |
|--------|---------------------------|------------------------------------|
| POST   | `/upstox/save-token`      | Save token manually (simplest)     |
| GET    | `/upstox/status`          | Check token validity + expiry      |
| GET    | `/upstox/login`           | Start OAuth2 (open in browser)     |
| GET    | `/upstox/callback`        | OAuth2 redirect handler            |
| DELETE | `/upstox/logout`          | Clear stored tokens                |

### Instruments

| Method | Endpoint                  | Description                        |
|--------|---------------------------|------------------------------------|
| GET    | `/instruments/status`     | Show loaded symbol count           |
| POST   | `/instruments/reload`     | Force reload from CSV              |
| GET    | `/instruments/search?q=X` | Search by symbol or company name   |

### Signals

| Method | Endpoint                  | Description                        |
|--------|---------------------------|------------------------------------|
| GET    | `/signals`                | Today's signals                    |
| GET    | `/signals/history`        | All signals with filters           |
| GET    | `/signals/{id}`           | Single signal detail               |

### Scanner & Webhook

| Method | Endpoint                  | Description                        |
|--------|---------------------------|------------------------------------|
| POST   | `/scanner/run`            | Scan all 2600+ NSE stocks          |
| POST   | `/webhook/chartink`       | Receive Chartink alert manually    |

### WebSocket

```
wss://stock-signals-4fec.onrender.com/ws/signals
```

| Message type    | Payload                                          |
|-----------------|--------------------------------------------------|
| `new_signals`   | `{count, signals: [...]}`                        |
| `ltp`           | `{instrument_key, ltp}`                          |
| `status_update` | `{signal_id, symbol, status, ltp, reason}`       |
| `scan_complete` | `{count, signals: [...]}`                        |

Send `"ping"` → receive `"pong"` (keepalive).

---

## Frontend Pages

### Dashboard (`/`)
- Live market status (Open / Pre-Market / Closed)
- Strategy tabs: All | S1 | S2
- Signal cards: Symbol, Strategy badge, Entry/SL/T1/T2, R:R, SL% label (Good/OK), Qty

### Signals (`/signals`)
- Full history table with date/strategy/status filters
- SL label column (color-coded: green=Good, amber=OK)
- Timeframe badge (W=Weekly, D=Daily)
- Click row → detail modal
- Export CSV

### Trades (`/trades`)
- Add/close trades with P&L tracking
- Summary: Win Rate, Total P&L, Best/Worst trade
- Equity curve chart

---

## Deployment

### Backend (Render)

1. Connect GitHub repo to Render
2. Set environment variables in Render dashboard
3. Deploy — Dockerfile handles everything

**After each deploy — save token:**
```bash
curl -X POST https://your-backend.onrender.com/upstox/save-token \
  -H "Content-Type: application/json" \
  -d '{"access_token": "TOKEN"}'
```

### Frontend (Vercel)

1. Connect GitHub repo to Vercel
2. Set `VITE_API_URL` and `VITE_WS_URL` to your Render backend URL
3. Deploy automatically on every push

### Updating instruments

The `NSE_instruments.csv` is bundled in the repo. Update monthly:

```bash
cd backend/upstox
curl -L "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz" \
  -o NSE_instruments.csv.gz && gunzip -f NSE_instruments.csv.gz
cd ../..
python3 extract_and_update.py
git add backend/upstox/NSE_instruments.csv backend/upstox/instruments.py
git commit -m "update NSE instruments" && git push
```

---

## Troubleshooting

| Problem | Solution |
|---------|---------|
| `No Upstox token` | POST to `/upstox/save-token` with today's token |
| `symbol_count: 233` in scanner | Deploy latest code + call `/instruments/reload` |
| `Symbol XYZ not found` | Check `/instruments/search?q=XYZ` — name may have changed (e.g. ZOMATO → ETERNAL) |
| `Insufficient data` | Stock needs 260+ days of history — newly listed stocks won't qualify |
| `WebSocket offline` | Token expired — save fresh token, WS will reconnect |
| `0 signals after scan` | Strategy conditions are strict — not every breakout qualifies |
| `Internal Server Error` on instruments | Check CSV exists: `csv_exists` in `/instruments/status` |
| Render deploy failing | Check `requirements.txt` path in Dockerfile |

---

## License

MIT — use freely for personal trading. Not financial advice.
