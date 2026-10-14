# Nifty Options Live Feed Server & Paper Trading Engine

A high-performance, lightweight Python service that streams real-time **Nifty 50 Spot** and **Nifty Options Chain** market data using Angel One's SmartAPI WebSocket 2.0. The server maintains an in-memory price cache, exposes a zero-dependency local HTTP JSON feed for decoupled IPC (Inter-Process Communication), and includes an interactive web dashboard alongside an algorithmic paper trading engine.

---

## Project Overview

Algorithmic trading setups and local market monitoring tools often face limitations with broker WebSocket connection limits and excessive memory consumption. **Nifty Options Live Feed Server** solves this by establishing a single persistent connection to the broker, automatically discovering all active option contracts for the nearest weekly/monthly Nifty expiry, and broadcasting live ticks over a local HTTP interface (`http://127.0.0.1:5555/`).

This decoupled architecture allows multiple local consumers—such as CLI testing utilities, browser-based option chain tables, and simulated execution engines—to consume real-time market ticks concurrently without creating redundant broker sessions.

---

## Key Features

- **Automated Instrument Discovery:** Automatically downloads and parses Angel One's official Scrip Master (`OpenAPIScripMaster.json`), caches it locally with a 12-hour expiration window, and resolves all active Call (CE) and Put (PE) strike contracts for the nearest active Nifty expiry.
- **WebSocket 2.0 Streaming:** Subscribes to Nifty 50 Spot (Token `99926000`, NSE CM) and streams option chain contracts in optimized 50-token batches (NSE FO) using Angel One's binary-efficient SmartWebSocketV2.
- **In-Memory Feed Server:** Runs an embedded, lightweight Python HTTP server (`http.server.HTTPServer`) in a background daemon thread, serving live spot and strike prices with CORS enabled for instant client access.
- **Live Option Chain Dashboard (`index.html`):** A standalone, responsive dark-mode web interface that polls the local feed every 500ms, displaying:
  - Live Nifty 50 Spot price with directional tick indicators (▲ / ▼).
  - Dynamic At-The-Money (ATM) strike calculation (with implied volatility parity fallback).
  - Call and Put strikes side-by-side with subtle In-The-Money (ITM) visual shading.
  - Quick-navigation "Jump to ATM" action.
- **Algorithmic Paper Trading Engine (`paper_strategy.py`):** Fully simulated execution engine supporting multiple strategies without risking real capital:
  - **Short Straddle:** Automatically sells ATM Call and Put options, tracking individual leg Stop-Loss and Target thresholds.
  - **Momentum Breakout:** Evaluates 5-tick vs 15-tick Simple Moving Average (SMA) crossovers on ATM contracts to trade breakout direction.
  - Real-world execution simulation including configurable slippage percentages and statutory/brokerage cost models (₹20 flat brokerage + 0.05% turnover tax).
  - Real-time terminal Heads-Up Display (HUD) with live P&L tracking.
  - CSV trade persistence logging executed and squared-off positions to `paper_trades.csv`.
- **Low Resource Footprint:** Designed to run efficiently on resource-constrained environments including local developer machines, Linux servers, and Android Termux environments.

---

## Technology Stack

### Backend & Core
- **Language:** Python 3 (Python 3.10+ recommended)
- **Broker SDK:** `smartapi-python` (Angel One SmartAPI & `SmartWebSocketV2`)
- **Authentication & Security:** `pyotp` (Time-based One-Time Password / 2FA generation)
- **Configuration:** `python-dotenv` (Environment variable management)
- **HTTP & Networking:** `requests` (Scrip master downloading), standard library `http.server` (Embedded feed server), standard library `urllib.request` (Client polling)
- **Concurrency:** Standard library `threading` (`threading.Thread`, `threading.Lock`)

### Frontend Dashboard
- **Core:** Semantic HTML5 & Vanilla JavaScript (ES6+, zero external build dependencies)
- **Styling:** Vanilla CSS3 (Custom CSS design system with CSS custom properties, glassmorphism-inspired borders, and dark financial palette)
- **Communication:** Native Browser `Fetch API` polling `http://127.0.0.1:5555/` every 500ms

### Storage & Persistence
- **Instrument Cache:** Local JSON file (`scrip_master.json`)
- **Trade Log:** Append-only CSV file (`paper_trades.csv`)
- **Runtime State:** Thread-safe in-memory Python dictionaries

---

## Project Structure

