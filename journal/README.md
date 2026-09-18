# Ledger：本机交易日记

个人复盘看板，只跑在本机。成交、资金流水和 API Key **不会上传到任何第三方**。数据存在 `journal/data/ledger.sqlite`。

这是记录工具，不是交易策略，也不构成投资建议。页面入口：`http://127.0.0.1:8765`（只绑定回环地址）。

## 启动 / 关闭（推荐）

Windows 下直接双击 `journal/` 里的脚本：

| 文件 | 作用 |
|------|------|
| `start.bat` | 启动看板，并打开浏览器（已在跑则只打开页面） |
| `stop.bat` | 关闭占用 8765 的 journal 进程 |
| `restart.bat` | 先停再启 |

`start.bat` 会：
- 先读仓库根目录 `.env`，没有再读系统环境变量 `BINANCE_API_KEY` / `SECRET`，再回退 `BINANCE_API_KEY_TRADE`
- 不默认开代理。只有已经设置 `PROXY_TYPE=CLASH` 时才走 `CLASH_HTTP_PROXY`（默认 `http://127.0.0.1:7890`）
- 在仓库根目录运行 `python -m journal.server --port 8765`

也可把 `start.bat` / `stop.bat` 固定到任务栏或建桌面快捷方式。

### 配置密钥

推荐：复制仓库根目录 `.env.example` 为 `.env` 后填入（已 gitignore）：

```
BINANCE_API_KEY=your-key
BINANCE_API_SECRET=your-secret
PROXY_TYPE=NONE
```

`python -m journal.server` 启动时会自动加载 `.env`。进程里已有的环境变量优先，不会被覆盖。

### 命令行（可选）

不写 `.env` 时，也可在仓库根目录临时设置：

```powershell
$env:BINANCE_API_KEY = "your-key"
$env:BINANCE_API_SECRET = "your-secret"
# 需要代理时再打开：
# $env:PROXY_TYPE = "CLASH"
# $env:CLASH_HTTP_PROXY = "http://127.0.0.1:7890"
python -m journal.server --port 8765
```

本地必须能访问币安。直连设 `PROXY_TYPE=NONE`（默认）。走 Clash 时设 `PROXY_TYPE=CLASH`。

需要环境变量（只读合约权限即可）：

| 变量 | 用途 |
|------|------|
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | 拉 userTrades、income、持仓、订单 CID。也认旧名 `*_TRADE` |
| `PROXY_TYPE` | `NONE`（默认，直连）或 `CLASH` |
| `CLASH_HTTP_PROXY` | `PROXY_TYPE=CLASH` 时的代理，默认 `http://127.0.0.1:7890` |

启动后打开：

- Home：`http://127.0.0.1:8765/#/home`
- Raw data：`http://127.0.0.1:8765/#/rawdata`

左侧绿色刷新按钮：从币安增量同步。**按住 Shift 再点** = 全市场扫描 + 申请最近 1 年成交归档（第一次、漏品种、或要补 3 个月以前的成交时用）。Python 流程改过后需要重启服务，前端改动 Ctrl+F5 即可。

## 页面

| 路由 | 内容 |
|------|------|
| `#/home` | 权益、胜率、近 4 周日历、今日已平仓、区间已实现盈亏 / 按日 TWR、实时持仓、最近 3 笔；右上角隐私模式 |
| `#/dashboard` | 区间净盈亏、品种 / 标签分解 |
| `#/analytics` | 回撤、持仓时长、时段、星期 |
| `#/calendar` | 按平仓日的月历；可写当天笔记 |
| `#/journal` | 已平仓轮次列表 |
| `#/rawdata` | SQLite 原始表：Fills / Income / Roundtrips |

右上角时间范围默认 **All time**。Home 的「今日」和「最近 3 笔」**不受这个范围影响**：今日按上海自然日，Last 3 按最近平仓时间。右侧「区间收益」跟随右上角范围，仍是已实现净盈亏金额。「收益率」是按日时间加权（TWR）：按上海自然日链接，`TRANSFER` 只改本金、不算收益，同日入金后的交易按新本金计。不再用「区间盈亏 / 期初权益」（会把后半段用大本金赚的钱算在期初小本金上）。划转以本地已同步的 income 为准，刷新后才计入。

