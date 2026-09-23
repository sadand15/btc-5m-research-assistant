# V2 验收记录

## 前瞻观察更新：2026-09-23

规则核对与固定七天窗口已设置，详见 [FORWARD_VALIDATION.md](FORWARD_VALIDATION.md)。新增预测完成时间、盘口联合记录、等待原因、未知结算原文和冻结检查，52 项测试通过。当前仍不把 Binance 模型当作已对 Chainlink 目标校准的模型。

## 后续接入更新：2026-09-23 11:53（北京时间）

用户提供的开发者 Key 已通过只读主网探测；后台服务已重启并显示 `venue_status=CONNECTED`、`quote_data_mode=LIVE DATA`，真实盘口开始录制。示例市场 ID 2536672，五分钟 BTC UP/DOWN，价格源为 CHAINLINK，市场 feeRateBps=200（不是固定按成交额 2% 计费）。当前 Binance 模型与市场价格源不同，仍保留拒绝跨源模拟入场的保护。

Key 只在当前后台服务的进程环境中，未持久化到配置、代码或数据库。今后从其他终端重启，需在该终端重新设置环境变量。以下“尚缺 Key”段落保留为本轮初始验收历史，接入状态以本更新为准；仍未据此验证真实收益。

2026-09-23，本机 Windows / Python 3.12，基于现有项目迭代，没有重新搭建项目。

## 本轮实跑

- `python -m pytest -q`：**46 passed**。覆盖旧版回归、cycle 分区、未来价格扰动、测试标签不影响校准、时间边界、微观特征历史/实时一致性、single-flight、超时后不重复派发、逐源过期、报价复核、断线重连、恢复、去重、费用、买卖侧与延迟模拟。
- `python scripts/verify_dashboard.py`：**8 metrics / 3 tabs / 18 tables**，没有渲染异常。研究页面包含多个 Plotly 图形与二维热图。
- `python v2.py research`：实际完成 14 天秒线 / 5 秒观察与 90 天分钟线研究；基础模型、微观特征对照、三种校准方式、三个无重叠滚动测试窗口都重新拟合，未进行超参数搜索。
- `python scripts/audit_original.py`：原始 V1 数据 SHA256 完全匹配；原 3,212 测试样本模型 accuracy 74.7821%，Naive 74.6264%。完整 cycle 分区无交集。
- `python app.py backtest`：部署模型 `v2-9e452c59ebf7`，数据指纹一致；47,613 测试样本，accuracy **73.7782%**，Brier **0.17032008**。V2 不再在此命令中调用旧固定赔率收益模型。
- `python v2.py paper`：0 / 100 / 250 / 500 / 1000ms、费用归零、固定滑点、波动相关滑点、spread 加倍全部运行，写入独立模拟账本。全部 **SIMULATED QUOTE**，不是 predict.fun 实际报价。零延迟 179 笔、净模拟结果 −21.83464；500ms 168 笔、−39.18672。
- 只读网页 `/api/state` 确认 Binance **CONNECTED**，新模型已加载，Distance-Time / Logistic / LightGBM 与 micro 对照均返回概率；Naive 仅显示方向。
- 电脑通过 Wi-Fi IP 访问 `http://PC-LAN-IP:8502/` 返回 **HTTP 200**。尚未收到 iPhone / iPad 实机成功确认。

## 数据与工件

- 原始 V1 审计：`runtime/v2/original_v1_audit.json`。
- 秒级研究：`runtime/v2/seconds/report.json`、`heldout.parquet`、`walkforward.parquet`、`observations.parquet`。
- 90 天研究：`runtime/v2/regimes/` 下对应文件。
- 模拟场景：`runtime/v2/paper_scenarios.json`，独立 SQLite：`runtime/v2/paper.sqlite`。
- 当前实时审计：`runtime/research.sqlite` 中 `audit_v2` 与原 `predictions`、`venue_*` 表。
- 完整分析及 25 项回答：[V2_REVIEW.md](V2_REVIEW.md)。旧 [FIRST_RUN.md](FIRST_RUN.md)、[SECOND_RUN.md](SECOND_RUN.md) 为历史结果，不替代本次 Review。

## 使用

```powershell
# 重新训练与评估；使用已有校验过的缓存
.\.venv\Scripts\python.exe v2.py research
# 独立无 Key 模拟执行
.\.venv\Scripts\python.exe v2.py paper
# 更新可读 Review
.\.venv\Scripts\python.exe scripts\v2_review.py
# 启动或重启后台
powershell -ExecutionPolicy Bypass -File .\start-background.ps1
```

电脑完整研究页：[Streamlit](http://localhost:8501/)。手机同 Wi-Fi：[轻量页面](http://PC-LAN-IP:8502/)。IP 改变时应使用电脑当前 Wi-Fi IPv4。

## 尚未实证的部分

predict.fun 主网 API Key 尚未获得。已按用户要求打开 [官方开发者控制台](https://developers.predict.fun/)，但当前会话没有已登录浏览器的点击控制工具，未完成登录或生成 Key。缺 Key 时实时 BTC 监控、训练、回放、模拟执行与 Dashboard 均正常运行；真实盘口功能显示禁用。

取得行情 Key 后，在本机 PowerShell 配置并重启（不发到聊天）：

```powershell
$env:PREDICTFUN_API_KEY = '在本机填写行情Key'
.\.venv\Scripts\python.exe venue.py probe
powershell -ExecutionPolicy Bypass -File .\start-background.ps1
```

没有真实历史 L2、predict.fun 回执或平台结算数据时，不得将合成执行结果用作盈利证据。毫秒模拟只验证机制；实际费用扣除单位、舍入、队列竞争和盘口到成交的可用数量仍待实证。

完成本轮 V2 后停止加功能，没有开始 V3。
