# Stock Signals 📈

A live trading signal dashboard for Indian equity markets (NSE).  
Receives Chartink breakout alerts → fetches Upstox OHLCV → runs two strategies → displays Entry / SL / T1 / T2 levels on a real-time React dashboard.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Upstox Authentication](#upstox-authentication)
- [Chartink Webhook Setup](#chartink-webhook-setup)
- [Strategy Logic](#strategy-logic)
- [API Reference](#api-reference)
- [Frontend Pages](#frontend-pages)
- [Docker Deployment](#docker-deployment)
- [Development (no Docker)](#development-no-docker)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Chartink webhook** — receives scanner alerts at market close (3:35 PM IST)
- **Upstox API v2** — fetches 1 year of daily OHLCV per stock
- **Two strategies** — S1 (Near 52-week High) and S2 (Fresh 52-week Breakout)
- **Auto levels** — Entry, Stop-Loss, Target 1, Target 2 calculated with ATR
- **Live LTP** — Upstox WebSocket feed with auto-reconnect
- **Auto status** — signals update to Hit T1 / Hit T2 / Stopped as LTP moves
- **Trade journal** — log entries and exits, track P&L, equity curve chart
- **Real-time dashboard** — React frontend updates live without page refresh
- **Redis cache** — OHLCV cached 1 hour (intraday) / 24 hours (post-market)

---

## Tech Stack

| Layer     | Technology                              |
|-----------|-----------------------------------------|
| Backend   | Python 3.11 + FastAPI + Uvicorn         |
| Database  | PostgreSQL 15 + SQLAlchemy (asyncpg)    |
| Cache     | Redis 7                                 |
| Data      | Upstox API v2 (REST + WebSocket)        |
| Frontend  | React 18 + Vite + Tailwind CSS          |
| State     | Zustand                                 |
| Charts    | Recharts                                |
| Realtime  | WebSocket (FastAPI ↔ React)             |
| Deploy    | Docker Compose                          |

---

## Project Structure

```
investors-way/
├── backend/
│   ├── main.py                  # FastAPI app, lifespan, WebSocket endpoint
│   ├── database.py              # Async SQLAlchemy + PostgreSQL
│   ├── redis_client.py          # Shared async Redis client
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── upstox/
│   │   ├── auth.py              # OAuth2 login, token refresh, Redis storage
│   │   ├── instruments.py       # Symbol → instrument_key mapper (CSV master)
│   │   ├── historical.py        # OHLCV daily candles fetch + Redis cache
│   │   └── realtime.py          # WebSocket LTP feed with auto-reconnect
│   │
│   ├── engine/
│   │   ├── levels.py            # Entry/SL/T1/T2/ATR/RR/Qty calculator
│   │   ├── strategy1.py         # S1: Near 52-week High (8 conditions)
│   │   ├── strategy2.py         # S2: Fresh 52-week Breakout (6 conditions)
│   │   └── data_fetch.py        # Pipeline orchestrator + LTP monitor callback
│   │
│   ├── api/
│   │   ├── webhook.py           # POST /webhook/chartink
│   │   ├── stocks.py            # GET /signals
│   │   ├── trades.py            # GET/POST/PUT /trades
│   │   ├── scanner.py           # POST /scanner/run
│   │   └── websocket_manager.py # Broadcast to React clients
│   │
│   └── models/
│       ├── signal.py            # Signal ORM model
│       └── trade.py             # Trade ORM model
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── package.json
│   ├── Dockerfile
│   ├── nginx.conf
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api/client.js        # Axios wrapper for all endpoints
│       ├── store/signalStore.js # Zustand global state
│       ├── hooks/
│       │   └── useWebSocket.js  # WS connection with auto-reconnect
│       ├── components/
│       │   ├── Navbar.jsx       # Nav links, WS indicator, Scan Now
│       │   ├── StockCard.jsx    # Signal card with live LTP
│       │   ├── LiveTicker.jsx   # Scrolling LTP ticker bar
│       │   └── PnLChart.jsx     # Recharts equity curve
│       └── pages/
│           ├── Dashboard.jsx    # Today's signals grid
│           ├── Signals.jsx      # Signal history table + CSV export
│           └── Trades.jsx       # Trade journal + P&L summary
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Quick Start

### Prerequisites

- Docker + Docker Compose installed
- Upstox developer account with API key + secret  
  → https://developer.upstox.com
- Chartink account (for live webhook alerts)  
  → https://chartink.com

### 1. Clone and configure

```bash
git clone https://github.com/yourname/investors-way.git
cd investors-way
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```env
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_REDIRECT_URI=http://localhost:8000/upstox/callback
POSTGRES_PASSWORD=your_secure_password
CAPITAL=200000
RISK_PCT=1.0
```

### 2. Start services

```bash
docker-compose up -d
```

This starts: PostgreSQL, Redis, FastAPI backend (port 8000), React frontend (port 3000).

### 3. Authenticate with Upstox

Open your browser and visit:

```
http://localhost:8000/upstox/login
```

Log in with your Upstox credentials and grant access. You will be redirected back and see:

```json
{ "status": "ok", "message": "Upstox authenticated successfully" }
```

The access token is stored in Redis and auto-refreshed. You only need to do this once per day (Upstox tokens expire after 24 hours).

### 4. Open the dashboard

```
http://localhost:3000
```

---

## Environment Variables

| Variable              | Default                                    | Description                              |
|-----------------------|--------------------------------------------|------------------------------------------|
| `UPSTOX_API_KEY`      | —                                          | Upstox API key (required)                |
| `UPSTOX_API_SECRET`   | —                                          | Upstox API secret (required)             |
| `UPSTOX_REDIRECT_URI` | `http://localhost:8000/upstox/callback`    | Must match Upstox app settings           |
| `DATABASE_URL`        | `postgresql://iway:changeme@postgres:5432/investorsway` | PostgreSQL connection |
| `REDIS_URL`           | `redis://redis:6379`                       | Redis connection URL                     |
| `CAPITAL`             | `200000`                                   | Total capital in Rs. for position sizing |
| `RISK_PCT`            | `1.0`                                      | Risk per trade as % of capital           |
| `ATR_LEN`             | `14`                                       | ATR period for target calculation        |
| `SL_LOOKBACK`         | `5`                                        | Bars back for swing low stop-loss        |
| `OHLCV_LOOKBACK_DAYS` | `400`                                      | Calendar days of OHLCV to fetch          |
| `ALLOWED_ORIGINS`     | `http://localhost:3000`                    | CORS allowed origins (comma-separated)   |

---

## Upstox Authentication

Upstox uses OAuth2. The flow is:

```
Browser → GET /upstox/login
       → Redirects to Upstox consent page
       → User logs in and approves
       → Upstox redirects to /upstox/callback?code=...
       → Backend exchanges code for access_token + refresh_token
       → Tokens stored in Redis
       → All subsequent API calls use Redis token automatically
```

**Token management is fully automatic** after the first login:
- Access token TTL stored in Redis (auto-evicts 5 min before expiry)
- `get_access_token()` silently refreshes when < 60 minutes remain
- If refresh fails (token revoked), visit `/upstox/login` again

**Check token status:**
```bash
curl http://localhost:8000/upstox/status
```

---

## Chartink Webhook Setup

1. Create a scanner on Chartink that matches your breakout criteria
2. Set up an Alert on the scanner
3. Choose **Webhook** as the alert method
4. Set the webhook URL to:

```
https://yourdomain.com/webhook/chartink
```

> For local testing, use [ngrok](https://ngrok.com): `ngrok http 8000`  
> Then use `https://xxxx.ngrok.io/webhook/chartink`

**Chartink sends this payload at 3:35 PM IST:**

```json
{
  "scan_name": "S1 Near 52wk High",
  "triggered_at": "15:35:00",
  "stocks": "RELIANCE,INFY,TCS",
  "trigger_prices": "2450.5,1823.0,3940.0"
}
```

The backend parses the stock list, fetches OHLCV, runs both strategies, saves signals to PostgreSQL, and broadcasts to the React dashboard — all within seconds.

**Test the webhook manually:**

```bash
curl -X POST http://localhost:8000/webhook/chartink \
  -H "Content-Type: application/json" \
  -d '{"stocks": "RELIANCE,HDFCBANK,INFY", "scan_name": "Test"}'
```

---

## Strategy Logic

### Strategy 1 — Near 52-Week High (S1)

Universe: **Nifty 200** | Timeframe: **Daily**

All of the following must be true:

| Condition   | Formula                                                    |
|-------------|------------------------------------------------------------|
| `trend_ok`  | close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200)|
| `near_high` | close ≥ highest(high, 250) × 0.97 AND ≤ × 1.03            |
| `rsi_ok`    | 55 < RSI(14) < 78                                          |
| `vol_ok`    | volume > SMA(volume, 20) × 2.0                             |
| `month_ok`  | close > close[21] × 1.08                                   |
| `liq_ok`    | volume × close > ₹2 crore                                  |
| `fresh_ok`  | close > close[1] × 1.005                                   |
| `price_ok`  | close > ₹50                                                |

### Strategy 2 — Fresh 52-Week Breakout (S2)

Universe: **Nifty 500** | Timeframe: **Daily**

| Condition     | Formula                                                     |
|---------------|-------------------------------------------------------------|
| `trend_ok`    | close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200)|
| `fresh_break` | close ≥ highest(high, 252)[yesterday] AND close[yesterday] < highest(high, 252)[yesterday] |
| `vol_ok`      | volume > SMA(volume, 50) × 2.0                              |
| `move_ok`     | close > close[1] × 1.005                                   |
| `liq_ok`      | volume × close > ₹2 crore                                  |
| `price_ok`    | close > ₹50                                                 |

### Levels Calculator (both strategies)

```
entry    = close × 1.001
sl       = max(low, lowest(low, 5)) × 0.995
sl_dist  = entry − sl
sl_pct   = (sl_dist / entry) × 100
t1       = entry + 1.5 × ATR(14)
t2       = entry + 3.0 × ATR(14)
rr1      = (t1 − entry) / sl_dist
rr2      = (t2 − entry) / sl_dist
qty      = floor((CAPITAL × RISK_PCT%) / sl_dist)
qty_half = floor(qty / 2)
```

### Trade Management

| Event          | Action                              |
|----------------|-------------------------------------|
| LTP ≤ SL       | Status → `stopped`                  |
| LTP ≥ T1       | Status → `hit_t1`, sell `qty_half`  |
| LTP ≥ T2       | Status → `hit_t2`, sell `qty_half`  |
| 2 closes < EMA(10) | Trail stop exit                 |
| 15 trading days | Time stop — exit if no target hit  |

---

## API Reference

### Signals

| Method | Endpoint                  | Description                          |
|--------|---------------------------|--------------------------------------|
| GET    | `/signals`                | Today's signals (add `?strategy=S1`) |
| GET    | `/signals/history`        | All signals with date/strategy filter|
| GET    | `/signals/{id}`           | Single signal detail                 |
| PATCH  | `/signals/{id}/status`    | Manually update signal status        |

### Trades

| Method | Endpoint       | Description                          |
|--------|----------------|--------------------------------------|
| POST   | `/trades`      | Create a new trade entry             |
| GET    | `/trades`      | List trades with P&L summary         |
| GET    | `/trades/{id}` | Single trade                         |
| PUT    | `/trades/{id}` | Close trade (sell_price, exit_reason)|
| DELETE | `/trades/{id}` | Delete trade record                  |

### Webhook & Scanner

| Method | Endpoint               | Description                     |
|--------|------------------------|---------------------------------|
| POST   | `/webhook/chartink`    | Receive Chartink alert          |
| POST   | `/scanner/run`         | Manual full-universe scan       |
| GET    | `/scanner/status`      | WS feed status + subscription count |

### Auth

| Method | Endpoint              | Description                       |
|--------|-----------------------|-----------------------------------|
| GET    | `/upstox/login`       | Start OAuth2 (open in browser)    |
| GET    | `/upstox/callback`    | OAuth2 redirect handler           |
| GET    | `/upstox/status`      | Check token validity              |
| DELETE | `/upstox/logout`      | Clear stored tokens               |

### WebSocket

```
ws://localhost:8000/ws/signals
```

Message types received by the frontend:

```jsonc
// New signals from Chartink or scanner
{ "type": "new_signals", "count": 3, "signals": [...] }

// Live price update
{ "type": "ltp", "instrument_key": "NSE_EQ|INE002A01018", "ltp": 2452.50 }

// Signal status changed
{ "type": "status_update", "signal_id": 12, "symbol": "RELIANCE", "status": "hit_t1", "ltp": 2510.00 }
```

Send `"ping"` → receive `"pong"` (keepalive).

**Interactive API docs:** http://localhost:8000/docs

---

## Frontend Pages

### Dashboard (`/`)
- Live market status (Open / Closed / Pre-Market)
- Strategy filter tabs: All | S1 | S2
- Signal cards showing: Symbol, Strategy badge, Live LTP, Entry/SL/T1/T2, R:R (color-coded), SL%, Qty, Status
- Scrolling live ticker bar at the top
- Auto-updates when new webhook arrives

### Signals (`/signals`)
- Full historical signal table with filters (date range, strategy, status)
- Click any row for a detail modal with all levels
- Export to CSV button

### Trades (`/trades`)
- Add Trade button → entry form (symbol, price, qty, date)
- Close Trade button on each open row → exit form (sell price, reason, date)
- Summary cards: Total Trades, Win Rate, Total P&L, Best/Worst Trade, Avg Hold Days
- Equity curve (Recharts line chart)
- Color-coded P&L table (green = profit, red = loss)

---

## Docker Deployment

### Development (with hot-reload)

```bash
docker-compose up
```

Backend mounts `./backend` as a volume so code changes reload automatically.

### Production

1. Set `ALLOWED_ORIGINS` to your actual domain in `.env`
2. Set `UPSTOX_REDIRECT_URI` to your production URL
3. Remove the volume mount in `docker-compose.yml` (backend service)
4. Add SSL termination (nginx reverse proxy or Cloudflare)

```bash
docker-compose up -d --build
```

### Useful commands

```bash
# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Restart backend only
docker-compose restart backend

# Connect to PostgreSQL
docker-compose exec postgres psql -U iway -d investorsway

# Flush Redis cache
docker-compose exec redis redis-cli FLUSHALL

# Check health
curl http://localhost:8000/health
```

---

## Development (no Docker)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set env vars (or create a .env file)
export DATABASE_URL=postgresql://user:pass@localhost:5432/investorsway
export REDIS_URL=redis://localhost:6379
export UPSTOX_API_KEY=...
export UPSTOX_API_SECRET=...
export CAPITAL=200000
export RISK_PCT=1.0

uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # starts on http://localhost:3000
```

---

## Troubleshooting

**`No Upstox access token found`**  
Visit `http://localhost:8000/upstox/login` in a browser to authenticate.

**`Symbol 'XYZ' not found in instruments master`**  
The instruments CSV downloads from Upstox on first run. If it fails, check network connectivity. The symbol may also not be listed as NSE_EQ (e.g. ETFs have different instrument types).

**`Insufficient data` for a signal**  
The stock needs ~260 days of daily candles. Newly listed stocks or illiquid names may not qualify.

**WebSocket shows Offline in the dashboard**  
Check that the backend is running and `VITE_WS_URL` points to the correct host. The frontend auto-reconnects every 3 seconds.

**Chartink webhook not reaching local machine**  
Use ngrok: `ngrok http 8000` and set the ngrok URL in Chartink alert settings.

**`Token refresh failed`**  
Upstox refresh tokens can be revoked if you log in from another device or change your password. Re-authenticate via `/upstox/login`.

---

## License

MIT — use freely for personal trading. Not financial advice.
