"""Tiny SOL Trend Bot — a tiny paper-trading bot for make.fun's bars-replay/v1.

The idea is deliberately small: ride an uptrend, sit in USDC otherwise.
For every symbol the harness sends, the bot tracks a fast EMA(5) and a slow
EMA(12) over hourly closes and buys only when the fast crosses above the
slow while the close is also above the close 12 bars ago — the momentum
check keeps the bot out of the whipsaw crosses a flat market throws off.
A position is sold whole when the slow EMA crosses back above the fast one,
or when it is worth 1.30x its cost (take-profit), or 0.92x (stop-loss).
Each entry risks one equal slice of the account (equity / 7, one per
universe symbol), further capped by the harness weight cap (25% of equity),
so a broad rally can hold most of the account while a single-symbol rally
holds about a seventh of it. That timing — same upside in a rising market,
much smaller losses in a falling one — is the whole edge over buy-and-hold.

Deterministic: the bot is a pure function of the bars and the hello message.
No clock, no randomness, no environment reads, so two runs on the same bars
produce the same replies byte for byte.

Run by the grader as: python3 -P -s /bot/main.py
Speaks agent-fun/bars-replay/v1 on stdin/stdout via vendor/makefun_bars.py
(a byte-identical copy of the kit's sdk/makefun_bars.py).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

FAST_SPAN = 5
SLOW_SPAN = 12
# One equal stake per universe symbol (7 here); each stake is also capped by
# the harness max_weight_bps (25% of equity), so a broad rally can hold the
# whole account while a single-symbol rally holds about a seventh of it.
STAKE_DIVISOR = 7
# Momentum filter: an entry needs the close above the close this many bars ago.
MOM_BARS = 12
# Take profit: position worth 13/10 of its cost (+30%).
TP_NUM, TP_DEN = 13, 10
# Stop loss: position worth 92/100 of its cost (-8%).
STOP_NUM, STOP_DEN = 92, 100
MAX_SLIPPAGE_BPS = 100


class EmaTracker:
    """One exponential moving average over closes.

    Warms up on the plain mean of its first `span` closes, then updates with
    the usual smoothing factor 2 / (span + 1). `value` is None until warm.
    """

    __slots__ = ("span", "alpha", "warm", "value")

    def __init__(self, span):
        self.span = span
        self.alpha = 2.0 / (span + 1)
        self.warm = []
        self.value = None

    def step(self, close):
        if self.value is not None:
            self.value += self.alpha * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class SymbolTrend:
    """Everything the bot remembers about one symbol.

    Two EMAs and the gap between them (fast minus slow), this bar and the
    bar before; the close history the momentum filter reads; and `falling`,
    a latched sell signal that stays set while the slow EMA is above the
    fast one after a downward cross.
    """

    __slots__ = ("fast", "slow", "prev_gap", "gap", "falling", "closes")

    def __init__(self):
        self.fast = EmaTracker(FAST_SPAN)
        self.slow = EmaTracker(SLOW_SPAN)
        # fast - slow after the bar before this one, once both EMAs are set.
        self.prev_gap = None
        # The same after this bar.
        self.gap = None
        # Sell signal: set on a cross of slow above fast, held while slow stays above.
        self.falling = False
        # Every close seen, oldest first.
        self.closes = []

    def feed(self, close):
        """Feed one bar's close through the EMAs and refresh the gaps."""
        self.closes.append(close)
        self.fast.step(close)
        self.slow.step(close)
        self.prev_gap = self.gap
        self.gap = (
            self.fast.value - self.slow.value
            if self.fast.value is not None and self.slow.value is not None
            else None
        )
        if self.gap is None or self.gap >= 0:
            self.falling = False

    def crossed_up(self):
        """True on the bar the fast EMA crosses above the slow one."""
        return (
            self.prev_gap is not None
            and self.gap is not None
            and self.gap > 0
            and self.prev_gap <= 0
        )

    def crossed_down(self):
        """True on the bar the slow EMA crosses above the fast one."""
        return (
            self.prev_gap is not None
            and self.gap is not None
            and self.gap < 0
            and self.prev_gap >= 0
        )

    def has_momentum(self):
        """True once the latest close is above the close MOM_BARS bars ago."""
        return len(self.closes) > MOM_BARS and self.closes[-1] > self.closes[-MOM_BARS - 1]


