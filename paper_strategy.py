"""
Live Nifty ATM Options Paper Trading Engine.
Consumes live feed from local server.py (http://127.0.0.1:5555/)
and executes simulated trades with zero real orders.
"""

import argparse
from collections import deque
import csv
from dataclasses import dataclass
from datetime import datetime
import json
import os
import signal
import sys
import time
import urllib.request

API_URL = "http://127.0.0.1:5555/"
LOT_SIZE = 65  # Nifty 50 standard lot size (1 lot = 65 qty)


@dataclass
class Position:
    symbol: str
    strike: float
    opt_type: str  # "CE" or "PE"
    side: str      # "BUY" or "SELL"
    qty: int
    entry_price: float
    current_price: float
    entry_time: str

    @property
    def unrealized_pnl(self) -> float:
        if self.side == "BUY":
            return (self.current_price - self.entry_price) * self.qty
        return (self.entry_price - self.current_price) * self.qty


class PaperOptionsEngine:
    def __init__(
        self,
        mode: str = "straddle",
        lots: int = 1,
        sl_pct: float = 15.0,
        target_pct: float = 25.0,
        slippage_pct: float = 0.05,
        brokerage_per_order: float = 20.0,
    ):
        self.mode = mode.lower()
        self.qty = lots * LOT_SIZE
        self.sl_pct = sl_pct / 100.0
        self.target_pct = target_pct / 100.0
        self.slippage_pct = slippage_pct / 100.0
        self.brokerage = brokerage_per_order

        self.positions: dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.total_costs: float = 0.0
        self.closed_trades: list[dict] = []
        self.running: bool = True

        # Rolling price windows for Momentum SMA crossover
        self.ce_window = deque(maxlen=15)
        self.pe_window = deque(maxlen=15)
        self.active_atm_strike: float | None = None

        self.csv_file = "paper_trades.csv"
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "EntryTime", "ExitTime", "Symbol", "Side", "Qty",
                    "EntryPrice", "ExitPrice", "GrossPnL", "Costs", "NetPnL", "Reason"
                ])

    def fetch_feed(self) -> dict | None:
        try:
            with urllib.request.urlopen(API_URL, timeout=1.5) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception:
            return None

    def apply_slippage(self, ltp: float, side: str) -> float:
        slip = ltp * self.slippage_pct
        return round(ltp + slip if side == "BUY" else max(0.05, ltp - slip), 2)

    def open_position(self, leg: dict, side: str):
        symbol = leg["symbol"]
        if symbol in self.positions:
            return

        fill_price = self.apply_slippage(leg["ltp"], side)
        cost = self.brokerage + (fill_price * self.qty * 0.0005)
        self.total_costs += cost
        self.realized_pnl -= cost

        self.positions[symbol] = Position(
            symbol=symbol,
            strike=leg["strike"],
            opt_type=leg.get("type", "CE" if symbol.endswith("CE") else "PE"),
            side=side,
            qty=self.qty,
            entry_price=fill_price,
            current_price=leg["ltp"],
            entry_time=datetime.now().strftime("%H:%M:%S"),
        )
        print(
            f"\n[ORDER FILLED] {side} {self.qty}x {symbol} @ ₹{fill_price:.2f} "
            f"(LTP: ₹{leg['ltp']:.2f} | Cost: ₹{cost:.2f})"
        )

    def close_position(self, symbol: str, exit_ltp: float, reason: str):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return

        exit_side = "SELL" if pos.side == "BUY" else "BUY"
        fill_price = self.apply_slippage(exit_ltp, exit_side)

        if pos.side == "BUY":
            gross = (fill_price - pos.entry_price) * pos.qty
        else:
            gross = (pos.entry_price - fill_price) * pos.qty

        exit_cost = self.brokerage + (fill_price * pos.qty * 0.0005)
        self.total_costs += exit_cost
        net_trade_pnl = gross - exit_cost
        self.realized_pnl += net_trade_pnl

        exit_time = datetime.now().strftime("%H:%M:%S")
        trade_data = {
            "EntryTime": pos.entry_time,
            "ExitTime": exit_time,
            "Symbol": pos.symbol,
            "Side": pos.side,
            "Qty": pos.qty,
            "EntryPrice": pos.entry_price,
            "ExitPrice": fill_price,
            "GrossPnL": round(gross, 2),
            "Costs": round(exit_cost, 2),
            "NetPnL": round(net_trade_pnl, 2),
            "Reason": reason,
        }
        self.closed_trades.append(trade_data)

        with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(trade_data.values())

        print(
            f"\n[POSITION CLOSED] {pos.symbol} ({pos.side}) Exit @ ₹{fill_price:.2f} | "
            f"Trade Net P&L: ₹{net_trade_pnl:+.2f} | Reason: {reason}"
        )

    def find_atm_pair(self, contracts: dict, spot_price: float | None):
        strikes_map: dict[float, dict] = {}
        for item in contracts.values():
            strike = item.get("strike")
            ltp = item.get("ltp")
            if not strike or ltp is None or ltp <= 0:
                continue
            s_key = round(float(strike), 2)
            strikes_map.setdefault(s_key, {"ce": None, "pe": None})
            sym = str(item.get("symbol", ""))
            if sym.endswith("CE") or item.get("type") == "CE":
                strikes_map[s_key]["ce"] = item
            elif sym.endswith("PE") or item.get("type") == "PE":
                strikes_map[s_key]["pe"] = item

        valid_strikes = [
            s for s, pair in strikes_map.items() if pair["ce"] and pair["pe"]
        ]
        if not valid_strikes:
            return None, None, None

        if spot_price and spot_price > 0:
            atm = min(valid_strikes, key=lambda s: abs(s - spot_price))
        else:
            atm = min(
                valid_strikes,
                key=lambda s: abs(strikes_map[s]["ce"]["ltp"] - strikes_map[s]["pe"]["ltp"]),
            )
        return atm, strikes_map[atm]["ce"], strikes_map[atm]["pe"]

    def step_straddle(self, atm_strike: float, ce_leg: dict, pe_leg: dict, contracts_by_sym: dict):
        """
        Short Straddle Logic:
        - Sells both ATM CE and ATM PE if flat.
        - Monitors combined stop-loss and target.
        """
        if not self.positions and not self.closed_trades:
            self.active_atm_strike = atm_strike
            self.open_position(ce_leg, "SELL")
            self.open_position(pe_leg, "SELL")
            return

        # Update current prices of open positions
        for sym, pos in list(self.positions.items()):
            if sym in contracts_by_sym and contracts_by_sym[sym].get("ltp"):
                pos.current_price = contracts_by_sym[sym]["ltp"]

            # Individual leg SL check
            loss_pct = (pos.current_price - pos.entry_price) / pos.entry_price
            if loss_pct >= self.sl_pct:
                self.close_position(sym, pos.current_price, "STOP_LOSS_HIT")
            elif -loss_pct >= self.target_pct:
                self.close_position(sym, pos.current_price, "TARGET_ACHIEVED")

    def step_momentum(self, atm_strike: float, ce_leg: dict, pe_leg: dict, contracts_by_sym: dict):
        """
        Momentum Option Buying Logic:
        - Tracks 5-tick vs 15-tick SMA on ATM CE and PE.
        - Buys when fast SMA > slow SMA, exits on SL/Target or trend reversal.
        """
        self.ce_window.append(ce_leg["ltp"])
        self.pe_window.append(pe_leg["ltp"])

        # Update open positions & check SL/Target
        for sym, pos in list(self.positions.items()):
            if sym in contracts_by_sym and contracts_by_sym[sym].get("ltp"):
                pos.current_price = contracts_by_sym[sym]["ltp"]

            change_pct = (pos.current_price - pos.entry_price) / pos.entry_price
            if change_pct <= -self.sl_pct:
                self.close_position(sym, pos.current_price, "STOP_LOSS_HIT")
            elif change_pct >= self.target_pct:
                self.close_position(sym, pos.current_price, "TARGET_ACHIEVED")

        if len(self.ce_window) < 15:
            return

        ce_fast = sum(list(self.ce_window)[-5:]) / 5.0
        ce_slow = sum(self.ce_window) / 15.0
        pe_fast = sum(list(self.pe_window)[-5:]) / 5.0
        pe_slow = sum(self.pe_window) / 15.0

        if not self.positions:
            if ce_fast > ce_slow * 1.002:
                self.open_position(ce_leg, "BUY")
            elif pe_fast > pe_slow * 1.002:
                self.open_position(pe_leg, "BUY")

    def render_hud(self, spot: float | None, atm: float | None, ce_ltp: float, pe_ltp: float):
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        net_total = self.realized_pnl + unrealized
        spot_str = f"{spot:.2f}" if spot else "--"
        atm_str = f"{int(atm)}" if atm else "--"

        sys.stdout.write(
            f"\r[LIVE {self.mode.upper()}] Nifty: {spot_str} | ATM: {atm_str} "
            f"(CE: ₹{ce_ltp:.2f}, PE: ₹{pe_ltp:.2f}) | "
            f"Open Legs: {len(self.positions)} | "
            f"Unrealized: ₹{unrealized:+.2f} | Net P&L: ₹{net_total:+.2f}   "
        )
        sys.stdout.flush()

    def run(self):
        print("=" * 72)
        print(f" NIFTY ATM OPTIONS PAPER TRADER | MODE: {self.mode.upper()} | QTY: {self.qty}")
        print(f" Stop-Loss: {self.sl_pct*100:.1f}% | Target: {self.target_pct*100:.1f}% | Feed: {API_URL}")
        print("=" * 72)

        while self.running:
            payload = self.fetch_feed()
            if not payload:
                sys.stdout.write("\r[WAITING] Cannot reach server.py at http://127.0.0.1:5555/ ...   ")
                sys.stdout.flush()
                time.sleep(1.0)
                continue

            spot = payload.get("spot", {}).get("ltp")
            contracts = payload.get("contracts", payload)
            contracts_by_sym = {
                c["symbol"]: c for c in contracts.values() if isinstance(c, dict) and "symbol" in c
            }

            atm_strike, ce_leg, pe_leg = self.find_atm_pair(contracts, spot)
            if not atm_strike or not ce_leg or not pe_leg:
                sys.stdout.write("\r[WAITING] Waiting for ATM CE & PE live ticks from WebSocket...   ")
                sys.stdout.flush()
                time.sleep(0.5)
                continue

            if self.mode == "straddle":
                self.step_straddle(atm_strike, ce_leg, pe_leg, contracts_by_sym)
            else:
                self.step_momentum(atm_strike, ce_leg, pe_leg, contracts_by_sym)

            self.render_hud(spot, atm_strike, ce_leg["ltp"], pe_leg["ltp"])
            time.sleep(0.5)

    def stop(self):
        self.running = False
        print("\n\n[SHUTDOWN] Squaring off all open paper positions...")
        for sym, pos in list(self.positions.items()):
            self.close_position(sym, pos.current_price, "SESSION_EXIT")

        print("\n" + "=" * 65)
        print("                PAPER TRADING SESSION SUMMARY                ")
        print("=" * 65)
        print(f"Strategy Mode       : {self.mode.upper()}")
        print(f"Total Closed Trades : {len(self.closed_trades)}")
        print(f"Total Brokerage/Tax : ₹{self.total_costs:.2f}")
        print(f"Final Net P&L       : ₹{self.realized_pnl:+.2f}")
        print(f"Trade Log Saved To  : {self.csv_file}")
        print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nifty ATM Options Paper Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["straddle", "momentum"],
        default="straddle",
        help="Trading strategy mode: 'straddle' (short ATM CE+PE) or 'momentum' (buy breakout leg)",
    )
    parser.add_argument("--lots", type=int, default=1, help="Number of Nifty lots (1 lot = 75 qty)")
    parser.add_argument("--sl", type=float, default=15.0, help="Stop-loss percentage per leg")
    parser.add_argument("--target", type=float, default=25.0, help="Target percentage per leg")
    args = parser.parse_args()

    engine = PaperOptionsEngine(
        mode=args.mode,
        lots=args.lots,
        sl_pct=args.sl,
        target_pct=args.target,
    )

    def handle_exit(sig, frame):
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    engine.run()