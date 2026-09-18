"""Local TradeStream-style journal. Binds 127.0.0.1 only.

Usage (from the repo root):
    python -m journal.server
    python -m journal.server --port 8765
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from journal import db, queries
from journal.binance_sync import (
    account_snapshot,
    progress as sync_progress,
    rebuild_roundtrips,
    sync as run_sync,
    sync_plan,
)

HOST = "127.0.0.1"
PORT = 8765
_sync_lock = threading.Lock()
_sync_job: dict[str, Any] = {"running": False, "result": None, "error": None}


def _json(handler: SimpleHTTPRequestHandler, code: int, payload: Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _int(qs: dict[str, list[str]], key: str) -> Optional[int]:
    vals = qs.get(key)
    if not vals or vals[0] == "":
        return None
    return int(float(vals[0]))


def _float(qs: dict[str, list[str]], key: str) -> Optional[float]:
    vals = qs.get(key)
    if not vals or vals[0] == "":
        return None
    return float(vals[0])


def _str(qs: dict[str, list[str]], key: str) -> Optional[str]:
    vals = qs.get(key)
    if not vals or vals[0] == "":
        return None
    return vals[0]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        if self.path.startswith("/api/"):
            return
        super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                _json(self, 200, {"ok": True, "bind": f"{HOST}:{PORT}"})
                return
            if path == "/api/meta":
                _json(self, 200, queries.sync_meta())
                return
            if path == "/api/account":
                _json(self, 200, account_snapshot())
                return
            if path == "/api/summary":
                _json(self, 200, queries.summary(_int(qs, "from"), _int(qs, "to")))
                return
            if path == "/api/twr":
                wallet = _float(qs, "wallet")
                if wallet is None:
                    _json(self, 400, {"error": "wallet required"})
                    return
                _json(
                    self,
                    200,
                    queries.time_weighted_return(_int(qs, "from"), _int(qs, "to"), wallet),
                )
                return
            if path == "/api/analytics":
                _json(self, 200, queries.analytics(_int(qs, "from"), _int(qs, "to")))
                return
            if path == "/api/report":
                kind = _str(qs, "kind") or "symbol"
                _json(self, 200, queries.group_report(kind, _int(qs, "from"), _int(qs, "to")))
                return
            if path == "/api/roundtrips":
                rows, total = queries.closed_roundtrips(
                    from_ms=_int(qs, "from"),
                    to_ms=_int(qs, "to"),
                    symbol=_str(qs, "symbol"),
                    tag=_str(qs, "tag"),
                    side=_str(qs, "side"),
                    outcome=_str(qs, "outcome"),
                    limit=_int(qs, "limit") or 200,
                    offset=_int(qs, "offset") or 0,
                )
                _json(self, 200, {"rows": rows, "total": total})
                return
            if path == "/api/fills":
                rows, total = queries.fills_page(
                    from_ms=_int(qs, "from"),
                    to_ms=_int(qs, "to"),
                    symbol=_str(qs, "symbol"),
                    tag=_str(qs, "tag"),
                    side=_str(qs, "side"),
                    position_side=_str(qs, "position_side"),
                    q=_str(qs, "q"),
                    limit=_int(qs, "limit") or 200,
                    offset=_int(qs, "offset") or 0,
                )
                _json(self, 200, {"rows": rows, "total": total})
                return
            if path == "/api/income":
                rows, total = queries.income_page(
                    from_ms=_int(qs, "from"),
                    to_ms=_int(qs, "to"),
                    symbol=_str(qs, "symbol"),
                    income_type=_str(qs, "income_type"),
                    q=_str(qs, "q"),
                    limit=_int(qs, "limit") or 200,
                    offset=_int(qs, "offset") or 0,
                )
                _json(self, 200, {"rows": rows, "total": total})
                return
            if path == "/api/raw":
                kind = _str(qs, "kind") or "fills"
                limit = _int(qs, "limit") or 100
                offset = _int(qs, "offset") or 0
                if kind == "income":
                    rows, total = queries.income_page(
                        from_ms=_int(qs, "from"),
                        to_ms=_int(qs, "to"),
                        symbol=_str(qs, "symbol"),
                        q=_str(qs, "q"),
                        limit=limit,
                        offset=offset,
                    )
                elif kind == "roundtrips":
                    rows, total = queries.roundtrips_page(
                        from_ms=_int(qs, "from"),
                        to_ms=_int(qs, "to"),
                        symbol=_str(qs, "symbol"),
                        status=_str(qs, "status"),
                        side=_str(qs, "side"),
                        q=_str(qs, "q"),
                        limit=limit,
                        offset=offset,
                    )
                else:
                    rows, total = queries.fills_page(
                        from_ms=_int(qs, "from"),
                        to_ms=_int(qs, "to"),
                        symbol=_str(qs, "symbol"),
                        side=_str(qs, "side"),
                        position_side=_str(qs, "position_side"),
                        q=_str(qs, "q"),
                        limit=limit,
                        offset=offset,
                    )
                _json(self, 200, {"kind": kind, "rows": rows, "total": total, "limit": limit, "offset": offset})
                return
            if path == "/api/raw/meta":
                _json(self, 200, queries.raw_meta())
                return
            if path == "/api/calendar":
                now = datetime.now(queries.TZ)
                year = _int(qs, "year") or now.year
                month = _int(qs, "month") or now.month
                _json(self, 200, queries.calendar(year, month))
                return
            if path == "/api/day":
                day = _str(qs, "day")
                if not day:
                    _json(self, 400, {"error": "day required"})
                    return
                try:
                    _json(self, 200, queries.day_detail(day))
                except ValueError as e:
                    _json(self, 400, {"error": str(e)})
                return
            if path == "/api/sync":
                payload = dict(_sync_job)
                payload["progress"] = dict(sync_progress)
                payload["plan"] = sync_plan()
                _json(self, 200, payload)
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path == "/" or not path.startswith("/api/"):
                self._serve_static(path)
                return
            _json(self, 404, {"error": "not found"})
        except Exception as e:
            _json(self, 500, {"error": str(e), "trace": traceback.format_exc()})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/sync":
                body = _body(self)
                self._start_sync(bool(body.get("force_full")))
                payload = dict(_sync_job)
                payload["progress"] = dict(sync_progress)
                _json(self, 200, payload)
                return
            if path == "/api/rebuild":
                n = rebuild_roundtrips()
                _json(self, 200, {"ok": True, "roundtrips": n})
                return
            if path == "/api/note":
                body = _body(self)
                queries.save_note(str(body.get("day") or ""), str(body.get("body") or ""))
                _json(self, 200, {"ok": True})
                return
            _json(self, 404, {"error": "not found"})
        except Exception as e:
            _json(self, 500, {"error": str(e)})

    def _start_sync(self, force_full: bool) -> None:
        with _sync_lock:
            if _sync_job["running"]:
                return
            _sync_job.update({"running": True, "result": None, "error": None, "progress": {}})

        def worker() -> None:
            try:
                result = run_sync(force_full=force_full)
                with _sync_lock:
                    _sync_job.update({"running": False, "result": result, "error": None})
            except Exception as e:
                with _sync_lock:
                    _sync_job.update({"running": False, "result": None, "error": str(e)})

        threading.Thread(target=worker, daemon=True).start()

    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/")
        static_root = STATIC.resolve()
        if rel == "" or rel == "index.html":
            file_path = STATIC / "index.html"
        else:
            file_path = (STATIC / rel).resolve()
            if not file_path.is_relative_to(static_root):
                self.send_error(403)
                return
        if not file_path.is_file():
            name = Path(rel).name
            if "." in name:
                self.send_error(404)
                return
            file_path = STATIC / "index.html"
        data = file_path.read_bytes()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(file_path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local private trading journal")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("拒绝绑定公网地址。只允许 127.0.0.1 / localhost / ::1")
        sys.exit(2)
    db.get_conn()
    rebuilt = rebuild_roundtrips()
    plan = sync_plan()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Ledger 看板: http://{args.host}:{args.port}", flush=True)
    print(f"SQLite: {db.DB_PATH}", flush=True)
    print(
        f"本地已加载 {plan['fills']} 笔成交 / {plan['local_symbol_count']} 个品种；"
        f"roundtrips {rebuilt}；下次同步: {plan['mode']}",
        flush=True,
    )
    print("仅本机可访问。需要代理时设置 PROXY_TYPE=CLASH。同步由页面手动触发。", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
