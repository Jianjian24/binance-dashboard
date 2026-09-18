const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const TITLES = {
  home: "Home",
  dashboard: "Dashboard",
  analytics: "Analytics",
  calendar: "Calendar",
  journal: "Journal",
  rawdata: "Raw data",
  trades: "Trades",
  "reports/tags": "Tags report",
  "reports/symbols": "Symbols report",
  "reports/pnl": "PnL curve report",
};
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const RANGE_LABELS = {
  all: "All time",
  ytd: "Year to date",
  "90d": "Last 90 days",
  "30d": "Last 30 days",
  "7d": "Last 7 days",
  today: "Today",
  custom: "Custom range",
};
const PRIVACY_KEY = "ledger-privacy";
const PRIVACY_SALT_KEY = "ledger-privacy-salt";
function readPrivacy() {
  try {
    return localStorage.getItem(PRIVACY_KEY) === "1";
  } catch {
    return false;
  }
}
function newPrivacySalt() {
  const c = globalThis.crypto;
  if (c && c.getRandomValues) {
    const buf = new Uint32Array(2);
    c.getRandomValues(buf);
    return [...buf].map((n) => n.toString(36)).join("");
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
}
function readPrivacySalt() {
  try {
    return localStorage.getItem(PRIVACY_SALT_KEY) || "";
  } catch {
    return "";
  }
}
const state = {
  route: "home",
  range: "all",
  customFrom: "",
  customTo: "",
  privacy: readPrivacy(),
  privacySalt: "",
  raw: { kind: "fills", page: 0, symbol: "", q: "", side: "", positionSide: "", status: "" },
  renderId: 0,
};
if (state.privacy) {
  state.privacySalt = readPrivacySalt() || newPrivacySalt();
  try {
    localStorage.setItem(PRIVACY_SALT_KEY, state.privacySalt);
  } catch {}
}

function shanghaiDayStartMs(ms = Date.now()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(ms));
  const get = (t) => parts.find((p) => p.type === t).value;
  return Date.parse(`${get("year")}-${get("month")}-${get("day")}T00:00:00+08:00`);
}
function rangeMs(key) {
  const now = Date.now();
  const startOfDay = shanghaiDayStartMs(now);
  const sh = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
  }).formatToParts(new Date(now));
  const year = Number(sh.find((p) => p.type === "year").value);
  const y0 = Date.parse(`${year}-01-01T00:00:00+08:00`);
  if (key === "custom" && state.customFrom && state.customTo) {
    const from = Date.parse(`${state.customFrom}T00:00:00+08:00`);
    const to = Date.parse(`${state.customTo}T23:59:59.999+08:00`);
    if (!Number.isNaN(from) && !Number.isNaN(to) && from <= to) return [from, to];
  }
  const map = {
    today: [startOfDay, now],
    "7d": [now - 7 * 86400000, now],
    "30d": [now - 30 * 86400000, now],
    "90d": [now - 90 * 86400000, now],
    ytd: [y0, now],
    all: [null, null],
  };
  return map[key] || map.all;
}
function rangeLabel() {
  if (state.range === "custom" && state.customFrom && state.customTo) {
    return `${state.customFrom} → ${state.customTo}`;
  }
  return RANGE_LABELS[state.range] || "All time";
}
function qsRange() {
  const [from, to] = rangeMs(state.range);
  const p = new URLSearchParams();
  if (from) p.set("from", String(from));
  if (to) p.set("to", String(to));
  return p.toString();
}
async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(res.ok ? "响应不是 JSON" : res.statusText);
  }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function hash32(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function privacyUnit(key) {
  return hash32(`${state.privacySalt || "0"}:${key}`) / 4294967296;
}
function chartDecoy() {
  if (!state.privacy) return 1;
  return 8 + privacyUnit("chart:a") * 18;
}
function scramble(n, kind = "money") {
  const v = Number(n);
  if (!state.privacy || !Number.isFinite(v)) return v;
  if (v === 0) return 0;
  const sign = v < 0 ? -1 : 1;
  const abs = Math.abs(v);
  const u = privacyUnit(`${kind}:${abs.toPrecision(12)}`);
  let factor = 8 + u * 18;
  if (kind === "count") factor = 2.5 + u * 5;
  else if (kind === "price" || kind === "lev") factor = 0.85 + u * 0.5;
  else if (kind === "hold") factor = 0.8 + u * 0.7;
  else if (kind === "pct" || kind === "roi" || kind === "stat") factor = 1.4 + u * 1.6;
  let out = abs * factor;
  if (kind === "count") out = Math.max(1, Math.round(out));
  return sign * out;
}
function usdPlain(n, d = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const abs = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
  return v < 0 ? `-$${abs}` : `$${abs}`;
}
function signedUsdPlain(n, d = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const body = usdPlain(Math.abs(v), d);
  if (v > 0) return `+${body}`;
  if (v < 0) return `-${body}`;
  return body;
}
function usd(n, d = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return usdPlain(scramble(n, "money"), d);
}
function signedUsd(n, d = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return signedUsdPlain(scramble(n, "money"), d);
}
function count(n) {
  if (n == null || Number.isNaN(Number(n))) return "0";
  return String(Math.abs(Math.round(scramble(n, "count"))));
}
function priceTxt(n, digits = 5) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(scramble(n, "price")).toPrecision(digits);
}
function stat(n, d = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return scramble(n, "stat").toFixed(d);
}
function clsPnl(n) {
  if (n > 0) return "up";
  if (n < 0) return "down";
  return "";
}
function fmtTime(ms) {
  if (!ms) return "—";
  const d = new Date(ms);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const p = (x) => String(x).padStart(2, "0");
  return `${months[d.getMonth()]} ${d.getDate()}, ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtDay(ms) {
  if (!ms) return "";
  const d = new Date(ms);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}
function holdLabel(ms) {
  if (ms == null) return "—";
  const s = Math.round(scramble(ms, "hold") / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`;
  return `${(s / 86400).toFixed(1)}d`;
}
function pct(n) {
  return `${(Number(n) * 100).toFixed(0)}%`;
}
function roiFromRate(rate) {
  if (rate == null || !Number.isFinite(Number(rate))) return "—";
  const r = scramble(Number(rate), "roi") * 100;
  if (r > 0) return `+${r.toFixed(2)}%`;
  if (r < 0) return `${r.toFixed(2)}%`;
  return "0.00%";
}
function tagPills(tags) {
  return String(tags || "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => `<span class="tag">${esc(t)}</span>`)
    .join("");
}
function initials(sym) {
  return String(sym || "").replace("USDT", "").slice(0, 2).toUpperCase();
}

function parseHash() {
  state.route = (location.hash || "#/home").replace(/^#\/?/, "") || "home";
}
function setActiveNav() {
  $$("#rail a[data-route]").forEach((el) => {
    const r = el.getAttribute("data-route");
    el.classList.toggle("active", r && (state.route === r || state.route.startsWith(r + "/")));
  });
  $("#pageTitle").textContent = TITLES[state.route] || "Ledger";
}
function stale(seq) {
  return seq !== state.renderId;
}
function writeApp(seq, html) {
  if (stale(seq)) return false;
  $("#app").innerHTML = html;
  setPageBusy(false);
  return true;
}
function setPageBusy(on) {
  const bar = $("#pageProgress");
  if (bar) {
    bar.classList.toggle("on", on);
    bar.setAttribute("aria-hidden", on ? "false" : "true");
  }
  $$("#rail a[data-route]").forEach((el) => el.classList.remove("busy"));
  if (on) {
    const active = $$("#rail a[data-route]").find((el) => el.classList.contains("active"));
    if (active) active.classList.add("busy");
  }
}
function pageLoadingHtml() {
  const name = TITLES[state.route] || "页面";
  return `<div class="page-boot" aria-busy="true">
    <div class="load-line"><span class="spinner"></span><span>正在加载${esc(name)}…</span></div>
    <div class="grid grid-4">
      ${"<div class=\"card skel-card\"><div class=\"skel skel-k\"></div><div class=\"skel skel-v\"></div><div class=\"skel skel-s\"></div></div>".repeat(4)}
    </div>
    <div class="skel skel-panel"></div>
    <div class="grid grid-2" style="margin-top:14px">
      <div class="skel skel-panel sm"></div>
      <div class="skel skel-panel sm"></div>
    </div>
  </div>`;
}

function drawPnl(canvas, series, key = "equity", hover = null) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = devicePixelRatio || 1;
  const w = (canvas.width = canvas.clientWidth * dpr);
  const h = (canvas.height = Math.max(220, canvas.clientHeight || 260) * dpr);
  ctx.clearRect(0, 0, w, h);
  if (!series.length) return;
  const a = chartDecoy();
  const vals = series.map((p) => Number(p[key] || 0) * a);
  const times = series.map((p) => Number(p.t || 0));
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 0);
  const span = max - min || 1;
  const padL = 52 * dpr;
  const padR = 16 * dpr;
  const padT = 12 * dpr;
  const padB = 36 * dpr;
  const xAtT = (t) => padL + ((Number(t) - tMin) / tSpan) * (w - padL - padR);
  const xAt = (i) => xAtT(times[i]);
  const yAt = (v) => padT + (1 - (v - min) / span) * (h - padT - padB);
  const z = yAt(0);
  canvas._pnlDomain = { tMin, tMax, tSpan, padL: 52, padR: 16 };

  ctx.font = `${11 * dpr}px Inter, Segoe UI, sans-serif`;
  ctx.fillStyle = "#6d7380";
  ctx.textAlign = "right";
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = max - (span * i) / ticks;
    const y = yAt(v);
    ctx.fillText((v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(0), padL - 8 * dpr, y + 4 * dpr);
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = dpr;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
  }

  ctx.textAlign = "center";
  const tickCount = 5;
  for (let i = 0; i < tickCount; i++) {
    const t = tMin + (tSpan * i) / Math.max(tickCount - 1, 1);
    ctx.fillText(fmtDay(t), xAtT(t), h - 10 * dpr);
  }

  const strokePath = () => {
    ctx.beginPath();
    series.forEach((p, i) => {
      const x = xAt(i);
      const y = yAt(vals[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
  };

  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, padT, w - padL - padR, Math.max(0, z - padT));
  ctx.clip();
  strokePath();
  ctx.lineTo(xAt(series.length - 1), z);
  ctx.lineTo(xAt(0), z);
  ctx.closePath();
  ctx.fillStyle = "rgba(61, 214, 140, 0.22)";
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, z, w - padL - padR, Math.max(0, h - padB - z));
  ctx.clip();
  strokePath();
  ctx.lineTo(xAt(series.length - 1), z);
  ctx.lineTo(xAt(0), z);
  ctx.closePath();
  ctx.fillStyle = "rgba(227, 93, 112, 0.22)";
  ctx.fill();
  ctx.restore();

  strokePath();
  ctx.lineWidth = 1.7 * dpr;
  ctx.strokeStyle = vals[vals.length - 1] >= 0 ? "#3dd68c" : "#e35d70";
  ctx.stroke();

  if (hover == null || !series[hover]) return;
  const x = xAt(hover);
  const y = yAt(vals[hover]);
  ctx.setLineDash([4 * dpr, 4 * dpr]);
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  ctx.lineWidth = dpr;
  ctx.beginPath();
  ctx.moveTo(x, padT);
  ctx.lineTo(x, h - padB);
  ctx.moveTo(padL, y);
  ctx.lineTo(w - padR, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.fillStyle = "#f3f4f6";
  ctx.arc(x, y, 3.4 * dpr, 0, Math.PI * 2);
  ctx.fill();
}

function trackChart(canvas, series, key = "equity") {
  if (!canvas) return;
  state.charts = (state.charts || []).filter((c) => c.canvas !== canvas);
  state.charts.push({ canvas, series, key });
}

function bindPnlHover(canvas, series, key = "equity") {
  const wrap = canvas.closest(".chart-wrap") || canvas.parentElement;
  let tip = wrap.querySelector(".chart-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "chart-tip";
    wrap.appendChild(tip);
  }
  const indexAt = (e) => {
    if (!series.length) return null;
    const domain = canvas._pnlDomain || {};
    const padL = domain.padL || 52;
    const padR = domain.padR || 16;
    const rect = canvas.getBoundingClientRect();
    const inner = Math.max(rect.width - padL - padR, 1);
    const tMin = domain.tMin ?? Number(series[0].t || 0);
    const tMax = domain.tMax ?? Number(series[series.length - 1].t || 0);
    const tSpan = domain.tSpan || tMax - tMin || 1;
    const t = tMin + ((e.clientX - rect.left - padL) / inner) * tSpan;
    let best = 0;
    let bestD = Infinity;
    series.forEach((p, i) => {
      const d = Math.abs(Number(p.t || 0) - t);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  };
  canvas.onmousemove = (e) => {
    const i = indexAt(e);
    if (i == null) return;
    drawPnl(canvas, series, key, i);
    const p = series[i];
    const wrapRect = wrap.getBoundingClientRect();
    tip.style.display = "block";
    tip.style.left = `${Math.min(e.clientX - wrapRect.left + 12, wrapRect.width - 160)}px`;
    tip.style.top = `${Math.max(8, e.clientY - wrapRect.top - 52)}px`;
    tip.innerHTML = `<div>${fmtTime(p.t)}</div><div><strong>${signedUsdPlain(Number(p[key] || 0) * chartDecoy())}</strong></div>`;
  };
  canvas.onmouseleave = () => {
    drawPnl(canvas, series, key);
    tip.style.display = "none";
  };
}

function drawDonut(canvas, win, loss, be) {
  const ctx = canvas.getContext("2d");
  const dpr = devicePixelRatio || 1;
  const s = (canvas.width = canvas.height = 92 * dpr);
  const r = s / 2;
  const total = win + loss + be || 1;
  const ring = 11 * dpr;
  ctx.clearRect(0, 0, s, s);
  ctx.beginPath();
  ctx.strokeStyle = "#2c2f36";
  ctx.lineWidth = ring;
  ctx.arc(r, r, r - ring, 0, Math.PI * 2);
  ctx.stroke();
  let a = -Math.PI / 2;
  [[win, "#3dd68c"], [loss, "#e35d70"], [be, "#6d7380"]].forEach(([n, c]) => {
    if (!n) return;
    const slice = (n / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.strokeStyle = c;
    ctx.lineCap = "butt";
    ctx.lineWidth = ring;
    ctx.arc(r, r, r - ring, a, a + slice);
    ctx.stroke();
    a += slice;
  });
}

function barsHtml(rows) {
  if (!rows.length) return `<div class="s">暂无数据</div>`;
  const max = Math.max(...rows.map((r) => Math.abs(r.net_pnl || 0)), 1);
  return rows
    .map((r) => {
      const pnl = Number(r.net_pnl || 0);
      return `<div class="bar-row">
        <div class="name">${esc(r.name)}</div>
        <div class="track"><div class="fill ${pnl < 0 ? "neg" : ""}" style="width:${(Math.abs(pnl) / max) * 100}%"></div></div>
        <div class="val ${clsPnl(pnl)}">${signedUsd(pnl)}</div>
      </div>`;
    })
    .join("");
}

function chartRange(series) {
  if (!series.length) return "";
  return `${fmtDay(series[0].t)} – ${fmtDay(series[series.length - 1].t)}`;
}

async function renderHome() {
  const seq = state.renderId;
  const accountP = api("/api/account").catch(() => ({ ok: false }));
  const data = await api("/api/summary?" + qsRange());
  if (stale(seq)) return;
  const s = data.stats || {};
  const longs = s.longs || 0;
  const shorts = s.shorts || 0;
  const ls = longs + shorts || 1;
  const todayDay = data.today || {};
  const weeks = data.past_4_weeks || [];
  const avgVol = s.trades ? s.volume / s.trades : 0;
  const paint = (account) => {
    const pending = Boolean(account && account.pending);
    const value = account.ok ? account.equity : s.net_pnl;
    if (
      !writeApp(
        seq,
        `
    <div class="grid grid-4">
      <div class="card">
        <div class="k">Portfolio Value</div>
        <div class="v ${pending ? "" : account.ok ? "" : clsPnl(value)}" id="portValue">${
          pending ? `<span class="inline-load"><span class="spinner sm"></span></span>` : usd(value)
        }</div>
        <div class="s" id="portHint">${pending ? "正在读取账户权益…" : account.ok ? "The total value of assets in your accounts" : "区间已实现净盈亏（账户权益暂不可用）"}</div>
      </div>
      <div class="card">
        <div class="donut-wrap">
          <div class="donut-box">
            <canvas id="donut"></canvas>
            <div class="donut-pct">${pct(s.win_rate || 0)}</div>
          </div>
          <div>
            <div class="k">Total Win Rate</div>
            <div class="winline"><span class="up">${count(s.wins)} Wins</span><br><span class="down">${count(s.losses)} Losses</span><br><span class="s">${count(s.breakeven)} Breakeven</span></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="k">Total Trade Count</div>
        <div class="v">${count(s.trades)}</div>
        <div class="s">Total volume of ${usd(s.volume || 0)} with an average of ${usd(avgVol)} volume per trade</div>
      </div>
      <div class="card">
        <div class="ls">
          <div><div class="v">${pct(longs / ls)}</div><div class="s">Long Ratio</div></div>
          <div style="text-align:right"><div class="v">${pct(shorts / ls)}</div><div class="s">Short Ratio</div></div>
        </div>
        <div class="ratio"><span class="lg" style="width:${(longs / ls) * 100}%"></span><span class="sh" style="width:${(shorts / ls) * 100}%"></span></div>
      </div>
    </div>
    <div class="card chart-card" style="margin-top:14px">
      <div class="chart-head">
        <div class="card-title">PnL · ${rangeLabel()}</div>
        <div class="chart-range">${chartRange(data.curve || [])}</div>
      </div>
      <div class="chart-wrap">
        <canvas id="curve" style="height:280px"></canvas>
        <div class="chart-tip"></div>
      </div>
    </div>
    <div class="grid grid-2" style="margin-top:14px">
      <div class="card">
        <div class="chart-head">
          <div class="card-title">Past 4 Weeks</div>
          <div class="chart-range">${weeks.length ? weeks[0].day + " – " + weeks[weeks.length - 1].day : ""}</div>
        </div>
        <div class="weeks-head">${DOW.map((d) => `<div>${d}</div>`).join("")}</div>
        ${[0, 1, 2, 3]
          .map((w) => {
            const slice = weeks.slice(w * 7, w * 7 + 7);
            return `<div class="weeks-row" style="margin-bottom:8px">${slice
              .map((d) => {
                const future = Boolean(d.is_future);
                const cls = `${d.trades ? (d.pnl >= 0 ? "on" : "loss") : ""}${d.is_today ? " today" : ""}${future ? " future" : ""}`;
                const amt = future ? "—" : d.trades ? signedUsd(d.pnl) : signedUsd(0);
                return `<div class="wcell ${cls}" data-day="${esc(d.day)}" title="${esc(d.day)}">
                  <div class="meta"><span>${Number(d.day.slice(8))}</span><span>${count(d.trades || 0)} trades</span></div>
                  <div class="amt ${future ? "" : clsPnl(d.pnl)}">${amt}</div>
                </div>`;
              })
              .join("")}</div>`;
          })
          .join("")}
      </div>
      <div class="card">
        <div class="k">今日 ${todayDay.day || ""}</div>
        <div class="s" style="margin-bottom:10px">已平仓盈亏（上海时区，按平仓时间）</div>
        <div class="v ${clsPnl(todayDay.pnl)}" style="font-size:36px">${signedUsd(todayDay.pnl || 0)}</div>
        <div class="s" style="margin-top:10px">今日已平仓 ${count(todayDay.trades || 0)} 笔</div>
        <div class="stat-split">
          <div>
            <div class="s">区间收益 · ${esc(rangeLabel())}</div>
            <div class="v sm ${clsPnl(s.net_pnl)}">${signedUsd(s.net_pnl)}</div>
          </div>
          <div>
            <div class="s">收益率</div>
            <div class="v sm" id="roiValue"><span class="inline-load"><span class="spinner sm"></span></span></div>
            <div class="s roi-hint" id="roiHint">按日 TWR<br>划转后本金计入后续交易</div>
          </div>
        </div>
      </div>
    </div>
    ${positionsCard(account)}
    <div class="list-block" style="margin-top:18px">
      <div class="chart-head">
        <div class="card-title" style="margin:0">Last 3 trades</div>
        <a class="section-link" href="#/journal">按最近平仓时间 · 查看全部</a>
      </div>
      ${journalList(data.last_trades || [], { wide: true, empty: "还没有已平仓轮次。点左侧刷新从币安拉取成交。" })}
    </div>`
      )
    ) {
      return false;
    }
    drawDonut($("#donut"), s.wins || 0, s.losses || 0, s.breakeven || 0);
    drawPnl($("#curve"), data.curve || []);
    trackChart($("#curve"), data.curve || []);
    bindPnlHover($("#curve"), data.curve || []);
    $$(".wcell[data-day]").forEach((el) => {
      el.onclick = () => {
        const [y, m] = el.dataset.day.split("-").map(Number);
        state.calYear = y;
        state.calMonth = m;
        state.calFocusDay = el.dataset.day;
        location.hash = "#/calendar";
      };
    });
    return true;
  };
  if (!paint({ ok: false, pending: true })) return;
  const account = await accountP;
  if (stale(seq)) return;
  await applyAccountToHome(account, data, seq);
}

async function renderDashboard() {
  const seq = state.renderId;
  const [sum, symbols, tags] = await Promise.all([
    api("/api/summary?" + qsRange()),
    api("/api/report?kind=symbol&" + qsRange()),
    api("/api/report?kind=tag&" + qsRange()),
  ]);
  if (stale(seq)) return;
  const s = sum.stats || {};
  if (
    !writeApp(
      seq,
      `
    <div class="grid grid-3">
      <div class="card chart-card">
        <div class="card-title">PnL (Cumulative)</div>
        <div class="chart-wrap"><canvas id="curve" style="height:180px"></canvas><div class="chart-tip"></div></div>
        <div class="widget-foot">Net ${signedUsd(s.net_pnl)} · max DD ${signedUsd(s.max_drawdown)}</div>
      </div>
      <div class="card">
        <div class="card-title">Win Rate</div>
        <div class="v">${pct(s.win_rate || 0)}</div>
        <div class="s">${count(s.wins)} winning of ${count(s.trades)} trades (${pct(s.win_rate || 0)})</div>
      </div>
      <div class="card">
        <div class="card-title">PnL</div>
        <div class="v ${clsPnl(s.net_pnl)}">${signedUsd(s.net_pnl)}</div>
        <div class="s">Fees ${usd(s.fees || 0)} · PF ${stat(s.profit_factor || 0)}</div>
      </div>
    </div>
    <div class="grid grid-3" style="margin-top:14px">
      <div class="card">
        <div class="card-title">Hold time</div>
        <div class="v">${holdLabel(s.avg_hold_ms)}</div>
        <div class="s">Average hold across closed trades</div>
      </div>
      <div class="card">
        <div class="card-title">Volume (Cumulative)</div>
        <div class="v">${usd(s.volume || 0, 0)}</div>
        <div class="s">Avg ${usd(s.trades ? s.volume / s.trades : 0)} per trade</div>
      </div>
      <div class="card">
        <div class="card-title">Total trades</div>
        <div class="v">${count(s.trades)}</div>
        <div class="s">${count(sum.symbol_count || 0)} symbols</div>
      </div>
    </div>
    <div class="grid grid-2" style="margin-top:14px">
      <div class="card"><div class="card-title">Symbols</div>${barsHtml(symbols.slice(0, 12))}</div>
      <div class="card"><div class="card-title">Tags</div>${barsHtml(tags)}</div>
    </div>`
    )
  )
    return;
  drawPnl($("#curve"), sum.curve || []);
  trackChart($("#curve"), sum.curve || []);
  bindPnlHover($("#curve"), sum.curve || []);
}

async function renderReport(kind) {
  const seq = state.renderId;
  if (kind === "pnl") {
    const sum = await api("/api/summary?" + qsRange());
    if (!writeApp(seq, `<div class="card chart-card"><div class="chart-wrap"><canvas id="curve" style="height:320px"></canvas><div class="chart-tip"></div></div></div>`)) return;
    drawPnl($("#curve"), sum.curve || []);
    trackChart($("#curve"), sum.curve || []);
    bindPnlHover($("#curve"), sum.curve || []);
    return;
  }
  const rows = await api(`/api/report?kind=${kind === "tags" ? "tag" : "symbol"}&` + qsRange());
  writeApp(seq, `<div class="card">${barsHtml(rows)}</div>`);
}

async function renderAnalytics() {
  const seq = state.renderId;
  const data = await api("/api/analytics?" + qsRange());
  if (
    !writeApp(
      seq,
      `
    <div class="grid grid-2">
      <div class="card chart-card"><div class="card-title">Drawdown</div><div class="chart-wrap"><canvas id="dd" style="height:220px"></canvas><div class="chart-tip"></div></div></div>
      <div class="card"><div class="card-title">Hold time</div>${barsHtml(data.hold || [])}</div>
    </div>
    <div class="grid grid-2" style="margin-top:14px">
      <div class="card"><div class="card-title">Sessions</div>${barsHtml(data.session || [])}</div>
      <div class="card"><div class="card-title">Day of week</div>${barsHtml(data.weekday || [])}</div>
    </div>`
    )
  )
    return;
  drawPnl($("#dd"), data.curve || [], "drawdown");
  trackChart($("#dd"), data.curve || [], "drawdown");
  bindPnlHover($("#dd"), data.curve || [], "drawdown");
}

async function renderCalendar() {
  const seq = state.renderId;
  if (!$(".page-boot")) setPageBusy(true);
  const params = new URLSearchParams();
  if (state.calYear && state.calMonth) {
    params.set("year", String(state.calYear));
    params.set("month", String(state.calMonth));
  }
  const data = await api("/api/calendar" + (params.toString() ? "?" + params : ""));
  if (stale(seq)) return;
  state.calYear = data.year;
  state.calMonth = data.month;
  const months = data.months || [];
  const cells = [
    ...DOW.map((w) => `<div class="hd">${w}</div>`),
    ...Array.from({ length: data.weekday_offset }, () => `<div></div>`),
    ...data.days.map((d) => {
      const cls = `${d.trades ? (d.pnl >= 0 ? "has" : "loss") : ""}${d.is_today ? " today" : ""}${d.is_future ? " future" : ""}`;
      const amt = d.is_future ? "" : d.trades ? signedUsd(d.pnl) : "";
      return `<div class="cell ${cls}" data-day="${esc(d.day)}">
        <div class="num">${Number(d.day.slice(8))}</div>
        <div class="p ${d.is_future ? "" : clsPnl(d.pnl)}">${amt}</div>
        <div class="n">${d.trades ? count(d.trades) + " Trades" : ""}</div>
      </div>`;
    }),
  ];
  const monthBtns = months
    .map((m) => {
      const on = m.year === data.year && m.month === data.month;
      const label = `${m.year}-${String(m.month).padStart(2, "0")}`;
      return `<button type="button" class="btn ${on ? "on" : ""}" data-cal-y="${m.year}" data-cal-m="${m.month}">${label} · ${count(m.trades)}</button>`;
    })
    .join("");
  if (
    !writeApp(
      seq,
      `
    <div class="toolbar" style="justify-content:flex-end;flex-wrap:wrap">
      <div class="month-label">${data.year} / ${String(data.month).padStart(2, "0")}
        <span class="s" style="margin:0 0 0 8px">${data.trades ? signedUsd(data.pnl) + " · " + count(data.trades) + " 笔" : "本月无平仓"}</span>
      </div>
      <button class="btn" id="prevM">‹</button>
      <button class="btn" id="calToday">本月</button>
      <button class="btn" id="nextM">›</button>
    </div>
    <div class="cal-months">${monthBtns || `<span class="s">还没有已平仓月份</span>`}</div>
    ${data.trades ? "" : `<div class="s" style="margin:0 0 12px">格子为空表示这个月没有平仓。有成交的月份在上方，不会出现 2025 这种没有记录的年份。</div>`}
    <div class="cal">${cells.join("")}</div>
    <div id="dayBox"></div>`
    )
  )
    return;
  $("#prevM").onclick = () => {
    let y = data.year, m = data.month - 1;
    if (m < 1) { m = 12; y -= 1; }
    state.calYear = y; state.calMonth = m; renderCalendar();
  };
  $("#nextM").onclick = () => {
    let y = data.year, m = data.month + 1;
    if (m > 12) { m = 1; y += 1; }
    state.calYear = y; state.calMonth = m; renderCalendar();
  };
  $("#calToday").onclick = () => {
    state.calYear = data.today_year;
    state.calMonth = data.today_month;
    renderCalendar();
  };
  $$("[data-cal-y]").forEach((el) => {
    el.onclick = () => {
      state.calYear = Number(el.dataset.calY);
      state.calMonth = Number(el.dataset.calM);
      renderCalendar();
    };
  });
  $$(".cal .cell[data-day]").forEach((el) => {
    el.onclick = async () => {
      const day = el.dataset.day;
      const det = await api("/api/day?day=" + day);
      $("#dayBox").innerHTML = `<div class="card" style="margin-top:16px">
        <div class="k">${esc(day)}</div>
        <div class="v ${clsPnl(det.stats.net_pnl)}">${signedUsd(det.stats.net_pnl)}</div>
        <div class="s">${count(det.stats.trades)} trades</div>
        <textarea id="note">${esc(det.note || "")}</textarea>
        <div class="toolbar"><button class="btn" id="saveNote">Save note</button></div>
      </div>${journalList(det.trades || [])}`;
      $("#saveNote").onclick = async () => {
        await api("/api/note", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ day, body: $("#note").value }),
        });
        $("#saveNote").textContent = "已保存";
      };
    };
  });
  if (state.calFocusDay) {
    const focus = $(`.cal .cell[data-day="${state.calFocusDay}"]`);
    state.calFocusDay = "";
    if (focus) focus.click();
  }
}

function positionsCard(account) {
  if (account && account.pending) {
    return `<div class="card list-card" id="posSlot" style="margin-top:14px">
      <div class="chart-head">
        <div class="card-title" style="margin:0">Open positions</div>
        <div class="chart-range"><span class="inline-load"><span class="spinner sm"></span>读取实时持仓</span></div>
      </div>
      <div class="skel skel-row"></div>
      <div class="skel skel-row"></div>
    </div>`;
  }
  const rows = (account && account.positions) || [];
  const liveFailed = account && account.ok === false;
  const localOnly = rows.length && rows.every((p) => p.source === "local");
  const body = rows.length
    ? `<div class="jhead pos"><div>Symbol</div><div>Side & Size</div><div class="num-end">Entry</div><div class="num-end">Unrealized</div><div class="num-end">Lev</div></div>
      ${rows
        .map((p) => {
          const amt = Number(p.amount || 0);
          const short = String(p.side || "").toUpperCase() === "SHORT" || amt < 0;
          const notional = Math.abs(amt) * Number(p.entry || 0);
          const uPnl = p.unrealized;
          return `<div class="jrow pos ${short ? "short" : ""}">
            <div class="sym-cell"><span class="avatar">${esc(initials(p.symbol))}</span><div class="sym-meta">${esc(p.symbol)}</div></div>
            <div class="sz ${short ? "down" : "up"}">${short ? "↘" : "↗"} ${usd(notional)}</div>
            <div class="px num-end">${priceTxt(p.entry)}</div>
            <div class="pnl-chip ${uPnl == null ? "" : clsPnl(uPnl)}">${uPnl == null ? "—" : signedUsd(uPnl)}</div>
            <div class="lev num-end">${p.leverage ? Math.max(1, Math.round(scramble(p.leverage, "lev"))) + "x" : p.source === "local" ? "本地" : "—"}</div>
          </div>`;
        })
        .join("")}`
    : `<div class="pos-empty">${liveFailed ? "账户接口不可用，无法读取实时持仓" : "当前无持仓"}</div>`;
  const hint = localOnly
    ? "实时仓位接口失败，以下为本地未平仓轮次"
    : rows.length && account && account.ok
      ? `未实现 ${signedUsd(account.unrealized || 0)}`
      : "";
  return `<div class="card list-card" id="posSlot" style="margin-top:14px">
    <div class="chart-head">
      <div class="card-title" style="margin:0">Open positions</div>
      <div class="chart-range">${hint}</div>
    </div>
    ${body}
  </div>`;
}

async function applyAccountToHome(account, data, seq) {
  const s = data.stats || {};
  const value = account.ok ? account.equity : s.net_pnl;
  const v = $("#portValue");
  const h = $("#portHint");
  if (v) {
    v.className = `v ${account.ok ? "" : clsPnl(value)}`;
    v.textContent = usd(value);
  }
  if (h) {
    h.textContent = account.ok
      ? "The total value of assets in your accounts"
      : "区间已实现净盈亏（账户权益暂不可用）";
  }
  const roi = $("#roiValue");
  const hint = $("#roiHint");
  let rate = null;
  let start = null;
  if (account.ok) {
    try {
      const twr = await api("/api/twr?" + qsRange() + "&wallet=" + encodeURIComponent(String(account.wallet)));
      if (seq != null && stale(seq)) return;
      rate = twr.twr;
      start = twr.start_equity;
    } catch {
      rate = null;
    }
  }
  if (roi) {
    roi.innerHTML = `<span class="${clsPnl(rate)}">${roiFromRate(rate)}</span>`;
  }
  if (hint) {
    const line1 =
      start != null && Number.isFinite(Number(start))
        ? `按日 TWR · 期初 ${usd(start)}`
        : "按日 TWR";
    hint.innerHTML = `${line1}<br>划转后本金计入后续交易`;
  }
  const slot = $("#posSlot");
  if (!slot) return;
  const box = document.createElement("div");
  box.innerHTML = positionsCard(account);
  slot.replaceWith(box.firstElementChild);
}

function journalList(rows, opts = {}) {
  const wide = Boolean(opts.wide);
  if (!rows.length) {
    return `<div class="empty">${esc(opts.empty || "这个区间还没有平仓轮次。点左侧刷新，从币安拉取成交。")}</div>`;
  }
  const head = wide
    ? `<div class="jhead wide"><div>Symbol</div><div>Side & Size</div><div>Open & Close Times</div><div>Hold Time</div><div>Entry & Exit</div><div class="num-end">PnL</div></div>`
    : `<div class="jhead"><div>Symbol</div><div>Side & Size</div><div>Open & Close Times</div><div>Entry & Exit</div><div class="num-end">PnL</div></div>`;
  return `${head}
    ${rows
      .map((r) => {
        const pnl = Number(r.net_pnl || 0);
        const short = String(r.side) === "Short";
        const notional = Number(r.qty || 0) * Number(r.entry_price || 0);
        const chg =
          r.exit_price && r.entry_price
            ? ((Number(r.exit_price) - Number(r.entry_price)) / Number(r.entry_price)) * (short ? -1 : 1) * 100
            : null;
        const chgFake = chg == null ? null : scramble(chg, "pct");
        return `<div class="jrow ${wide ? "wide" : ""} ${short ? "short" : ""}">
          <div class="sym-cell"><span class="avatar">${esc(initials(r.symbol))}</span><div class="sym-meta">${esc(r.symbol)}${tagPills(r.tags)}</div></div>
          <div class="sz ${short ? "down" : "up"}">${short ? "↘" : "↗"} ${usd(notional)}</div>
          <div class="tm">${fmtTime(r.open_time_ms)} → ${fmtTime(r.close_time_ms)}<small>Close time</small></div>
          ${wide ? `<div class="tm">${holdLabel(r.hold_ms)}</div>` : ""}
          <div class="px">${priceTxt(r.entry_price)} → ${r.exit_price == null ? "—" : priceTxt(r.exit_price)}${chgFake == null ? "" : `<small>${chgFake >= 0 ? "+" : ""}${chgFake.toFixed(2)}%</small>`}</div>
          <div class="pnl-chip ${clsPnl(pnl)}">${signedUsd(pnl)}</div>
        </div>`;
      })
      .join("")}`;
}

async function renderJournal() {
  const seq = state.renderId;
  const data = await api("/api/roundtrips?limit=300&" + qsRange());
  const total = data.total || 0;
  writeApp(seq, `<div class="s" style="margin:0 4px 12px">已平仓 ${count(total)} 笔${total > 300 ? "（本页最多 300）" : ""}</div>${journalList(data.rows || [])}`);
}

async function renderTrades() {
  const seq = state.renderId;
  const data = await api("/api/fills?limit=400&" + qsRange());
  if (!data.rows.length) {
    writeApp(seq, `<div class="empty">还没有成交。</div>`);
    return;
  }
  writeApp(
    seq,
    data.rows
      .map((r) => {
        const pnl = Number(r.realized_pnl || 0);
        return `<div class="jrow ${r.side === "SELL" ? "short" : ""}">
        <div class="sym-cell"><span class="avatar">${esc(initials(r.symbol))}</span>${esc(r.symbol)}</div>
        <div class="sz">${r.side} ${state.privacy ? Number(scramble(r.qty, "qty")).toPrecision(6) : r.qty}</div>
        <div class="tm">${fmtTime(r.time_ms)}<small>${r.strategy_tag || ""}</small></div>
        <div class="px">${priceTxt(r.price, 6)}</div>
        <div class="pnl-chip ${clsPnl(pnl)}">${signedUsd(pnl, 4)}</div>
      </div>`;
      })
      .join("")
  );
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function fmtTs(ms) {
  if (ms == null || ms === "") return "";
  const n = Number(ms);
  if (!Number.isFinite(n)) return esc(ms);
  const d = new Date(n);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

function rawCell(key, value) {
  if (value == null || value === "") return "";
  if (String(key).endsWith("_ms") || key === "time_ms") {
    return `<span title="${esc(value)}">${esc(fmtTs(value))}</span>`;
  }
  const asNum =
    typeof value === "number"
      ? value
      : typeof value === "string" && /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(value.trim())
        ? Number(value)
        : null;
  if (asNum != null && Number.isFinite(asNum)) {
    const n = scramble(asNum, "raw");
    if (Number.isInteger(asNum) || Math.abs(asNum) >= 1000) return esc(String(Math.round(n)));
    return esc(String(Number(n.toPrecision(10))));
  }
  return esc(value);
}

function bindRawControls() {
  const raw = state.raw;
  const go = () => {
    raw.page = 0;
    renderRawdata();
  };
  $("#rawKind")?.querySelectorAll("[data-kind]").forEach((el) => {
    el.onclick = () => {
      raw.kind = el.dataset.kind;
      raw.page = 0;
      renderRawdata();
    };
  });
  $("#rawSymbol") && ($("#rawSymbol").onchange = (e) => { raw.symbol = e.target.value; go(); });
  $("#rawSide") && ($("#rawSide").onchange = (e) => { raw.side = e.target.value; go(); });
  $("#rawPos") && ($("#rawPos").onchange = (e) => { raw.positionSide = e.target.value; go(); });
  $("#rawStatus") && ($("#rawStatus").onchange = (e) => { raw.status = e.target.value; go(); });
  $("#rawSearch") && ($("#rawSearch").onkeydown = (e) => {
    if (e.key === "Enter") {
      raw.q = e.target.value.trim();
      go();
    }
  });
  $("#rawSearchBtn") && ($("#rawSearchBtn").onclick = () => {
    raw.q = $("#rawSearch").value.trim();
    go();
  });
  $("#rawPrev") && ($("#rawPrev").onclick = () => {
    raw.page = Math.max(0, raw.page - 1);
    renderRawdata();
  });
  $("#rawNext") && ($("#rawNext").onclick = () => {
    raw.page += 1;
    renderRawdata();
  });
  $("#rawRebuild") && ($("#rawRebuild").onclick = async () => {
    $("#rawRebuild").disabled = true;
    $("#rawRebuild").textContent = "重算中…";
    try {
      const r = await api("/api/rebuild", { method: "POST" });
      $("#syncHint").textContent = `已重算 ${count(r.roundtrips)} 笔 roundtrips`;
      await renderRawdata();
    } catch (e) {
      $("#syncHint").textContent = e.message;
      $("#rawRebuild").disabled = false;
      $("#rawRebuild").textContent = "重算 roundtrips";
    }
  });
}

async function renderRawdata() {
  const seq = state.renderId;
  if (!$(".page-boot")) setPageBusy(true);
  const raw = state.raw;
  const limit = 80;
  const offset = raw.page * limit;
  const p = new URLSearchParams();
  const [from, to] = rangeMs(state.range);
  if (from) p.set("from", String(from));
  if (to) p.set("to", String(to));
  p.set("kind", raw.kind);
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  if (raw.symbol) p.set("symbol", raw.symbol);
  if (raw.q) p.set("q", raw.q);
  if (raw.kind === "fills") {
    if (raw.side) p.set("side", raw.side);
    if (raw.positionSide) p.set("position_side", raw.positionSide);
  }
  if (raw.kind === "roundtrips") {
    if (raw.side) p.set("side", raw.side);
    if (raw.status) p.set("status", raw.status);
  }
  const [meta, data] = await Promise.all([
    api("/api/raw/meta"),
    api("/api/raw?" + p.toString()),
  ]);
  const rows = data.rows || [];
  const total = data.total || 0;
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + rows.length, total);
  const cols = rows.length ? Object.keys(rows[0]) : [];
  const kinds = [
    ["fills", `Fills ${count(meta.fills)}`],
    ["income", `Income ${count(meta.income)}`],
    ["roundtrips", `Roundtrips ${count(meta.roundtrips)}`],
  ];
  const symbolOpts = ["", ...(meta.symbols || [])]
    .map((s) => `<option value="${esc(s)}" ${s === raw.symbol ? "selected" : ""}>${esc(s || "全部品种")}</option>`)
    .join("");
  const extraFilters = raw.kind === "fills"
    ? `<select id="rawSide">
         <option value="">side</option>
         ${["BUY", "SELL"].map((s) => `<option ${raw.side === s ? "selected" : ""}>${s}</option>`).join("")}
       </select>
       <select id="rawPos">
         <option value="">positionSide</option>
         ${["LONG", "SHORT", "BOTH"].map((s) => `<option ${raw.positionSide === s ? "selected" : ""}>${s}</option>`).join("")}
       </select>`
    : raw.kind === "roundtrips"
      ? `<select id="rawSide">
           <option value="">side</option>
           ${["Long", "Short"].map((s) => `<option ${raw.side === s ? "selected" : ""}>${s}</option>`).join("")}
         </select>
         <select id="rawStatus">
           <option value="">status</option>
           ${["Closed", "Open"].map((s) => `<option ${raw.status === s ? "selected" : ""}>${s}</option>`).join("")}
         </select>`
      : "";
  const table = rows.length
    ? `<div class="raw-scroll"><table class="raw-table">
        <thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${rawCell(c, r[c])}</td>`).join("")}</tr>`).join("")}</tbody>
      </table></div>`
    : `<div class="empty">这个筛选条件下没有记录。</div>`;
  if (
    !writeApp(
      seq,
      `
    <div class="raw-page">
      <div class="raw-note">这里是 SQLite 里的原始记录，按时间倒序。Fills / Income 来自币安接口；Roundtrips 是本地用成交合成的仓位轮次。</div>
      <div class="raw-stats">
        <span>DB ${esc(meta.db_path || "")}</span>
        <span>fills ${fmtTs(meta.fill_from_ms)} → ${fmtTs(meta.fill_to_ms)}</span>
      </div>
      <div class="raw-tabs" id="rawKind">
        ${kinds.map(([k, label]) => `<button type="button" data-kind="${k}" class="${raw.kind === k ? "on" : ""}">${label}</button>`).join("")}
        <button type="button" class="btn" id="rawRebuild">重算 roundtrips</button>
      </div>
      <div class="raw-toolbar">
        <select id="rawSymbol">${symbolOpts}</select>
        ${extraFilters}
        <input id="rawSearch" type="search" placeholder="搜 symbol / cid / trade_id" value="${esc(raw.q)}" />
        <button type="button" class="btn" id="rawSearchBtn">搜索</button>
      </div>
      ${table}
      <div class="raw-pager">
        <button type="button" class="btn" id="rawPrev" ${offset <= 0 ? "disabled" : ""}>上一页</button>
        <span>${count(start)}–${count(end)} / ${count(total)}</span>
        <button type="button" class="btn" id="rawNext" ${end >= total ? "disabled" : ""}>下一页</button>
      </div>
    </div>`
    )
  )
    return;
  bindRawControls();
}

const routes = {
  home: renderHome,
  dashboard: renderDashboard,
  "reports/tags": () => renderReport("tags"),
  "reports/symbols": () => renderReport("symbols"),
  "reports/pnl": () => renderReport("pnl"),
  analytics: renderAnalytics,
  calendar: renderCalendar,
  journal: renderJournal,
  trades: renderTrades,
  rawdata: renderRawdata,
};

async function refreshHint() {
  const meta = await api("/api/meta");
  const mode = meta.next_mode === "full" ? "Next sync: full universe" : "Next sync: incremental";
  const key = meta.has_api_key ? "" : " · API key missing";
  const symbols = count(meta.symbol_count || 0);
  const fills = count(meta.fills);
  $("#syncHint").textContent = `${symbols} symbols · ${fills} fills · ${mode}${key}`;
  return meta;
}

async function render(opts = {}) {
  parseHash();
  setActiveNav();
  const seq = ++state.renderId;
  state.charts = [];
  if (!opts.quiet) {
    setPageBusy(true);
    $("#app").innerHTML = pageLoadingHtml();
  }
  try {
    await (routes[state.route] || renderHome)();
  } catch (e) {
    writeApp(seq, `<div class="empty">${esc(e.message)}</div>`);
  } finally {
    if (!stale(seq)) setPageBusy(false);
  }
}

async function doSync(forceFull = false) {
  const btn = $("#syncBtn");
  btn.disabled = true;
  $("#syncHint").textContent = forceFull ? "Full universe sync…" : "Fetching from Binance…";
  try {
    await api("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force_full: forceFull }),
    });
    const poll = async () => {
      try {
        const job = await api("/api/sync");
        const p = job.progress || {};
        if (job.running) {
          $("#syncHint").textContent = p.message || "Syncing…";
          setTimeout(poll, 700);
          return;
        }
        btn.disabled = false;
        if (job.error) $("#syncHint").textContent = job.error;
        await refreshHint();
        await render();
      } catch (e) {
        btn.disabled = false;
        $("#syncHint").textContent = e.message;
      }
    };
    poll();
  } catch (e) {
    btn.disabled = false;
    $("#syncHint").textContent = e.message;
  }
}

window.addEventListener("hashchange", render);
$("#syncBtn").addEventListener("click", (e) => doSync(Boolean(e.shiftKey)));
window.addEventListener("resize", () => {
  clearTimeout(state.resizeTimer);
  state.resizeTimer = setTimeout(() => {
    (state.charts || []).forEach((c) => {
      if (c.canvas && c.canvas.isConnected) drawPnl(c.canvas, c.series, c.key);
    });
  }, 120);
});

function syncPrivacyBtn() {
  const btn = $("#privacyBtn");
  if (!btn) return;
  btn.setAttribute("aria-pressed", state.privacy ? "true" : "false");
  btn.title = state.privacy ? "Show Balances" : "Hide Balances";
  const label = $("#privacyLabel");
  if (label) label.textContent = state.privacy ? "Show Balances" : "Hide Balances";
  document.body.classList.toggle("privacy-on", state.privacy);
}
function setPrivacy(on) {
  state.privacy = Boolean(on);
  if (state.privacy) {
    state.privacySalt = newPrivacySalt();
  } else {
    state.privacySalt = "";
  }
  try {
    localStorage.setItem(PRIVACY_KEY, state.privacy ? "1" : "0");
    if (state.privacy) localStorage.setItem(PRIVACY_SALT_KEY, state.privacySalt);
    else localStorage.removeItem(PRIVACY_SALT_KEY);
  } catch {}
  syncPrivacyBtn();
}

function syncRangeMenu() {
  const btn = $("#rangeBtn");
  const menu = $("#rangeMenu");
  const custom = $("#rangeCustom");
  if (!btn || !menu) return;
  btn.textContent = rangeLabel();
  $$("#rangeMenu [data-range]").forEach((el) => {
    el.classList.toggle("on", el.dataset.range === state.range);
  });
  custom.hidden = state.range !== "custom";
  if (state.customFrom) $("#rangeFrom").value = state.customFrom;
  if (state.customTo) $("#rangeTo").value = state.customTo;
}
function closeRangeMenu() {
  $("#rangeMenu").hidden = true;
}
$("#rangeBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("#rangeMenu").hidden = !$("#rangeMenu").hidden;
  syncRangeMenu();
});
$("#rangeMenu").addEventListener("click", (e) => e.stopPropagation());
$$("#rangeMenu [data-range]").forEach((el) => {
  el.addEventListener("click", () => {
    state.range = el.dataset.range;
    $("#rangeCustom").hidden = state.range !== "custom";
    syncRangeMenu();
    if (state.range !== "custom") {
      closeRangeMenu();
      render();
    }
  });
});
$("#rangeApply").addEventListener("click", () => {
  state.customFrom = $("#rangeFrom").value;
  state.customTo = $("#rangeTo").value;
  if (!state.customFrom || !state.customTo) return;
  if (state.customFrom > state.customTo) {
    const t = state.customFrom;
    state.customFrom = state.customTo;
    state.customTo = t;
  }
  state.range = "custom";
  closeRangeMenu();
  syncRangeMenu();
  render();
});
document.addEventListener("click", closeRangeMenu);
syncRangeMenu();
syncPrivacyBtn();
$("#privacyBtn").addEventListener("click", () => {
  setPrivacy(!state.privacy);
  refreshHint().catch(() => {});
  render({ quiet: true });
});
refreshHint();
render();