# Per-symbol trend state, keyed by symbol.
trends = {}


def feed_batch(batch):
    """Feed a batch's bars through their trends.

    Returns (cross_up, fresh): the symbols whose fast EMA crossed above
    their slow one on this bar with momentum behind it, and every symbol
    the batch carried a bar for. A zero-volume bar still feeds the EMAs
    (its close is a real print) but can never signal a cross.
    """
    cross_up = set()
    fresh = set()
    for bar in batch["bars"]:
        symbol = bar["symbol"]
        trend = trends.get(symbol)
        if trend is None:
            trend = SymbolTrend()
            trends[symbol] = trend
        trend.feed(float(int(bar["c"])))
        fresh.add(symbol)
        if bar.get("v") == "0":
            continue
        if trend.crossed_up() and trend.has_momentum():
            cross_up.add(symbol)
        if trend.crossed_down():
            trend.falling = True
    return cross_up, fresh


def should_exit(state, symbol, held, falling):
    """Whether a held position exits on this close: sell signal, take-profit, stop-loss."""
    if falling:
        return True
    worth = state.value(symbol, held.qty)
    return worth * TP_DEN >= held.cost * TP_NUM or worth * STOP_DEN <= held.cost * STOP_NUM


def plan_sells(state, fresh):
    """Sell orders, in universe order, for held symbols whose exit fired."""
    sells = []
    for spec in state.hello["symbols"]:
        symbol = spec["symbol"]
        if symbol not in fresh:
            continue
        held = state.positions.get(symbol)
        if held is not None and should_exit(state, symbol, held, trends[symbol].falling):
            sells.append(
                {
                    "side": "sell",
                    "symbol": symbol,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            )
    return sells


def size_buy(state, symbol, stake, cash):
    """One buy's size: the equal stake, capped by the weight cap and the cash left."""
    size = stake
    weight_room = state.weight_room(symbol)
    if size > weight_room:
        size = weight_room
    if size > cash:
        size = cash
    return size


def fill_buys(state, cross_up, orders):
    """Append buy orders for fresh cross-ups, in universe order.

    Sells go first (the caller seeds `orders` with them); buys then take
    the remaining order slots, open-position slots and cash. Every buy is
    one equal stake, capped by the harness weight cap and by the cash left.
    A stake below the harness minimum notional stops the loop: the stake is
    the same for every symbol, so a later one would be too small as well.
    """
    caps = state.hello["caps"]
    fees = state.hello["fees"]
    slots = min(len(state.hello["symbols"]), caps["max_open_positions"])
    stake = state.equity // STAKE_DIVISOR
    room = slots - len(state.positions)
    cash = state.cash
    for spec in state.hello["symbols"]:
        symbol = spec["symbol"]
        if symbol not in cross_up:
            continue
        if room <= 0 or len(orders) >= caps["max_orders_per_bar"]:
            break
        size = size_buy(state, symbol, stake, cash)
        if size <= 0 or size < int(fees["min_notional_quote_units"]):
            break
        orders.append(
            {
                "side": "buy",
                "symbol": symbol,
                "notional_quote_units": size,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        )
        cash -= size
        room -= 1


def on_batch(state, batch):
    cross_up, fresh = feed_batch(batch)
    if state.warming_up:
        return []

    caps = state.hello["caps"]
    orders = plan_sells(state, fresh)[: caps["max_orders_per_bar"]]
    fill_buys(state, cross_up, orders)
    return orders


makefun_bars.run(on_batch)