```plaintext
nifty-options-feed-server/
├── .env.example        # Template for required Angel One API credentials and server settings
├── .gitignore          # Git exclusion rules
├── LICENSE             # MIT License
├── README.md           # Project architecture, setup, and usage documentation
├── client.py           # Lightweight CLI client verifying server connectivity and tick feed
├── index.html          # Browser-based live Nifty option chain web dashboard
├── paper_strategy.py   # Algorithmic paper trading execution engine (Straddle & Momentum)
├── paper_trades.csv    # CSV ledger recording simulated trade executions and P&L results
├── requirements.txt    # Python package dependencies
├── scrip_master.json   # Cached Angel One instrument master file (auto-generated)
├── server.py           # Core feed server: SmartAPI WS 2.0 streaming + HTTP REST endpoint
└── logs/               # Execution logs directory organized by date
    ├── 2026-10-13/
    │   └── app.log
    └── 2026-10-14/
        └── app.log
```

---

## Application Architecture

The following diagram illustrates how data flows from the broker into the local ecosystem:

```
                  +-----------------------------------+
                  |         Angel One SmartAPI        |
                  |  - REST API (Initial Spot & Auth) |
                  |  - WebSocket 2.0 (Live Ticks)     |
                  +-----------------+-----------------+
                                    |
                            WebSocket Ticks
                                    v
+-------------------------------------------------------------------------+
| server.py (Central Feed Daemon)                                         |
|                                                                         |
|  1. Authenticates via Client Code + MPIN + TOTP (pyotp)                 |
|  2. Fetches/Caches scrip_master.json (Refreshed every 12 hrs)           |
|  3. Subscribes: Nifty Spot (99926000) + Nearest Expiry CE & PE Strikes  |
|  4. Thread-Safe In-Memory Store (STATE_LOCK):                           |
|     - SPOT_DATA                                                         |
|     - LATEST_PRICES                                                     |
|  5. Embedded HTTP Server (Daemon Thread) listening on port 5555         |
+-----------------------------------+-------------------------------------+
                                    |
                    HTTP GET / (JSON Market Feed)
                                    |
          +-------------------------+-------------------------+
          |                                                   |
          v                                                   v
+-----------------------+                         +-----------------------+
| index.html            |                         | paper_strategy.py     |
| (Browser Dashboard)   |                         | (Paper Trading Bot)   |
|                       |                         |                       |
| - Polling every 500ms |                         | - Short Straddle /    |
| - Auto ATM detection  |                         |   Momentum strategies |
| - ITM/OTM highlighting|                         | - Slippage & Cost Sim |
| - Tick directions     |                         | - Logs to CSV         |
+-----------------------+                         +-----------------------+
```

---

## Prerequisites

Before setting up the project, ensure you have:

1. **Python:** Version 3.10 or higher installed.
2. **Angel One Trading Account:** Active SmartAPI account enabled for trading APIs.
3. **SmartAPI Credentials:**
   - SmartAPI Key (generated from the Angel One Developer Portal)
   - Client Code (User ID)
   - MPIN
   - Base32 TOTP Secret Key (from your Authenticator app setup in Angel One)
4. **Operating System:** Compatible with Linux (Ubuntu/Debian), macOS, Windows, or Android (Termux).

---

## Installation and Setup

### 1. Clone the Repository
```bash
git clone <repository-url>
cd nifty-options-feed-server
```

### 2. Create and Activate a Virtual Environment
```bash
# On Linux / macOS / Termux:
python3 -m venv venv
source venv/bin/activate

# On Windows (PowerShell):
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Required Dependencies
```bash
pip install -r requirements.txt
```

---

## Environment Configuration

The application requires credentials to authenticate with Angel One SmartAPI. Copy the example configuration file and enter your credentials:

```bash
# On Linux / macOS / Termux:
cp .env.example .env

# On Windows:
copy .env.example .env
```

Open `.env` and fill in the values:

```env
# Angel One SmartAPI Credentials
ANGEL_API_KEY=your_smartapi_key_here
ANGEL_CLIENT_CODE=your_client_code_here
ANGEL_PIN=your_mpin_here
ANGEL_TOTP_SECRET=your_base32_totp_secret_here

