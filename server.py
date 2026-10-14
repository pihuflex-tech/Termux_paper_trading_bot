"""
Nifty Options + Live Spot Feed Server.
Streams Nifty 50 Spot (Token 99926000) and all active option strikes via SmartAPI WS 2.0.
"""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import sys
import threading
import time
from dotenv import load_dotenv
import pyotp
import requests

try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
except ImportError:
    try:
        from smartapi import SmartConnect
        from smartapi.smartWebSocketV2 import SmartWebSocketV2
    except ImportError:
        raise ImportError(
            "SmartAPI package not found. Run: pip install smartapi-python"
        )

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("feed_server")

NIFTY_SPOT_TOKEN = "99926000"  # Official Angel One NSE Nifty 50 Index token

STATE_LOCK = threading.Lock()
SPOT_DATA = {
    "token": NIFTY_SPOT_TOKEN,
    "symbol": "NIFTY 50",
    "ltp": None,
    "ts": None,
}
LATEST_PRICES = {}
TOKEN_META = {}


def load_active_nifty_chain():
    """
    Loads the instrument master, identifies the nearest active Nifty option expiry,
    and pre-populates all available strikes (CE & PE).
    """
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    cache_file = "scrip_master.json"

    need_download = True
    if os.path.exists(cache_file):
        if (time.time() - os.path.getmtime(cache_file)) < 43200:
            need_download = False

    if need_download:
        logger.info("Downloading official instrument master...")
        res = requests.get(url, timeout=30)
        res.raise_for_status()
        with open(cache_file, "wb") as f:
            f.write(res.content)
        logger.info("Instrument master cached successfully.")
    else:
        logger.info("Using cached instrument master.")

    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    today = datetime.now().date()
    expiry_map = {}

    for item in data:
        if (
            item.get("name") == "NIFTY"
            and item.get("exch_seg") == "NFO"
            and item.get("instrumenttype") == "OPTIDX"
        ):
            exp_str = item.get("expiry")
            if not exp_str:
                continue
            try:
                clean_exp = exp_str.replace("-", "").upper()
                exp_date = datetime.strptime(clean_exp, "%d%b%Y").date()
                if exp_date >= today:
                    expiry_map.setdefault(exp_date, []).append(item)
            except ValueError:
                continue

    if not expiry_map:
        raise RuntimeError("No active Nifty option contracts found in scrip master.")

    nearest_expiry = sorted(expiry_map.keys())[0]
    contracts = expiry_map[nearest_expiry]

    def parse_strike(c):
        try:
            return float(c.get("strike", 0)) / 100.0
        except (ValueError, TypeError):
            return 0.0

    contracts.sort(key=parse_strike)

    subscribed_tokens = []
    with STATE_LOCK:
        for item in contracts:
            token = str(item.get("token", "")).strip()
            symbol = str(item.get("symbol", "")).strip()
            strike_val = parse_strike(item)

            if not token or strike_val <= 0:
                continue

            opt_type = (
                "CE"
                if symbol.endswith("CE")
                else ("PE" if symbol.endswith("PE") else "")
            )

            meta = {
                "token": token,
                "symbol": symbol,
                "strike": strike_val,
                "type": opt_type,
                "ltp": None,
                "ts": None,
            }
            TOKEN_META[token] = meta
            LATEST_PRICES[token] = meta.copy()
            subscribed_tokens.append(token)

    logger.info(
        f"Loaded {len(subscribed_tokens)} option contracts ({len(subscribed_tokens)//2} strikes) "
        f"for active series ({nearest_expiry.strftime('%d-%b-%Y')})."
    )
    return subscribed_tokens


