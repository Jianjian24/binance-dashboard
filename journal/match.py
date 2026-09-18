from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from journal.tags import tags_from_cids

EPS = 1e-8


@dataclass
class Lot:
    qty: float
    price: float
    time_ms: int
    cid: str


@dataclass
class Book:
    qty: float = 0.0  # LONG/SHORT: always >= 0; BOTH: +long / -short
    lots: deque[Lot] = field(default_factory=deque)
    fill_ids: list[int] = field(default_factory=list)
    cids: list[str] = field(default_factory=list)
    realized: float = 0.0
    commission: float = 0.0
    exit_qty: float = 0.0
    exit_notional: float = 0.0
    open_time_ms: int = 0
    consumed: list[Lot] = field(default_factory=list)

    def reset(self) -> None:
        self.qty = 0.0
        self.lots.clear()
        self.fill_ids.clear()
        self.cids.clear()
        self.realized = 0.0
        self.commission = 0.0
        self.exit_qty = 0.0
        self.exit_notional = 0.0
        self.open_time_ms = 0
        self.consumed.clear()


def _vwap(lots: list[Lot]) -> float:
    total = sum(x.qty for x in lots)
    if total <= EPS:
        return 0.0
    return sum(x.qty * x.price for x in lots) / total


def _credit(book: Book, fill: dict, fraction: float = 1.0) -> None:
    book.fill_ids.append(int(fill["trade_id"]))
    cid = str(fill.get("client_order_id") or "")
    if cid:
        book.cids.append(cid)
    book.commission += float(fill.get("commission") or 0) * fraction
    book.realized += float(fill.get("realized_pnl") or 0) * fraction


def _add(book: Book, qty: float, price: float, time_ms: int, cid: str) -> None:
    if abs(book.qty) <= EPS:
        book.open_time_ms = time_ms
        book.lots.clear()
        book.consumed.clear()
        book.exit_qty = 0.0
        book.exit_notional = 0.0
    book.lots.append(Lot(qty, price, time_ms, cid))


def _reduce_lots(book: Book, qty: float, price: float) -> float:
    remain = qty
    while remain > EPS and book.lots:
        lot = book.lots[0]
        take = min(lot.qty, remain)
        book.consumed.append(Lot(take, lot.price, lot.time_ms, lot.cid))
        lot.qty -= take
        remain -= take
        if lot.qty <= EPS:
            book.lots.popleft()
    closed = qty - remain
    book.exit_qty += closed
    book.exit_notional += price * closed
    return remain


def _emit(book: Book, symbol: str, side: str, close_ms: int | None, status: str) -> dict:
    qty = book.exit_qty if status == "Closed" else sum(x.qty for x in book.lots)
    entry_src = book.consumed if status == "Closed" else list(book.lots)
    if status == "Closed" and not entry_src:
        entry_src = list(book.lots)
    first_id = book.fill_ids[0] if book.fill_ids else 0
    last_id = book.fill_ids[-1] if book.fill_ids else 0
    hold = None
    if close_ms is not None and book.open_time_ms:
        hold = max(0, int(close_ms) - int(book.open_time_ms))
    tags = tags_from_cids(book.cids)
    return {
        "id": f"{symbol}:{first_id}:{last_id}:{status}:{side}",
        "symbol": symbol,
        "side": side,
        "open_time_ms": book.open_time_ms,
        "close_time_ms": close_ms,
        "qty": qty,
        "entry_price": _vwap(entry_src),
        "exit_price": (book.exit_notional / book.exit_qty) if book.exit_qty else None,
        "realized_pnl": book.realized,
        "commission": book.commission,
        "net_pnl": book.realized - book.commission,
        "hold_ms": hold,
        "status": status,
        "tags": ",".join(tags),
        "fill_ids": ",".join(str(i) for i in book.fill_ids),
    }


def match_roundtrips(fills: list[dict]) -> list[dict]:
    """Rebuild position cycles.

    Hedge LONG/SHORT flatten independently — this matches Binance 仓位历史.
    A reduce never flips the same hedge book into the opposite side.
    One-way BOTH still flips leftover into the opposite direction.
    """
    ordered = sorted(
        fills,
        key=lambda f: (str(f["symbol"]), int(f["time_ms"]), int(f["trade_id"])),
    )
    books: dict[tuple[str, str], Book] = {}
    out: list[dict] = []

    def get(symbol: str, key: str) -> Book:
        return books.setdefault((symbol, key), Book())

    def close_side(symbol: str, key: str, side: str, time_ms: int) -> None:
        book = get(symbol, key)
        if not book.fill_ids or (book.exit_qty <= EPS and not book.consumed):
            book.reset()
            return
        out.append(_emit(book, symbol, side, time_ms, "Closed"))
        book.reset()

    for fill in ordered:
        symbol = str(fill["symbol"])
        ps = (fill.get("position_side") or "BOTH").upper()
        sd = str(fill.get("side") or "").upper()
        qty = abs(float(fill["qty"]))
        price = float(fill["price"])
        time_ms = int(fill["time_ms"])
        cid = str(fill.get("client_order_id") or "")

        if ps in ("LONG", "SHORT"):
            increasing = (ps == "LONG" and sd == "BUY") or (ps == "SHORT" and sd == "SELL")
            side = "Long" if ps == "LONG" else "Short"
            book = get(symbol, ps)
            if increasing:
                _credit(book, fill)
                _add(book, qty, price, time_ms, cid)
                book.qty += qty
                continue
            # Hedge cannot flip with one order. Extra reduce qty is ignored;
            # the other side only opens via its own LONG/SHORT fills.
            if book.qty > EPS:
                _credit(book, fill)
                _reduce_lots(book, min(qty, book.qty), price)
                book.qty = sum(x.qty for x in book.lots)
                if book.qty <= EPS:
                    close_side(symbol, ps, side, time_ms)
            continue

        book = get(symbol, "BOTH")
        delta = qty if sd == "BUY" else -qty
        net = book.qty
        if abs(net) <= EPS:
            book.reset()
            _credit(book, fill)
            _add(book, qty, price, time_ms, cid)
            book.qty = delta
            continue
        same = (net > 0 and delta > 0) or (net < 0 and delta < 0)
        if same:
            _credit(book, fill)
            _add(book, qty, price, time_ms, cid)
            book.qty = net + delta
            continue
        closed = min(qty, abs(net))
        frac = closed / qty if qty > EPS else 1.0
        _credit(book, fill, frac)
        _reduce_lots(book, closed, price)
        leftover = qty - closed
        side = "Long" if net > 0 else "Short"
        book.qty = net + (closed if delta > 0 else -closed)
        if abs(book.qty) <= EPS:
            book.qty = 0.0
            out.append(_emit(book, symbol, side, time_ms, "Closed"))
            book.reset()
            if leftover > EPS:
                _credit(book, fill, 1.0 - frac)
                _add(book, leftover, price, time_ms, cid)
                book.qty = leftover if delta > 0 else -leftover
        elif leftover > EPS:
            out.append(_emit(book, symbol, side, time_ms, "Closed"))
            book.reset()
            _credit(book, fill, 1.0 - frac)
            _add(book, leftover, price, time_ms, cid)
            book.qty = leftover if delta > 0 else -leftover

    for (symbol, key), book in books.items():
        if not book.lots or abs(book.qty) <= EPS:
            continue
        if key == "SHORT" or (key == "BOTH" and book.qty < 0):
            side = "Short"
        else:
            side = "Long"
        out.append(_emit(book, symbol, side, None, "Open"))
    return out