# Server Configuration
SERVER_HOST=127.0.0.1
SERVER_PORT=5555
MAX_TOKENS=150
```

> **Security Notice:** Never commit your `.env` file to version control. The `.gitignore` file should ensure `.env` remains local.

---

## Running the Project

The project consists of three distinct executable modules:

### 1. Start the Live Feed Server
The server must be running before starting any client or strategy.

```bash
python server.py
```
**Expected Server Lifecycle:**
1. Verifies local `scrip_master.json`. If missing or older than 12 hours, downloads the latest instrument master (~35 MB) from Angel Broking's CDN.
2. Identifies the nearest active expiry for Nifty options (`OPTIDX` on `NFO`) on or after the current date.
3. Launches the local HTTP daemon on `http://127.0.0.1:5555/`.
4. Authenticates with Angel One via TOTP and initializes the Nifty 50 spot price via REST.
5. Connects to SmartWebSocketV2 and subscribes to Spot index ticks and option contracts in 50-contract batches.

---

### 2. Verify Feed via CLI Client
In a separate terminal, test the local feed server:

```bash
python client.py
```
This queries `http://127.0.0.1:5555/` once, displaying the current Nifty 50 spot price, total contract count, and the first 15 active strikes that have received live market ticks.

---

### 3. Launch the Web Dashboard
Open `index.html` directly in your web browser:
- **Direct file access:** Double-click `index.html` or drag it into any modern web browser.
- **Via a static web server (optional):**
  ```bash
  python -m http.server 8000
  ```
  Then navigate to `http://127.0.0.1:8000/index.html`.

The dashboard automatically connects to `http://127.0.0.1:5555/`, calculates the ATM strike dynamically, highlights ITM/OTM zones, and updates live tick prices.

---

### 4. Run the Paper Trading Bot
Execute automated paper trades against live prices:

#### Mode A: Short ATM Straddle (Default)
Sells both ATM Call and Put options, enforcing individual stop-losses and profit targets:
```bash
python paper_strategy.py --mode straddle --lots 1 --sl 15.0 --target 25.0
```

#### Mode B: Momentum Breakout Buyer
Monitors 5-tick vs 15-tick SMA on ATM strikes and buys the breakout leg:
```bash
python paper_strategy.py --mode momentum --lots 1 --sl 15.0 --target 25.0
```

#### Available Command-Line Arguments:
| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--mode` | string | `straddle` | Strategy logic: `straddle` (short ATM CE+PE) or `momentum` (buy breakout leg). |
| `--lots` | int | `1` | Number of Nifty lots (1 lot = 65 quantity). |
| `--sl` | float | `15.0` | Stop-loss percentage per leg (e.g., `15.0` = 15%). |
| `--target` | float | `25.0` | Profit target percentage per leg (e.g., `25.0` = 25%). |

Press `Ctrl+C` to gracefully terminate the strategy. The engine will square off all open positions with exit reason `SESSION_EXIT` and print a summary table to the console.

---

## API Documentation

The server exposes a minimal HTTP/JSON interface designed for high throughput and zero client-side dependencies.

### 1. Market Data Feed

- **URL:** `http://127.0.0.1:5555/`
- **Method:** `GET`
- **Headers Sent by Server:**
  - `Content-Type: application/json`
  - `Access-Control-Allow-Origin: *`
  - `Cache-Control: no-store, no-cache, must-revalidate`

#### Response Body:
```json
{
  "spot": {
    "token": "99926000",
    "symbol": "NIFTY 50",
    "ltp": 25145.20,
    "ts": 1728983412.354
  },
  "contracts": {
    "62341": {
      "token": "62341",
      "symbol": "NIFTY24OCT2625100CE",
      "strike": 25100.0,
      "type": "CE",
      "ltp": 142.50,
      "ts": 1728983412.311
    },
    "62342": {
      "token": "62342",
      "symbol": "NIFTY24OCT2625100PE",
      "strike": 25100.0,
      "type": "PE",
      "ltp": 128.10,
      "ts": 1728983412.298
    }
  }
}
```

### 2. CORS Preflight

- **URL:** `http://127.0.0.1:5555/`
- **Method:** `OPTIONS`
- **Headers Sent by Server:**
  - `Access-Control-Allow-Origin: *`
  - `Access-Control-Allow-Methods: GET, OPTIONS`
  - `Access-Control-Allow-Headers: *`

---

## Database & Data Persistence

The project does not rely on a standalone database service. Persistence is handled through local flat files:

1. **Instrument Cache (`scrip_master.json`):**
   - Cached copy of the Angel Broking Scrip Master.
   - Refreshed automatically if older than 43,200 seconds (12 hours) to ensure expiry dates and strike tokens stay synchronized.
