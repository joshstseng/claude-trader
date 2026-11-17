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
        return OrderInfo(str(o.id), o.client_order_id, status, int(float(o.filled_qty or 0)), price)

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

    def last_price(self, symbol: str) -> float | None:
        """The latest trade (IEX, real-time on the free plan): good enough to see if a price has run."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestTradeRequest
        try:
            t = self.data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))
            return float(t[symbol].price)
        except Exception:  # noqa: BLE001
            return None
