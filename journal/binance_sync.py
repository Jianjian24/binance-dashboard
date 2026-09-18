from __future__ import annotations

import csv
import gzip
import io
import os
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.request import ProxyHandler, Request, build_opener

from journal import db
from journal.match import match_roundtrips
from journal.tags import tag_from_client_order_id

INCOME_WINDOW_DAYS = 7
INCOME_OVERLAP_MS = 24 * 3600 * 1000
ORDER_WINDOW_DAYS = 7
CID_LOOKBACK_DAYS = 90
FUTURES_LAUNCH_MS = 1567900800000  # 2019-09-08 UTC

progress: dict[str, Any] = {
    "phase": "",
    "mode": "",
    "symbol": "",
    "index": 0,
    "total": 0,
    "fills_new": 0,
    "message": "",
}


def _set_progress(**kwargs: Any) -> None:
    progress.update(kwargs)


def _proxy_url() -> Optional[str]:
    """HTTP proxy only when PROXY_TYPE=CLASH. No dependency on any other project."""
    proxy_type = os.getenv("PROXY_TYPE", "NONE").upper()
    if proxy_type != "CLASH":
        return None
    return os.getenv("CLASH_HTTP_PROXY") or os.getenv("CLASH_HTTPS_PROXY") or "http://127.0.0.1:7890"


def api_credentials() -> tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_API_KEY_TRADE")
    secret = os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_API_SECRET_TRADE")
    return api_key, secret


def has_api_credentials() -> bool:
    api_key, secret = api_credentials()
    return bool(api_key and secret)


