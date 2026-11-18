"""Alpaca, paper account only (Step 1b.4).

Every client here is created with paper=True, and settings.alpaca_settings() refuses to load when
ALPACA_PAPER isn't "true". There is no code path to a live account until Step 5.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OrderInfo:
    broker_id: str
    client_id: str
    status: str            # Alpaca's: new / accepted / partially_filled / filled / canceled / rejected / ...
    filled_qty: int
    filled_price: float | None
    stop_id: str | None = None      # the bracket's stop-loss order
    target_id: str | None = None    # the bracket's take-profit order


class AlpacaPaper:
    def __init__(self):
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient
        from app import settings
        settings.load_env()
        a = settings.alpaca_settings()            # refuses anything but paper
        self.trading = TradingClient(a.api_key, a.secret_key, paper=True)
        self.data = StockHistoricalDataClient(a.api_key, a.secret_key)

    @staticmethod
    def _info(o) -> OrderInfo:
        status = getattr(o.status, "value", str(o.status))
        price = float(o.filled_avg_price) if o.filled_avg_price else None
        stop_id = target_id = None
        for leg in getattr(o, "legs", None) or []:
            kind = getattr(leg.type, "value", str(leg.type))
            if kind == "limit":
                target_id = str(leg.id)
            elif kind in ("stop", "stop_limit"):
                stop_id = str(leg.id)
        return OrderInfo(str(o.id), o.client_order_id, status, int(float(o.filled_qty or 0)), price,
                         stop_id, target_id)

    def bracket_buy(self, symbol: str, qty: int, limit_price: float, stop: float, target: float,
                    client_id: str) -> OrderInfo:
        """Buy with a limit; once filled, Alpaca holds the stop and the target (one cancels the other).
        The same client_id twice is refused by Alpaca, so a retry can never double-order."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest
        req = LimitOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
                                limit_price=round(limit_price, 2), order_class=OrderClass.BRACKET,
                                take_profit=TakeProfitRequest(limit_price=round(target, 2)),
                                stop_loss=StopLossRequest(stop_price=round(stop, 2)),
                                client_order_id=client_id)
        return self._info(self.trading.submit_order(req))

    def order(self, client_id: str) -> OrderInfo | None:
        try:
            return self._info(self.trading.get_order_by_client_id(client_id))
        except Exception:  # noqa: BLE001 - not found
            return None

    def cancel(self, broker_id: str) -> None:
        self.trading.cancel_order_by_id(broker_id)

    # -------------------------------------------------------- positions (1b.6)

    def positions(self) -> list[dict]:
        out = []
        for p in self.trading.get_all_positions():
            out.append({"symbol": p.symbol, "qty": int(float(p.qty)), "avg_entry": float(p.avg_entry_price),
                        "price": float(p.current_price) if p.current_price else None,
                        "unrealized": float(p.unrealized_pl) if p.unrealized_pl else 0.0})
        return out

    def open_orders(self) -> list[OrderInfo]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        return [self._info(o) for o in self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))]

    def close_all(self) -> list[tuple[str, str | None]]:
        """Cancel every open order and sell every position at market. [(symbol, close order id)]."""
        out = []
        for r in self.trading.close_all_positions(cancel_orders=True) or []:
            # Alpaca puts the sell's id in order_id; the nested body isn't always parsed as an Order
            oid = getattr(r, "order_id", None) or getattr(getattr(r, "body", None), "id", None)
            out.append((r.symbol, str(oid) if oid else None))
        return out

    def last_sell_fill(self, symbol: str, after: str | None = None) -> tuple[float, str] | None:
        """(average price, filled at ISO) of the latest filled SELL in a symbol, optionally after a time.
        Used to repair an exit that was booked before its fill price was known."""
        from datetime import datetime
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        since = None
        if after:
            try:
                since = datetime.fromisoformat(str(after).replace("Z", "+00:00"))
            except ValueError:
                since = None
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[symbol], after=since, limit=50)
        best = None
        for o in self.trading.get_orders(req):
            if getattr(o.side, "value", o.side) != "sell" or not o.filled_avg_price or not o.filled_at:
                continue
            if best is None or o.filled_at > best[1]:
                best = (float(o.filled_avg_price), o.filled_at)
        return (best[0], best[1].isoformat()) if best else None

    def fill_of(self, broker_id: str) -> tuple[str, float | None]:
        """(status, filled average price) of one order."""
        o = self.trading.get_order_by_id(broker_id)
        return getattr(o.status, "value", str(o.status)), (float(o.filled_avg_price) if o.filled_avg_price else None)

    def exit_fill(self, client_id: str) -> tuple[str, float, str] | None:
        """For a bracket that already exited: ("target" | "stop", price, filled at ISO) from its legs."""
        from alpaca.trading.requests import GetOrderByIdRequest
        parent = self.trading.get_order_by_client_id(client_id)
        o = self.trading.get_order_by_id(str(parent.id), GetOrderByIdRequest(nested=True))
        for leg in o.legs or []:
            if getattr(leg.status, "value", str(leg.status)) == "filled" and leg.filled_avg_price:
                kind = getattr(leg.type, "value", str(leg.type))
                return ("target" if kind == "limit" else "stop", float(leg.filled_avg_price),
                        leg.filled_at.isoformat() if leg.filled_at else "")
        return None

    # ------------------------------------------------- managing a trade (1b.9)

    def replace_leg(self, leg_id: str, *, stop_price: float | None = None,
                    limit_price: float | None = None) -> str:
        """Change a bracket's stop (stop_price) or target (limit_price) in place. Alpaca gives the
        changed leg a NEW order id: returned, so fills can still be matched."""
        from alpaca.trading.requests import ReplaceOrderRequest
        req = ReplaceOrderRequest(stop_price=round(stop_price, 2) if stop_price is not None else None,
                                  limit_price=round(limit_price, 2) if limit_price is not None else None)
        return str(self.trading.replace_order_by_id(leg_id, req).id)

    def close_now(self, symbol: str, leg_ids: list[str], wait_s: float = 8.0) -> str:
        """Cancel the stop and target, wait until they're gone (they hold the shares), then sell at
        market. Returns the sell order's id."""
        import time
        for lid in leg_ids:
            try:
                self.trading.cancel_order_by_id(lid)
            except Exception:  # noqa: BLE001 - already filled/cancelled
                pass
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            states = []
            for lid in leg_ids:
                try:
                    states.append(getattr(self.trading.get_order_by_id(lid).status, "value", ""))
                except Exception:  # noqa: BLE001
                    states.append("canceled")
            if all(s in ("canceled", "cancelled", "filled", "expired", "replaced") for s in states):
                break
            time.sleep(0.5)
        return str(self.trading.close_position(symbol).id)

    def price(self, symbol: str) -> float | None:
        """Alpaca's current price for an open position, else the latest IEX trade."""
        try:
            p = self.trading.get_open_position(symbol)
            if p.current_price:
                return float(p.current_price)
        except Exception:  # noqa: BLE001
            pass
        return self.last_price(symbol)

    def last_price(self, symbol: str) -> float | None:
        """The latest trade (IEX, real-time on the free plan): good enough to see if a price has run."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestTradeRequest
        try:
            t = self.data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))
            return float(t[symbol].price)
        except Exception:  # noqa: BLE001
            return None