Home 的 Open positions 以币安全仓位接口为准：返回空列表就是没有持仓，不会再拿历史成交品种逐个查询。Side & Size 是 `数量 × 开仓价` 的名义金额（两位小数）。

## 数据怎么来

1. 币安 U 本位 `userTrades`（按 symbol 的 `fromId` 翻页）。接口大约只能查**近 3 个月**；只传 `startTime` 经常只有约 7 天。
2. `income` 用来发现品种；持仓接口用来发现当前还在交易的合约。
3. 第一次全市场扫描后，本地记住品种列表，之后增量拉。
4. **3 个月以前**的成交走官方成交归档 `trade/asyn`（最长约 1 年，每月约 5 次）。Shift+同步会申请最近 1 年归档。CSV 时间列是 `Time(UTC)`，手续费是 `0.22038800 USDT` 这种带单位的字符串。下载副本在 `data/last_archive.bin`（已 gitignore），解析失败时可直接重导，不必再打归档接口。
5. 本地用成交合成 **roundtrip**（一方向从 0 开到 0 平，对齐币安「仓位历史」）。对冲模式下 LONG / SHORT 各自归零，不会把平空当成开多。

盈亏与展示：

- 轮次 `net_pnl` = 成交 `realizedPnl` 之和 − 手续费。和币安「已实现盈亏」通常差 1–2 分（四舍五入）。
- 日历 / 今日统计按 **平仓时间、Asia/Shanghai**。未平仓不算进去。月份条只出现「有已平仓」的月份。
- Home 的 Open positions 来自币安实时持仓；接口返回空即无仓，不再用历史品种逐个补查。Side & Size 是 `数量 × 开仓价` 的名义金额（两位小数），不是取整美元。
- Home 右侧「区间收益」跟随右上角时间范围（已实现净盈亏金额）。「收益率」= 按日 TWR：每个资金时点 `r = 交易盈亏 / 当时权益`（划转只加减本金），再按上海自然日把 `(1+r)` 连乘。入金后的交易计入新本金。接口 `GET /api/twr?from=&to=&wallet=`。

## 策略标签

`userTrades` 和成交归档都**没有** `clientOrderId`。同步后会用 `allOrders` 回填 CID（官方只给**近 90 天**），再按前缀打标：

| 前缀 | 标签 |
|------|------|
| `GRIDB` / `GRIDN` / `GRIDT` | `GRID` |
| `MMBL` / `MMSH` / `MMCL` / `MMMC` | `MM` |
| `TRAPO` / `TRAPSL` / `TRAPTP` | `TRAP` |
| `MSG` / `MSGT` | `SCALP` |
| 对不上（含币安默认 `x-Cb7ytekJ…`） | `OTHER` |

90 天以前的成交无法回填 CID，会一直是 `OTHER`。增量同步不会用空 CID 把已经打上的标签盖掉。一轮里只要有成交带策略前缀，轮次标签就用策略名，不会因为夹了一笔 OTHER 就变成 OTHER。

## 调试

Raw data 页可按品种、`side`、`positionSide` 过滤，搜索 `trade_id` / cid。  
「重算 roundtrips」只重跑本地撮合，不访问币安（`POST /api/rebuild`）。

核对仓位时：先在 Raw data 看 Fills 是否已有对应成交，再看 Roundtrips 是否按 LONG/SHORT 各自平完。

## 文件

```
journal/
  server.py          HTTP，仅 127.0.0.1
  binance_sync.py    拉币安 + 归档 + CID 回填 + 重建轮次
  match.py           对冲/单向仓合成
  queries.py         统计与分页
  db.py              SQLite
  tags.py            cid → 策略标签
  static/            前端
  data/ledger.sqlite 本地账本（已 gitignore）
  data/last_archive.bin  最近一次成交归档（已 gitignore）
```

常用接口：`GET /api/health`、`/api/summary`、`/api/twr`、`/api/raw?kind=fills|income|roundtrips`、`POST /api/sync`、`POST /api/rebuild`。