def make_client():
    api_key, secret = api_credentials()
    if not api_key or not secret:
        raise RuntimeError("缺少 BINANCE_API_KEY / BINANCE_API_SECRET")
    from binance.client import Client

    proxy = _proxy_url()
    # (connect, read)：避免代理半开连接时读超时不生效、线程一直挂死
    kwargs: dict[str, Any] = {"requests_params": {"timeout": (5, 20)}}
    if proxy:
        kwargs["requests_params"]["proxies"] = {"http": proxy, "https": proxy}
    client = Client(api_key, secret, **kwargs)
    try:
        server_time = int((_call(client, "get_server_time") or {}).get("serverTime") or 0)
        if server_time:
            client.timestamp_offset = server_time - int(time.time() * 1000)
    except Exception:
        client.timestamp_offset = -1500
    return client


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _upsert_fills(rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = []
    for t in rows:
        cid = str(t.get("clientOrderId") or t.get("client_order_id") or "")
        payload.append(
            (
                int(t["id"]),
                int(t.get("orderId") or 0),
                cid,
                str(t["symbol"]),
                str(t.get("side") or ""),
                str(t.get("positionSide") or "BOTH"),
                _parse_num(t.get("price") or 0),
                _parse_num(t.get("qty") or 0),
                _parse_num(t.get("quoteQty") or 0),
                _parse_num(t.get("realizedPnl") or 0),
                _parse_num(t.get("commission") or 0),
                str(t.get("commissionAsset") or ""),
                1 if t.get("maker") else 0,
                int(t["time"]),
                tag_from_client_order_id(cid),
            )
        )
    return db.executemany(
        """
        INSERT INTO fills(
            trade_id, order_id, client_order_id, symbol, side, position_side,
            price, qty, quote_qty, realized_pnl, commission, commission_asset,
            maker, time_ms, strategy_tag
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(trade_id) DO UPDATE SET
            realized_pnl=excluded.realized_pnl,
            commission=excluded.commission,
            client_order_id=CASE
                WHEN excluded.client_order_id != '' THEN excluded.client_order_id
                ELSE fills.client_order_id
            END,
            strategy_tag=CASE
                WHEN excluded.client_order_id != '' THEN excluded.strategy_tag
                WHEN IFNULL(fills.client_order_id, '') != '' THEN fills.strategy_tag
                ELSE excluded.strategy_tag
            END
        """,
        payload,
    )


def _upsert_income(rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = []
    for r in rows:
        payload.append(
            (
                int(r.get("time") or 0),
                str(r.get("symbol") or ""),
                str(r.get("incomeType") or ""),
                float(r.get("income") or 0),
                str(r.get("asset") or ""),
                str(r.get("tranId") or r.get("tradeId") or ""),
            )
        )
    return db.executemany(
        """
        INSERT INTO income(time_ms, symbol, income_type, income, asset, tran_id)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(tran_id, income_type, time_ms) DO NOTHING
        """,
        payload,
    )


def _rebuild_roundtrips() -> int:
    fills = db.fetchall(
        """
        SELECT trade_id, order_id, client_order_id, symbol, side, position_side,
               price, qty, realized_pnl, commission, time_ms, strategy_tag
        FROM fills ORDER BY symbol, time_ms, trade_id
        """
    )
    trips = match_roundtrips(fills)
    conn = db.get_conn()
    conn.execute("DELETE FROM roundtrips")
    conn.executemany(
        """
        INSERT INTO roundtrips(
            id, symbol, side, open_time_ms, close_time_ms, qty, entry_price,
            exit_price, realized_pnl, commission, net_pnl, hold_ms, status, tags, fill_ids
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                t["id"],
                t["symbol"],
                t["side"],
                t["open_time_ms"],
                t["close_time_ms"],
                t["qty"],
                t["entry_price"],
                t["exit_price"],
                t["realized_pnl"],
                t["commission"],
                t["net_pnl"],
                t["hold_ms"],
                t["status"],
                t["tags"],
                t["fill_ids"],
            )
            for t in trips
        ],
    )
    conn.commit()
    return len(trips)


def rebuild_roundtrips() -> int:
    return _rebuild_roundtrips()


def _call(client, method: str, **kwargs: Any):
    fn = getattr(client, method)
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            return fn(**kwargs)
        except Exception as e:
            last_err = e
            msg = str(e)
            if "-1021" in msg:
                try:
                    server_time = int(client.get_server_time()["serverTime"])
                    client.timestamp_offset = server_time - int(time.time() * 1000)
                except Exception:
                    client.timestamp_offset = int(getattr(client, "timestamp_offset", 0) or 0) - 1500
                time.sleep(0.2)
                continue
            if "-1003" in msg or "Too many" in msg or "timed out" in msg.lower():
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
    raise last_err or RuntimeError(method)


def _fetch_income(client, start_ms: int, end_ms: int) -> list[dict]:
    import threading

    out: list[dict] = []
    cursor = start_ms
    span = max(end_ms - start_ms, 1)
    started = time.time()
    budget_s = 20.0

    def _one_window(win_start: int, win_end: int) -> list[dict]:
        box: dict[str, Any] = {"batch": None, "err": None}

        def run() -> None:
            try:
                box["batch"] = (
                    client.futures_income_history(
                        startTime=win_start,
                        endTime=win_end,
                        limit=1000,
                    )
                    or []
                )
            except Exception as e:  # noqa: BLE001
                box["err"] = e

        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(8)
        if th.is_alive():
            raise TimeoutError("income window hung")
        if box["err"] is not None:
            raise box["err"]
        return list(box["batch"] or [])

    while cursor < end_ms:
        if time.time() - started > budget_s:
            _set_progress(
                phase="income",
                message=f"资金流水超时，已拉 {len(out)} 条，继续后续同步",
            )
            break
        window_end = min(end_ms, cursor + INCOME_WINDOW_DAYS * 86400 * 1000)
        pct = int(min(99, max(0, (cursor - start_ms) * 100 / span)))
        _set_progress(
            phase="income",
            message=f"拉取资金流水以发现品种 {pct}% · {len(out)} 条",
        )
        try:
            batch = _one_window(cursor, window_end)
        except Exception:
            cursor = window_end + 1
            time.sleep(0.1)
            continue
        out.extend(batch)
        if len(batch) >= 1000:
            last = max(int(x.get("time") or cursor) for x in batch)
            cursor = (last + 1) if last > cursor else (window_end + 1)
        else:
            cursor = window_end + 1
        time.sleep(0.05)
    return out


def _fetch_symbol_trades(client, symbol: str, after_id: Optional[int]) -> list[dict]:
    """Paginate userTrades by fromId. after_id=None means from the first trade."""
    out: list[dict] = []
    cursor = (int(after_id) + 1) if after_id else 1
    while True:
        batch = _call(
            client,
            "futures_account_trades",
            symbol=symbol,
            fromId=cursor,
            limit=1000,
        ) or []
        if not batch:
            break
        batch = [t for t in batch if int(t["id"]) >= cursor]
        if after_id:
            batch = [t for t in batch if int(t["id"]) > int(after_id)]
        if not batch:
            break
        out.extend(batch)
        cursor = max(int(t["id"]) for t in batch) + 1
        if len(batch) < 1000:
            break
        time.sleep(0.08)
    return out


def _order_cid(order: dict) -> str:
    return str(order.get("clientOrderId") or order.get("origClientOrderId") or "").strip()


def _fetch_symbol_orders(client, symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """allOrders 每次最多 7 天；不带 orderId 时返回窗口内最近 1000 笔，需向前翻页。"""
    out: list[dict] = []
    cursor = int(start_ms)
    limit_ms = ORDER_WINDOW_DAYS * 86400 * 1000 - 1000
    while cursor <= end_ms:
        window_end = min(int(end_ms), cursor + limit_ms)
        chunk_end = window_end
        while chunk_end >= cursor:
            batch = _call(
                client,
                "futures_get_all_orders",
                symbol=symbol,
                startTime=cursor,
                endTime=chunk_end,
                limit=1000,
            ) or []
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 1000:
                break
            oldest = min(int(o.get("time") or o.get("updateTime") or chunk_end) for o in batch)
            if oldest <= cursor:
                break
            chunk_end = oldest - 1
            time.sleep(0.08)
        cursor = window_end + 1
        time.sleep(0.08)
    return out


def _apply_order_cids(orders: list[dict]) -> int:
    seen: dict[tuple[str, int], str] = {}
    for order in orders:
        cid = _order_cid(order)
        symbol = str(order.get("symbol") or "")
        oid = int(order.get("orderId") or 0)
        if not cid or not symbol or not oid:
            continue
        seen[(symbol, oid)] = cid
    if not seen:
        return 0
    payload = [
        (cid, tag_from_client_order_id(cid), symbol, oid)
        for (symbol, oid), cid in seen.items()
    ]
    return db.executemany(
        """
        UPDATE fills
        SET client_order_id = ?, strategy_tag = ?
        WHERE symbol = ? AND order_id = ? AND IFNULL(client_order_id, '') = ''
        """,
        payload,
    )


def backfill_client_order_ids(client=None, lookback_days: int = CID_LOOKBACK_DAYS) -> dict[str, Any]:
    """userTrades / 归档 CSV 都没有 clientOrderId，用 allOrders 补 GRID/MM 等前缀。"""
    lookback_days = min(int(lookback_days), CID_LOOKBACK_DAYS)
    c = client or make_client()
    now_ms = int(time.time() * 1000)
    start_floor = now_ms - lookback_days * 86400 * 1000
    spans = db.fetchall(
        """
        SELECT symbol, MIN(time_ms) AS a, MAX(time_ms) AS b
        FROM fills
        WHERE IFNULL(client_order_id, '') = '' AND time_ms >= ?
        GROUP BY symbol
        """,
        (start_floor,),
    )
    tagged = 0
    scanned = 0
    errors: list[str] = []
    total = len(spans)
    for i, row in enumerate(spans, start=1):
        symbol = str(row["symbol"])
        if not re.fullmatch(r"[A-Z0-9]+USDT", symbol):
            continue
        a = max(int(row["a"] or start_floor), start_floor)
        b = min(int(row["b"] or now_ms), now_ms)
        _set_progress(
            phase="tags",
            symbol=symbol,
            index=i,
            total=total,
            message=f"回填订单 CID {symbol}  {i}/{total}",
        )
        try:
            orders = _fetch_symbol_orders(c, symbol, a, b)
            scanned += len(orders)
            tagged += _apply_order_cids(orders)
        except Exception as e:
            errors.append(f"{symbol}: {e}")
    return {"symbols": total, "orders": scanned, "fills_tagged": tagged, "errors": errors}


def _http_get_bytes(url: str) -> bytes:
    proxy = _proxy_url()
    opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}) if proxy else ProxyHandler({}))
    req = Request(url, headers={"User-Agent": "ledger-journal"})
    with opener.open(req, timeout=180) as resp:
        return resp.read()


_NUM_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NUM_ASSET_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z0-9]+)?")


def _parse_num(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip().replace(",", "")
    match = _NUM_RE.match(text)
    return float(match.group(0)) if match else 0.0


def _parse_num_asset(val: Any) -> tuple[float, str]:
    if val is None or val == "":
        return 0.0, ""
    text = str(val).strip().replace(",", "")
    match = _NUM_ASSET_RE.match(text)
    if not match:
        return 0.0, ""
    return float(match.group(1)), (match.group(2) or "")


def _parse_trade_time(val: Any) -> int:
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        v = int(val)
        return v if v > 10_000_000_000 else v * 1000
    text = str(val).strip()
    if text.isdigit():
        v = int(text)
        return v if v > 10_000_000_000 else v * 1000
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(text.replace("Z", "")[:26], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return 0


def _norm_header(name: str) -> str:
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


def _row_get(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and row[key] not in ("", None):
            return str(row[key])
        nk = _norm_header(key)
        for rk, rv in row.items():
            if rv in ("", None):
                continue
            rn = _norm_header(rk)
            if rn == nk:
                return str(rv)
            if nk in ("time", "timestamp") and ("time" in rn or rn in ("datetime", "date")):
                return str(rv)
    return ""


def _csv_rows_to_trades(text: str) -> list[dict]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    out: list[dict] = []
    for raw in reader:
        row = {str(k or "").strip(): ("" if v is None else str(v).strip()) for k, v in raw.items()}
        trade_id = _row_get(row, "id", "tradeId", "trade id", "成交ID")
        symbol = _row_get(row, "symbol", "合约", "交易对")
        if not trade_id or not symbol:
            continue
        maker_raw = _row_get(row, "maker", "isMaker", "是否挂单").lower()
        fee_num, fee_from_val = _parse_num_asset(_row_get(row, "commission", "fee", "手续费"))
        fee_asset = _row_get(row, "commissionAsset", "feeAsset", "fee asset", "手续费资产") or fee_from_val
        out.append(
            {
                "id": int(_parse_num(trade_id)),
                "orderId": int(_parse_num(_row_get(row, "orderId", "order id", "订单ID"))),
                "clientOrderId": _row_get(row, "clientOrderId", "client order id", "客户订单ID"),
                "symbol": symbol.replace("/", ""),
                "side": _row_get(row, "side", "方向").upper() or "BUY",
                "positionSide": (_row_get(row, "positionSide", "position side", "持仓方向") or "BOTH").upper(),
                "price": _parse_num(_row_get(row, "price", "成交价")),
                "qty": _parse_num(_row_get(row, "qty", "quantity", "baseQty", "成交量")),
                "quoteQty": _parse_num(_row_get(row, "quoteQty", "amount", "成交额")),
                "realizedPnl": _parse_num(_row_get(row, "realizedPnl", "realized profit", "已实现盈亏")),
                "commission": fee_num,
                "commissionAsset": fee_asset,
                "maker": maker_raw in ("true", "1", "yes", "maker"),
                "time": _parse_trade_time(
                    _row_get(row, "time", "timestamp", "时间", "Time(UTC)", "datetime")
                ),
            }
        )
    return out


def _bytes_to_trades(blob: bytes) -> list[dict]:
    if blob[:2] == b"PK":
        trades: list[dict] = []
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                trades.extend(_bytes_to_trades(zf.read(name)))
        return trades
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return _csv_rows_to_trades(blob.decode("utf-8-sig", errors="replace"))


def import_trade_archive(start_ms: int, end_ms: int, client=None) -> dict[str, Any]:
    """Pull USDT-M fills older than the 3-month userTrades window via Binance async download."""
    c = client or make_client()
    _set_progress(phase="archive", message="申请成交历史归档（含 3 个月以前）")
    req = _call(c, "futures_v1_get_trade_asyn", startTime=int(start_ms), endTime=int(end_ms))
    download_id = str((req or {}).get("downloadId") or "")
    if not download_id:
        raise RuntimeError(f"归档申请失败: {req}")
    url = ""
    for i in range(90):
        time.sleep(2)
        st = _call(c, "futures_v1_get_trade_asyn_id", downloadId=download_id) or {}
        status = str(st.get("status") or "").lower()
        _set_progress(phase="archive", message=f"归档 {status or 'processing'} {i+1}/90")
        if status in ("completed", "complete"):
            url = str(st.get("url") or "")
            break
        if status in ("failed", "expired"):
            raise RuntimeError(f"归档失败: {st}")
    if not url:
        raise RuntimeError("归档超时，请稍后 Shift+同步重试")
    _set_progress(phase="archive", message="下载并导入归档成交")
    blob = _http_get_bytes(url)
    archive_path = db.DATA_DIR / "last_archive.bin"
    archive_path.write_bytes(blob)
    trades = _bytes_to_trades(blob)
    n = _upsert_fills(trades)
    db.set_state("archive_from_ms", str(start_ms))
    db.set_state("archive_to_ms", str(end_ms))
    db.set_state("archive_download_id", download_id)
    return {"download_id": download_id, "trades": len(trades), "upserted": n}


def _last_trade_id(symbol: str) -> Optional[int]:
    row = db.fetchone("SELECT MAX(trade_id) AS m FROM fills WHERE symbol = ?", (symbol,))
    if row and row["m"]:
        return int(row["m"])
    return None


def _local_symbols() -> set[str]:
    return {
        str(row["symbol"])
        for row in db.fetchall("SELECT DISTINCT symbol FROM fills")
        if row["symbol"]
    }


def _position_symbols(client) -> set[str]:
    found: set[str] = set()
    try:
        for p in _call(client, "futures_position_information") or []:
            amt = float(p.get("positionAmt") or 0)
            if abs(amt) > 0 and p.get("symbol"):
                found.add(str(p["symbol"]))
    except Exception:
        pass
    return found


def _usdt_perp_symbols(client) -> list[str]:
    info = _call(client, "futures_exchange_info") or {}
    out: list[str] = []
    for s in info.get("symbols") or []:
        if str(s.get("quoteAsset") or "") != "USDT":
            continue
        ctype = str(s.get("contractType") or "")
        if ctype and ctype not in ("PERPETUAL",):
            continue
        if s.get("symbol"):
            out.append(str(s["symbol"]))
    return sorted(set(out))


def sync_plan(force_full: bool = False) -> dict[str, Any]:
    scanned = db.get_state("universe_scan_done") == "1"
    fills = int((db.fetchone("SELECT COUNT(*) AS n FROM fills") or {}).get("n") or 0)
    symbols = sorted(_local_symbols())
    mode = "full" if (force_full or not scanned) else "incremental"
    return {
        "mode": mode,
        "universe_scan_done": scanned,
        "fills": fills,
        "local_symbols": symbols,
        "local_symbol_count": len(symbols),
    }


def _income_symbols(client, start_ms: int, end_ms: int) -> set[str]:
    _set_progress(phase="income", message="拉取资金流水以发现品种")
    income = _fetch_income(client, start_ms, end_ms)
    _upsert_income(income)
    db.set_state("last_income_end_ms", str(end_ms))
    return {str(r.get("symbol")) for r in income if r.get("symbol")}


def _parse_position_rows(rows: list[dict] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in rows or []:
        amt = float(p.get("positionAmt") or 0)
        if abs(amt) < 1e-12:
            continue
        upnl = float(p.get("unRealizedProfit") or p.get("unrealizedProfit") or 0)
        out.append(
            {
                "symbol": p.get("symbol"),
                "amount": amt,
                "entry": float(p.get("entryPrice") or 0),
                "unrealized": upnl,
                "leverage": p.get("leverage"),
                "side": p.get("positionSide") or ("SHORT" if amt < 0 else "LONG"),
                "source": "live",
            }
        )
    return out


def _valid_futures_symbol(symbol: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,20}USDT", str(symbol or "")))


def _live_positions(client) -> tuple[list[dict[str, Any]], Optional[str]]:
    last_err: Optional[str] = None
    try:
        parsed = _parse_position_rows(client.futures_position_information())
        return parsed, None
    except Exception as e:
        last_err = str(e)
    symbols = {
        str(r["symbol"])
        for r in db.fetchall("SELECT DISTINCT symbol FROM roundtrips WHERE status='Open'")
        if r.get("symbol")
    }
    if not symbols:
        symbols = {s for s in _local_symbols() if _valid_futures_symbol(s)}
    found: list[dict[str, Any]] = []
    for symbol in sorted(s for s in symbols if _valid_futures_symbol(s)):
        try:
            found.extend(_parse_position_rows(client.futures_position_information(symbol=symbol)))
        except Exception as e:
            last_err = str(e)
    return found, last_err


def _local_open_positions() -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT symbol, side, qty, entry_price, open_time_ms
        FROM roundtrips WHERE status='Open' ORDER BY open_time_ms DESC
        """
    )
    out = []
    for r in rows:
        qty = float(r["qty"] or 0)
        if qty <= 1e-12:
            continue
        short = str(r.get("side") or "") == "Short"
        out.append(
            {
                "symbol": r["symbol"],
                "amount": -qty if short else qty,
                "entry": float(r["entry_price"] or 0),
                "unrealized": None,
                "leverage": None,
                "side": "SHORT" if short else "LONG",
                "source": "local",
            }
        )
    return out


def account_snapshot(client=None) -> dict[str, Any]:
    try:
        c = client or make_client()
    except Exception as e:
        local = _local_open_positions()
        return {"ok": False, "error": str(e), "positions": local, "unrealized": 0.0, "equity": None}
    wallet = 0.0
    available = 0.0
    try:
        bals = c.futures_account_balance() or []
        for b in bals:
            if str(b.get("asset")) == "USDT":
                wallet = float(b.get("balance") or 0)
                available = float(b.get("availableBalance") or 0)
                break
    except Exception as e:
        local = _local_open_positions()
        return {"ok": False, "error": str(e), "positions": local, "unrealized": 0.0, "equity": None}
    positions, pos_err = _live_positions(c)
    if not positions:
        positions = _local_open_positions()
    unrealized = sum(float(p.get("unrealized") or 0) for p in positions if p.get("unrealized") is not None)
    return {
        "ok": True,
        "wallet": wallet,
        "available": available,
        "unrealized": unrealized,
        "equity": wallet + unrealized,
        "positions": positions,
        "position_error": pos_err,
    }


def sync(force_full: bool = False, lookback_days: int = 0) -> dict[str, Any]:
    """Load local DB first, then full-scan all USDT-M symbols or increment from last tradeId."""
    del lookback_days  # kept for older callers; full history uses fromId, not a day window
    started = time.time()
    plan = sync_plan(force_full=force_full)
    mode = plan["mode"]
    _set_progress(
        phase="start",
        mode=mode,
        symbol="",
        index=0,
        total=0,
        fills_new=0,
        message="已加载本地库，正在连接币安",
    )
    client = make_client()
    now = datetime.now(timezone.utc)
    end_ms = _ms(now)
    local = _local_symbols()
    positions = _position_symbols(client)

    if mode == "full":
        _set_progress(phase="universe", message="枚举全部 U 本位永续")
        universe = set(_usdt_perp_symbols(client))
        # 全量模式用 exchangeInfo 枚举全部 U 本位永续即可，不再拉资金流水
        # （income 接口在部分代理环境下会挂死，导致页面一直停在「拉取资金流水」）
        symbols = sorted(universe | local | positions)
    else:
        last_income = int(db.get_state("last_income_end_ms") or 0)
        income_start = (last_income - INCOME_OVERLAP_MS) if last_income else (end_ms - 14 * 86400 * 1000)
        extra: set[str] = set()
        try:
            extra = _income_symbols(client, income_start, end_ms)
        except Exception:
            pass
        symbols = sorted(local | positions | extra)

    fills_n = 0
    hit_symbols = 0
    per_symbol: list[dict[str, Any]] = []
    errors: list[str] = []
    total = len(symbols)
    _set_progress(phase="trades", mode=mode, total=total, message=f"{mode} · {total} 个品种")

    for i, symbol in enumerate(symbols, start=1):
        last_id = _last_trade_id(symbol)
        _set_progress(
            phase="trades",
            symbol=symbol,
            index=i,
            total=total,
            fills_new=fills_n,
            message=f"{symbol}  {i}/{total}" + (f"  from #{last_id}" if last_id else "  全量"),
        )
        try:
            rows = _fetch_symbol_trades(client, symbol, after_id=last_id)
            n = _upsert_fills(rows)
            fills_n += n
            if rows or last_id:
                hit_symbols += 1
            if rows:
                per_symbol.append({"symbol": symbol, "new": len(rows), "from_id": last_id})
        except Exception as e:
            errors.append(f"{symbol}: {e}")
        time.sleep(0.1)

    if mode == "full":
        try:
            arch_start = end_ms - 365 * 86400 * 1000
            _set_progress(phase="archive", message="拉取 1 年成交归档（含 3 个月前）")
            arch = import_trade_archive(arch_start, end_ms, client)
            fills_n += int(arch.get("upserted") or 0)
            per_symbol.append({"symbol": "_archive", "new": arch.get("upserted"), "from_id": None})
        except Exception as e:
            errors.append(f"archive: {e}")

    try:
        _set_progress(phase="tags", message="用订单历史回填 GRID/MM 标签")
        cid_stats = backfill_client_order_ids(client)
        if cid_stats.get("errors"):
            errors.extend(f"tags {e}" for e in cid_stats["errors"][:8])
        per_symbol.append(
            {
                "symbol": "_tags",
                "new": cid_stats.get("fills_tagged"),
                "from_id": cid_stats.get("orders"),
            }
        )
    except Exception as e:
        errors.append(f"tags: {e}")

    _set_progress(phase="rebuild", message="重建开平仓轮次", fills_new=fills_n)
    trips = _rebuild_roundtrips()
    if mode == "full" and not errors:
        db.set_state("universe_scan_done", "1")
    elif mode == "full" and hit_symbols > 0:
        db.set_state("universe_scan_done", "1")
    db.set_state("last_sync_ms", str(end_ms))
    db.set_state("last_sync_mode", mode)
    db.set_state("last_sync_ok", "0" if errors and fills_n == 0 else "1")
    db.set_state("last_sync_error", "; ".join(errors[:8]))
    _set_progress(phase="done", message="完成", fills_new=fills_n, index=total, total=total)
    return {
        "ok": not errors or fills_n > 0,
        "mode": mode,
        "symbols": len(symbols),
        "symbols_with_trades": int(
            (db.fetchone("SELECT COUNT(DISTINCT symbol) AS n FROM fills") or {}).get("n") or 0
        ),
        "fills_upserted": fills_n,
        "roundtrips": trips,
        "elapsed_sec": round(time.time() - started, 2),
        "per_symbol": per_symbol[:80],
        "errors": errors,
        "last_sync_ms": end_ms,
    }
