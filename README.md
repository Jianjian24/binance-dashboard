# Ledger

本机交易日记。用来看自己的历史成交、做复盘，不是交易软件，也不提供投资建议。

数据、密钥都留在你这台电脑上：页面只监听 `127.0.0.1`，不上传第三方。需要时可用只读 API 从交易所把成交拉到本地 SQLite。第三方依赖只有 `python-binance`。

> 市场有风险。本项目不荐标、不承诺收益、不代操作。盈亏数字只反映你自己已经发生的记录。

## 能做什么

- 首页总览：账户权益、胜率、盈亏曲线、近四周日历、当日已平仓
- 复盘页：按日笔记、品种 / 时段分解、已平仓轮次列表
- 隐私模式：右上角 Hide Balances，金额与笔数打成 `*`，截图更安心
- 原始数据：本地成交、资金流水、合成轮次，方便自己核对

不会帮你下单，也不会把数据发到云端。

## 环境

Python 3.10+。建议用虚拟环境：

```powershell
cd E:\code\binance-dashboard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env` 后填入**只读**权限的 API Key（不要开交易 / 划转权限）：

```powershell
copy .env.example .env
notepad .env
```

```
BINANCE_API_KEY=your-key
BINANCE_API_SECRET=your-secret
PROXY_TYPE=NONE
```

启动时会自动读取仓库根目录的 `.env`。终端或系统里已经有的变量优先，不会被覆盖。`.env` 已被 gitignore，请勿提交、勿发给任何人。

走本地代理时把 `PROXY_TYPE` 设为 `CLASH`，需要的话再写 `CLASH_HTTP_PROXY`。

## 启动

```powershell
python -m journal.server --port 8765
```

或双击 `journal\start.bat`。浏览器打开 <http://127.0.0.1:8765>。

左侧绿色按钮：从交易所增量同步成交。按住 Shift 再点：全量扫描并申请历史成交归档（第一次使用或要补更早记录时）。

更细的接口、统计口径和标签规则见 [`journal/README.md`](journal/README.md)。

## 说明

- 仅供个人记录与复盘，请遵守你所在地的法律法规，以及交易所用户协议。
- 统计可能和交易所 App 有分位差，以官方账单为准。
- 本仓库不收集用户数据。