2. **Trade Ledger (`paper_trades.csv`):**
   - Stores completed paper trades formatted as:
     ```csv
     EntryTime,ExitTime,Symbol,Side,Qty,EntryPrice,ExitPrice,GrossPnL,Costs,NetPnL,Reason
     13:18:56,13:29:24,NIFTY19OCT2622600CE,SELL,65,131.83,140.52,-564.85,24.57,-589.42,SESSION_EXIT
     ```
   - Captured exit reasons include `STOP_LOSS_HIT`, `TARGET_ACHIEVED`, and `SESSION_EXIT`.
3. **Execution Logs (`logs/`):**
   - Dated subfolders containing application execution logs.

---

## Authentication and Authorization

- **Broker Level:** Authenticates via Angel One SmartAPI using 4 factors:
  1. API Key (`ANGEL_API_KEY`)
  2. Client Code (`ANGEL_CLIENT_CODE`)
  3. MPIN (`ANGEL_PIN`)
  4. TOTP Code dynamically computed from the Base32 secret (`ANGEL_TOTP_SECRET`) via `pyotp`.
  Upon authentication, the API returns a JWT access token and feed token used to open the secure WebSocket session.
- **Local Feed Level:** The HTTP feed runs on `127.0.0.1` (loopback) without authentication, intended for trusted local consumption by dashboard scripts and trading bots on the same machine.

---

## Testing

The project currently does not include an automated unit testing suite (such as `pytest`). Testing is conducted through operational integration:

1. **Feed Health Verification:** Run `python client.py` to confirm that `server.py` is serving valid JSON and receiving ticks from the broker.
2. **Dashboard Visual Test:** Load `index.html` in a web browser to verify connection status pill transitions from `Connecting...` to `Live Feed`.
3. **Dry-Run Engine Test:** Run `python paper_strategy.py` with default arguments to ensure the engine connects, identifies the ATM strike pair, and receives live ticks.

---

## Build and Deployment

### Development
Run the Python scripts directly within the activated virtual environment as outlined in the [Running the Project](#running-the-project) section.

### Production / Background Execution
To run the server as a background service on Linux/Ubuntu or Termux:

```bash
# Using nohup:
nohup python3 server.py > server.log 2>&1 &

# Or configure a systemd service (/etc/systemd/system/nifty-feed.service):
[Unit]
Description=Nifty Options Live Feed Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/path/to/nifty-options-feed-server
ExecStart=/path/to/nifty-options-feed-server/venv/bin/python3 server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| `Missing Angel One credentials in .env file` | Required environment variables are empty or missing. | Ensure `.env` exists in the project root with valid `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, and `ANGEL_TOTP_SECRET`. |
| `SmartAPI package not found` | Dependency not installed in active environment. | Run `pip install -r requirements.txt` within your virtual environment. |
| `Authentication failed` | Invalid credentials, expired session, or incorrect TOTP secret. | Verify client code, MPIN, and test your TOTP secret key with an authenticator app. |
| `No active Nifty option contracts found in scrip master` | Outdated `scrip_master.json` or date filter mismatch. | Delete `scrip_master.json` and restart `server.py` to trigger a fresh download from Angel Broking. |
| `Server connection failed: [Errno 111] Connection refused` | `client.py` or dashboard cannot reach `server.py`. | Confirm that `python server.py` is running and bound to `127.0.0.1:5555`. |
| Dashboard shows `Server Offline` | Browser blocking local request or server not running. | Verify `server.py` is running and check browser console for local network permissions or CORS restrictions. |
| Prices display `--` in dashboard | Market is closed or WebSocket ticks have not yet arrived. | Option strikes update as live trades occur on NSE. Outside market hours, only strikes with initial ticks will display prices. |

---

## Known Limitations

- **Single Active Expiry:** The server dynamically loads and subscribes to strikes for the **single nearest active expiry** on or after today's date. Multi-expiry tracking across subsequent monthly/weekly contracts is not currently supported in `server.py`.
- **Trading Hours:** Live WebSocket ticks are pushed during active NSE market hours (09:15 AM to 03:30 PM IST on trading days). Outside market hours, WebSocket ticks remain static until market open.
- **In-Memory Feed State:** Feed data is held in memory and will reset if `server.py` restarts.
- **Lot Size Alignment:** `paper_strategy.py` is configured with `LOT_SIZE = 65` (reflecting NSE's updated lot size for Nifty 50 contracts).

---

## Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/new-feature`).
3. Commit your changes with clear, descriptive commit messages.
4. Push your branch to your fork (`git push origin feature/new-feature`).
5. Open a Pull Request detailing the changes made.

---

## License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for complete terms and copyright details.

Copyright (c) 2026 Prashant Kumar Maurya.