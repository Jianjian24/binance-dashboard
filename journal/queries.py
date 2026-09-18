from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from journal import db

TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TRANSFER_TYPES = frozenset({"TRANSFER"})


def _day(ms: Optional[int]) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%Y-%m-%d")


def _weekday(ms: Optional[int]) -> int:
    if not ms:
        return 0
    return datetime.fromtimestamp(ms / 1000, tz=TZ).weekday()


def _hour(ms: Optional[int]) -> int:
    if not ms:
        return 0
    return datetime.fromtimestamp(ms / 1000, tz=TZ).hour


def parse_range(from_ms: Optional[int], to_ms: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    return from_ms, to_ms


def _rt_where(from_ms: Optional[int], to_ms: Optional[int], extra: str = "") -> tuple[str, list[Any]]:
    clauses = ["status = 'Closed'"]
    params: list[Any] = []
    if from_ms:
        clauses.append("close_time_ms >= ?")
        params.append(int(from_ms))
    if to_ms:
        clauses.append("close_time_ms <= ?")
        params.append(int(to_ms))
    if extra:
        clauses.append(extra)
    return " AND ".join(clauses), params


def closed_roundtrips(
    from_ms: Optional[int] = None,
    to_ms: Optional[int] = None,
    symbol: Optional[str] = None,
    tag: Optional[str] = None,
    side: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where, params = _rt_where(from_ms, to_ms)
    if symbol:
        where += " AND symbol = ?"
        params.append(symbol)
    if tag:
        where += " AND (tags = ? OR tags LIKE ? OR tags LIKE ? OR tags LIKE ?)"
        params.extend([tag, f"{tag},%", f"%,{tag}", f"%,{tag},%"])
    if side:
        where += " AND side = ?"
        params.append(side)
    if outcome == "win":
        where += " AND net_pnl > 0"
    elif outcome == "loss":
        where += " AND net_pnl < 0"
    total_row = db.fetchone(f"SELECT COUNT(*) AS n FROM roundtrips WHERE {where}", params)
    total = int(total_row["n"]) if total_row else 0
    rows = db.fetchall(
        f"""
        SELECT * FROM roundtrips
        WHERE {where}
        ORDER BY close_time_ms DESC
        LIMIT ? OFFSET ?
        """,
        [*params, int(limit), int(offset)],
    )
    return rows, total


def fills_page(
    from_ms: Optional[int] = None,
    to_ms: Optional[int] = None,
    symbol: Optional[str] = None,
    tag: Optional[str] = None,
    side: Optional[str] = None,
    position_side: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["1=1"]
    params: list[Any] = []
    if from_ms:
        clauses.append("time_ms >= ?")
        params.append(int(from_ms))
    if to_ms:
        clauses.append("time_ms <= ?")
        params.append(int(to_ms))
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if tag:
        clauses.append("strategy_tag = ?")
        params.append(tag)
    if side:
        clauses.append("side = ?")
        params.append(side.upper())
    if position_side:
        clauses.append("position_side = ?")
        params.append(position_side.upper())
    if q:
        like = f"%{q}%"
        clauses.append(
            "(symbol LIKE ? OR IFNULL(client_order_id,'') LIKE ? OR CAST(trade_id AS TEXT) LIKE ?)"
        )
        params.extend([like, like, like])
    where = " AND ".join(clauses)
    total_row = db.fetchone(f"SELECT COUNT(*) AS n FROM fills WHERE {where}", params)
    total = int(total_row["n"]) if total_row else 0
    rows = db.fetchall(
        f"SELECT * FROM fills WHERE {where} ORDER BY time_ms DESC, trade_id DESC LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    )
    return rows, total


def income_page(
    from_ms: Optional[int] = None,
    to_ms: Optional[int] = None,
    symbol: Optional[str] = None,
    income_type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["1=1"]
    params: list[Any] = []
    if from_ms:
        clauses.append("time_ms >= ?")
        params.append(int(from_ms))
    if to_ms:
        clauses.append("time_ms <= ?")
        params.append(int(to_ms))
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if income_type:
        clauses.append("income_type = ?")
        params.append(income_type)
    if q:
        like = f"%{q}%"
        clauses.append(
            "(IFNULL(symbol,'') LIKE ? OR IFNULL(income_type,'') LIKE ? OR IFNULL(tran_id,'') LIKE ?)"
        )
        params.extend([like, like, like])
    where = " AND ".join(clauses)
    total_row = db.fetchone(f"SELECT COUNT(*) AS n FROM income WHERE {where}", params)
    total = int(total_row["n"]) if total_row else 0
    rows = db.fetchall(
        f"SELECT * FROM income WHERE {where} ORDER BY time_ms DESC, id DESC LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    )
    return rows, total


def roundtrips_page(
    from_ms: Optional[int] = None,
    to_ms: Optional[int] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    side: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["1=1"]
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if from_ms:
        clauses.append("COALESCE(close_time_ms, open_time_ms) >= ?")
        params.append(int(from_ms))
    if to_ms:
        clauses.append("COALESCE(close_time_ms, open_time_ms) <= ?")
        params.append(int(to_ms))
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if side:
        clauses.append("side = ?")
        params.append(side)
    if q:
        like = f"%{q}%"
        clauses.append("(symbol LIKE ? OR IFNULL(tags,'') LIKE ? OR IFNULL(id,'') LIKE ?)")
        params.extend([like, like, like])
    where = " AND ".join(clauses)
    total_row = db.fetchone(f"SELECT COUNT(*) AS n FROM roundtrips WHERE {where}", params)
    total = int(total_row["n"]) if total_row else 0
    rows = db.fetchall(
        f"""
        SELECT * FROM roundtrips
        WHERE {where}
        ORDER BY COALESCE(close_time_ms, open_time_ms) DESC
        LIMIT ? OFFSET ?
        """,
        [*params, int(limit), int(offset)],
    )
    return rows, total


def raw_meta() -> dict[str, Any]:
    fill_span = db.fetchone("SELECT MIN(time_ms) AS a, MAX(time_ms) AS b, COUNT(*) AS n FROM fills") or {}
    inc_n = db.fetchone("SELECT COUNT(*) AS n FROM income") or {}
    rt_n = db.fetchone("SELECT COUNT(*) AS n FROM roundtrips") or {}
    symbols = [
        r["symbol"]
        for r in db.fetchall("SELECT DISTINCT symbol FROM fills ORDER BY symbol")
        if r.get("symbol")
    ]
    return {
        "fills": int(fill_span.get("n") or 0),
        "income": int(inc_n.get("n") or 0),
        "roundtrips": int(rt_n.get("n") or 0),
        "fill_from_ms": fill_span.get("a"),
        "fill_to_ms": fill_span.get("b"),
        "symbols": symbols,
        "db_path": str(db.DB_PATH),
    }


def _today_bounds() -> tuple[int, int, str]:
    now = datetime.now(TZ)
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1, now.strftime("%Y-%m-%d")


def today_closed() -> dict[str, Any]:
    from_ms, to_ms, key = _today_bounds()
    rows = db.fetchall(
        """
        SELECT net_pnl FROM roundtrips
        WHERE status = 'Closed' AND close_time_ms >= ? AND close_time_ms <= ?
        """,
        (from_ms, to_ms),
    )
    pnl = sum(float(r["net_pnl"] or 0) for r in rows)
    return {"day": key, "pnl": pnl, "trades": len(rows)}


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(r["net_pnl"] or 0) for r in rows]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    net = sum(pnls)
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    win_rate = (len(wins) / n) if n else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss else (999.0 if gross_win else 0.0)
    expectancy = (net / n) if n else 0.0
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls[::-1]:
        equity += p
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(pnls) - len(wins) - len(losses),
        "net_pnl": net,
        "gross_pnl": sum(float(r["realized_pnl"] or 0) for r in rows),
        "fees": sum(float(r["commission"] or 0) for r in rows),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "max_drawdown": max_dd,
        "avg_hold_ms": (sum(int(r["hold_ms"] or 0) for r in rows) / n) if n else 0,
        "volume": sum(float(r.get("qty") or 0) * float(r.get("entry_price") or 0) for r in rows),
        "longs": sum(1 for r in rows if str(r.get("side")) == "Long"),
        "shorts": sum(1 for r in rows if str(r.get("side")) == "Short"),
    }


def summary(from_ms: Optional[int] = None, to_ms: Optional[int] = None) -> dict[str, Any]:
    where, params = _rt_where(from_ms, to_ms)
    rows = db.fetchall(f"SELECT * FROM roundtrips WHERE {where} ORDER BY close_time_ms ASC", params)
    stats = _metrics(rows)
    by_wd = defaultdict(lambda: {"pnl": 0.0, "n": 0, "wins": 0})
    for r in rows:
        wd = _weekday(r.get("close_time_ms"))
        by_wd[wd]["pnl"] += float(r["net_pnl"] or 0)
        by_wd[wd]["n"] += 1
        if float(r["net_pnl"] or 0) > 0:
            by_wd[wd]["wins"] += 1
    weekday = []
    today_wd = datetime.now(TZ).weekday()
    for i, name in enumerate(WEEKDAYS):
        cell = by_wd[i]
        n = cell["n"]
        weekday.append(
            {
                "dow": i,
                "name": name,
                "pnl": cell["pnl"],
                "avg_pnl": (cell["pnl"] / n) if n else 0.0,
                "trades": n,
                "win_rate": (cell["wins"] / n) if n else 0,
                "is_today": i == today_wd,
            }
        )
    curve = _equity_curve(rows, from_ms, to_ms)
    heatmap = daily_heatmap(from_ms, to_ms)
    now = datetime.now(TZ)
    today_key = now.strftime("%Y-%m-%d")
    four_start = datetime(now.year, now.month, now.day, tzinfo=TZ) - timedelta(days=now.weekday() + 21)
    four_end = four_start + timedelta(days=28)
    weeks = daily_heatmap(int(four_start.timestamp() * 1000), int(four_end.timestamp() * 1000) - 1)
    week_map = {d["day"]: d for d in weeks}
    past_4_weeks = []
    d = four_start
    while d < four_end:
        key = d.strftime("%Y-%m-%d")
        cell = week_map.get(key, {"day": key, "pnl": 0.0, "trades": 0})
        past_4_weeks.append(
            {
                "day": key,
                "dow": d.weekday(),
                "pnl": cell["pnl"],
                "trades": cell["trades"],
                "is_today": key == today_key,
                "is_future": key > today_key,
            }
        )
        d += timedelta(days=1)
    today_cell = today_closed()
    recent, _ = closed_roundtrips(limit=3)
    open_rows = db.fetchall(
        "SELECT * FROM roundtrips WHERE status='Open' ORDER BY open_time_ms DESC"
    )
    return {
        "stats": stats,
        "cashflow": _cashflow(from_ms, to_ms),
        "last_trades": recent,
        "open_roundtrips": open_rows,
        "today": {
            "day": today_key,
            "pnl": today_cell["pnl"],
            "trades": today_cell["trades"],
        },
        "weekday": weekday,
        "curve": curve,
        "heatmap": heatmap,
        "past_4_weeks": past_4_weeks,
        "open_count": len(open_rows),
        "fill_count": int((db.fetchone("SELECT COUNT(*) AS n FROM fills") or {}).get("n") or 0),
        "symbol_count": int((db.fetchone("SELECT COUNT(DISTINCT symbol) AS n FROM fills") or {}).get("n") or 0),
        "last_sync_ms": int(db.get_state("last_sync_ms") or 0),
    }


def _cashflow(from_ms: Optional[int], to_ms: Optional[int]) -> dict[str, Any]:
    clauses = ["1=1"]
    params: list[Any] = []
    if from_ms:
        clauses.append("time_ms >= ?")
        params.append(int(from_ms))
    if to_ms:
        clauses.append("time_ms <= ?")
        params.append(int(to_ms))
    where = " AND ".join(clauses)
    rows = db.fetchall(
        f"SELECT income_type, SUM(income) AS s FROM income WHERE {where} GROUP BY income_type",
        params,
    )
    by_type = {str(r["income_type"] or ""): float(r["s"] or 0) for r in rows}
    net_transfer = sum(v for k, v in by_type.items() if k in TRANSFER_TYPES)
    return {"net_transfer": net_transfer}


def time_weighted_return(
    from_ms: Optional[int],
    to_ms: Optional[int],
    end_wallet: float,
) -> dict[str, Any]:
    """Daily TWR (Shanghai). Transfers change capital only; later trading uses the new base."""
    start_cut = int(from_ms or 0)
    clauses = ["time_ms >= ?"]
    params: list[Any] = [start_cut]
    if to_ms:
        clauses.append("time_ms <= ?")
        params.append(int(to_ms))
    rows = db.fetchall(
        f"""
        SELECT time_ms, income_type, income
        FROM income
        WHERE {" AND ".join(clauses)}
        ORDER BY time_ms, id
        """,
        params,
    )
    after = db.fetchone(
        "SELECT SUM(income) AS s FROM income WHERE time_ms > ?",
        (int(to_ms) if to_ms else 2**62,),
    )
    equity_end = float(end_wallet) - float((after or {}).get("s") or 0)
    ranged = sum(float(r["income"] or 0) for r in rows)
    equity = equity_end - ranged
    start_equity = equity
    factor = 1.0
    day_factor = 1.0
    current_day = None
    days = 0
    segments = 0
    net_transfer = 0.0

    def _close_day() -> None:
        nonlocal factor, day_factor, days
        if current_day is None:
            return
        factor *= day_factor
        days += 1
        day_factor = 1.0

    for r in rows:
        day = _day(int(r["time_ms"] or 0))
        if day != current_day:
            _close_day()
            current_day = day
        amt = float(r["income"] or 0)
        if str(r["income_type"] or "") in TRANSFER_TYPES:
            net_transfer += amt
            equity += amt
            continue
        if abs(equity) > 1e-8:
            day_factor *= 1.0 + (amt / equity)
            segments += 1
        equity += amt
    _close_day()
    return {
        "twr": factor - 1.0,
        "start_equity": start_equity,
        "end_equity": equity_end,
        "net_transfer": net_transfer,
        "events": len(rows),
        "days": days,
        "segments": segments,
    }


def _equity_curve(
    rows: list[dict[str, Any]],
    from_ms: Optional[int] = None,
    to_ms: Optional[int] = None,
) -> list[dict[str, Any]]:
    equity = 0.0
    peak = 0.0
    points: list[dict[str, Any]] = []
    for r in rows:
        equity += float(r["net_pnl"] or 0)
        peak = max(peak, equity)
        t = r.get("close_time_ms")
        if not t:
            continue
        points.append(
            {
                "t": t,
                "equity": equity,
                "drawdown": equity - peak,
                "pnl": float(r["net_pnl"] or 0),
            }
        )
    now_ms = int(datetime.now(TZ).timestamp() * 1000)
    start = from_ms or (points[0]["t"] if points else None)
    end = to_ms or now_ms
    if start is None:
        return []
    out: list[dict[str, Any]] = [{"t": start, "equity": 0.0, "drawdown": 0.0, "pnl": 0.0}]
    out.extend(points)
    last_eq = points[-1]["equity"] if points else 0.0
    last_dd = points[-1]["drawdown"] if points else 0.0
    if not points or int(points[-1]["t"]) != int(end):
        out.append({"t": end, "equity": last_eq, "drawdown": last_dd, "pnl": 0.0})
    return out


def daily_heatmap(from_ms: Optional[int] = None, to_ms: Optional[int] = None) -> list[dict[str, Any]]:
    where, params = _rt_where(from_ms, to_ms)
    rows = db.fetchall(
        f"SELECT close_time_ms, net_pnl FROM roundtrips WHERE {where}",
        params,
    )
    by_day: dict[str, dict[str, Any]] = {}
    for r in rows:
        day = _day(r.get("close_time_ms"))
        if not day:
            continue
        cell = by_day.setdefault(day, {"day": day, "pnl": 0.0, "trades": 0})
        cell["pnl"] += float(r["net_pnl"] or 0)
        cell["trades"] += 1
    return sorted(by_day.values(), key=lambda x: x["day"])


def calendar(year: int, month: int) -> dict[str, Any]:
    start = datetime(year, month, 1, tzinfo=TZ)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=TZ)
    else:
        end = datetime(year, month + 1, 1, tzinfo=TZ)
    from_ms = int(start.timestamp() * 1000)
    to_ms = int(end.timestamp() * 1000) - 1
    days = {d["day"]: d for d in daily_heatmap(from_ms, to_ms)}
    notes = {
        r["day"]: r["body"]
        for r in db.fetchall(
            "SELECT day, body FROM day_notes WHERE day >= ? AND day < ?",
            (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
        )
    }
    today_key = datetime.now(TZ).strftime("%Y-%m-%d")
    cells = []
    d = start
    while d < end:
        key = d.strftime("%Y-%m-%d")
        cell = days.get(key, {"day": key, "pnl": 0.0, "trades": 0})
        cell = dict(cell)
        cell["note"] = notes.get(key, "")
        cell["is_today"] = key == today_key
        cell["is_future"] = key > today_key
        cells.append(cell)
        d += timedelta(days=1)
    month_pnl = sum(c["pnl"] for c in cells)
    month_trades = sum(c["trades"] for c in cells)
    now = datetime.now(TZ)
    return {
        "year": year,
        "month": month,
        "days": cells,
        "pnl": month_pnl,
        "trades": month_trades,
        "weekday_offset": start.weekday(),
        "today_year": now.year,
        "today_month": now.month,
        "months": months_with_closes(),
    }


def months_with_closes() -> list[dict[str, Any]]:
    rows = db.fetchall(
        "SELECT close_time_ms, net_pnl FROM roundtrips WHERE status='Closed' AND close_time_ms IS NOT NULL"
    )
    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        day = _day(r.get("close_time_ms"))
        if not day:
            continue
        key = day[:7]
        cell = buckets.setdefault(
            key,
            {"year": int(key[:4]), "month": int(key[5:7]), "trades": 0, "pnl": 0.0},
        )
        cell["trades"] += 1
        cell["pnl"] += float(r["net_pnl"] or 0)
    return [buckets[k] for k in sorted(buckets)]


def day_detail(day: str) -> dict[str, Any]:
    try:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=TZ)
    except ValueError as exc:
        raise ValueError("day 必须是 YYYY-MM-DD") from exc
    end = start + timedelta(days=1)
    from_ms = int(start.timestamp() * 1000)
    to_ms = int(end.timestamp() * 1000) - 1
    rows, _ = closed_roundtrips(from_ms, to_ms, limit=500)
    note = db.fetchone("SELECT body FROM day_notes WHERE day = ?", (day,))
    stats = _metrics(rows)
    return {"day": day, "trades": rows, "stats": stats, "note": (note or {}).get("body", "")}


def save_note(day: str, body: str) -> None:
    from time import time as now

    db.execute(
        """
        INSERT INTO day_notes(day, body, updated_ms) VALUES(?,?,?)
        ON CONFLICT(day) DO UPDATE SET body=excluded.body, updated_ms=excluded.updated_ms
        """,
        (day, body, int(now() * 1000)),
    )


def group_report(kind: str, from_ms: Optional[int] = None, to_ms: Optional[int] = None) -> list[dict[str, Any]]:
    where, params = _rt_where(from_ms, to_ms)
    rows = db.fetchall(f"SELECT * FROM roundtrips WHERE {where}", params)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if kind == "symbol":
            buckets[str(r["symbol"])].append(r)
        elif kind == "tag":
            for tag in str(r.get("tags") or "OTHER").split(","):
                buckets[tag or "OTHER"].append(r)
        elif kind == "side":
            buckets[str(r["side"] or "")].append(r)
        elif kind == "hour":
            buckets[f"{_hour(r.get('close_time_ms')):02d}:00"].append(r)
        elif kind == "weekday":
            buckets[WEEKDAYS[_weekday(r.get("close_time_ms"))]].append(r)
        elif kind == "hold":
            buckets[_hold_bucket(r.get("hold_ms"))].append(r)
        elif kind == "session":
            buckets[_session(_hour(r.get("close_time_ms")))].append(r)
        else:
            buckets["all"].append(r)
    out = []
    for name, items in buckets.items():
        m = _metrics(items)
        m["name"] = name
        out.append(m)
    out.sort(key=lambda x: x["net_pnl"], reverse=True)
    return out


def _hold_bucket(hold_ms: Optional[int]) -> str:
    if not hold_ms:
        return "未知"
    minutes = hold_ms / 60000
    if minutes < 1:
        return "< 1m"
    if minutes < 5:
        return "1–5m"
    if minutes < 15:
        return "5–15m"
    if minutes < 60:
        return "15–60m"
    if minutes < 240:
        return "1–4h"
    if minutes < 1440:
        return "4–24h"
    return "> 1d"


def _session(hour: int) -> str:
    if 0 <= hour < 9:
        return "Tokyo"
    if 7 <= hour < 16:
        return "London"
    if 13 <= hour < 22:
        return "New York"
    return "Off-session"


def analytics(from_ms: Optional[int] = None, to_ms: Optional[int] = None) -> dict[str, Any]:
    where, params = _rt_where(from_ms, to_ms)
    rows = db.fetchall(f"SELECT * FROM roundtrips WHERE {where} ORDER BY close_time_ms ASC", params)
    return {
        "stats": _metrics(rows),
        "curve": _equity_curve(rows, from_ms, to_ms),
        "hold": group_report("hold", from_ms, to_ms),
        "session": group_report("session", from_ms, to_ms),
        "weekday": group_report("weekday", from_ms, to_ms),
        "hour": group_report("hour", from_ms, to_ms),
    }


def sync_meta() -> dict[str, Any]:
    from journal.binance_sync import has_api_credentials, progress, sync_plan

    plan = sync_plan()
    return {
        "last_sync_ms": int(db.get_state("last_sync_ms") or 0),
        "last_sync_ok": db.get_state("last_sync_ok", "1") == "1",
        "last_sync_error": db.get_state("last_sync_error"),
        "last_sync_mode": db.get_state("last_sync_mode"),
        "fills": int((db.fetchone("SELECT COUNT(*) AS n FROM fills") or {}).get("n") or 0),
        "roundtrips": int((db.fetchone("SELECT COUNT(*) AS n FROM roundtrips") or {}).get("n") or 0),
        "symbol_count": int((db.fetchone("SELECT COUNT(DISTINCT symbol) AS n FROM fills") or {}).get("n") or 0),
        "db_path": str(db.DB_PATH),
        "has_api_key": has_api_credentials(),
        "next_mode": plan["mode"],
        "universe_scan_done": plan["universe_scan_done"],
        "local_symbols": plan["local_symbols"][:30],
        "progress": dict(progress),
    }