class WebFeedHandler(BaseHTTPRequestHandler):
    """Serves live Nifty Spot + Option Chain state over HTTP."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()

        with STATE_LOCK:
            payload = json.dumps(
                {
                    "spot": SPOT_DATA,
                    "contracts": LATEST_PRICES,
                }
            )
        self.wfile.write(payload.encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_http_server(host: str = "127.0.0.1", port: int = 5555):
    server = HTTPServer((host, port), WebFeedHandler)
    logger.info(f"Dashboard HTTP Feed Server active at http://{host}:{port}/")
    server.serve_forever()


def run_websocket_feed(option_tokens: list):
    api_key = os.getenv("ANGEL_API_KEY")
    client_code = os.getenv("ANGEL_CLIENT_CODE")
    pin = os.getenv("ANGEL_PIN")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")

    if not all([api_key, client_code, pin, totp_secret]):
        logger.error("Missing Angel One credentials in .env file.")
        return

    smart_api = SmartConnect(api_key=api_key)
    totp = pyotp.TOTP(totp_secret).now()
    session = smart_api.generateSession(client_code, pin, totp)

    if not session.get("status"):
        logger.error(f"Authentication failed: {session.get('message')}")
        return

    jwt_token = session["data"]["jwtToken"]
    feed_token = smart_api.getfeedToken()

    # Fetch initial Nifty 50 Spot LTP via REST so spot is available immediately
    try:
        ltp_res = smart_api.ltpData("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
        if ltp_res and ltp_res.get("status") and ltp_res.get("data"):
            init_spot = float(ltp_res["data"]["ltp"])
            with STATE_LOCK:
                SPOT_DATA["ltp"] = init_spot
                SPOT_DATA["ts"] = time.time()
            logger.info(f"Initial Nifty 50 Spot Price: {init_spot:.2f}")
    except Exception as e:
        logger.warning(f"Could not fetch initial REST spot price: {e}")

    sws = SmartWebSocketV2(
        auth_token=jwt_token,
        api_key=api_key,
        client_code=client_code,
        feed_token=feed_token,
    )

    def on_open(*args, **kwargs):
        logger.info("WebSocket connected. Subscribing to Nifty Spot + Options...")

        # 1. Subscribe to Nifty 50 Index (exchangeType 1 = NSE CM)
        try:
            spot_sub = [{"exchangeType": 1, "tokens": [NIFTY_SPOT_TOKEN]}]
            sws.subscribe("nifty_spot", 1, spot_sub)
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Spot subscription error: {e}")

        # 2. Subscribe to Option Chain in 50-token batches (exchangeType 2 = NSE FO)
        batch_size = 50
        for i in range(0, len(option_tokens), batch_size):
            chunk = option_tokens[i : i + batch_size]
            token_list = [{"exchangeType": 2, "tokens": chunk}]
            correlation_id = f"nifty_batch_{i // batch_size}"
            try:
                sws.subscribe(correlation_id, 1, token_list)
                time.sleep(0.12)
            except Exception as e:
                logger.error(f"Batch subscription error: {e}")

        logger.info(
            f"Subscribed to Nifty Spot + {len(option_tokens)} option contracts."
        )

    def on_data(*args, **kwargs):
        message = None
        for arg in args:
            if isinstance(arg, (dict, list)):
                message = arg
                break

        if not message:
            return

        items = message if isinstance(message, list) else [message]

        for item in items:
            if not isinstance(item, dict):
                continue

            token = str(item.get("token") or item.get("tk", "")).strip()
            raw_price = item.get("last_traded_price")
            if raw_price is None:
                raw_price = item.get("ltp")

            if raw_price is None:
                continue

            try:
                if isinstance(raw_price, int):
                    ltp = raw_price / 100.0
                else:
                    val = float(raw_price)
                    ltp = val / 100.0 if val.is_integer() else val

                if ltp < 0:
                    continue

                now_ts = time.time()
                if token == NIFTY_SPOT_TOKEN:
                    with STATE_LOCK:
                        SPOT_DATA["ltp"] = ltp
                        SPOT_DATA["ts"] = now_ts
                elif token in TOKEN_META:
                    with STATE_LOCK:
                        LATEST_PRICES[token]["ltp"] = ltp
                        LATEST_PRICES[token]["ts"] = now_ts
            except (ValueError, TypeError):
                pass

    def on_error(*args, **kwargs):
        err = args[1] if len(args) > 1 else (args[0] if args else "Unknown Error")
        logger.error(f"WebSocket error: {err}")

    def on_close(*args, **kwargs):
        logger.warning("WebSocket connection closed.")

    sws.on_open = on_open
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close

    sws.connect()


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "5555"))
    host = os.getenv("SERVER_HOST", "127.0.0.1")

    tokens = load_active_nifty_chain()

    http_thread = threading.Thread(
        target=start_http_server, args=(host, port), daemon=True
    )
    http_thread.start()

    try:
        run_websocket_feed(tokens)
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
        sys.exit(0)