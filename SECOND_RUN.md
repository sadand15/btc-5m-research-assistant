# V2：秒级回放、跨阶段验证、predict.fun 报价模拟

本轮在已有项目上完成，旧版报告及模型保留在 `runtime/report.json` 和 `runtime/model.joblib`。当前配置改用 `runtime/seconds/model.joblib`，不再把分钟收盘附近作为唯一可观察时间。

## 真实秒级回放

数据来自 Binance 官方每日 **1s K 线 ZIP**，逐文件核对官方 SHA-256；处理 2025 年起档案的微秒时间戳，统一成毫秒。记录来源、校验值、行数和缺口。

本次研究区间：**2026-09-08 至 2026-09-22（UTC，右端不含）**，另下载前一天用于热身。共 1,209,600 根研究区间秒线，4,032 个完整五分钟周期，按每 5 秒采样生成 **237,888 条样本**。底层每秒数据都参与当前分钟 OHLCV 累计；没有用分钟最终高低价填充早期快照。

支持 `--step 1` 输出逐秒样本。本次训练步长选 5 秒以控制重复样本量，时间支持点为已过去 5、10、…、295 秒。模型持续运行；入场仍检查真实采样网格、行情新鲜度和策略条件。此处“支持附近”不代表每个秒位都有独立校准证据。

```powershell
.\.venv\Scripts\python.exe research.py seconds --days 14 --step 5
# 如需严格逐秒采样，改为 --step 1
# 将训练发布到 config.yaml 的模型路径，可追加 --publish
```

完整数据集和逐日样本：`runtime/seconds/samples.parquet`、`samples-日期-5s.parquet`。

| 秒级实验模型 | 独立测试准确率 | Brier |
|---|---:|---:|
| 距离/剩余时间 | 74.01% | 0.16916 |
| 全特征 Logistic | 74.07% | 0.16804 |
| LightGBM | 74.04% | 0.16976 |

独立测试 807 个周期，每周期 59 个样本。LightGBM 剩余 **30 秒**：准确率 **89.34%**，Brier **0.07780**；剩余 **180 秒**：准确率 **69.64%**，Brier **0.20169**。前者已观察到更多本轮价格运动，不能理解为从周期开盘就有 89% 预测能力。

秒级实验只有 3 个测试日期块；LightGBM 相对距离/时间基线的 Brier 差值 95% 日块区间约 **[-0.00200, +0.00289]**，未显示稳定增益。

## 90 天跨行情阶段验证

研究区间：**2026-06-24 至 2026-09-22（UTC，右端不含）**。使用 129,600 根真实分钟线，25,920 个五分钟周期，103,680 条样本。该实验扩大时间跨度，与秒级实验分别报告，不能把分钟实验的证据当作覆盖全部秒位。

```powershell
.\.venv\Scripts\python.exe research.py regimes --days 90
.\.venv\Scripts\python.exe evaluate.py all
```

新增诊断包括：

- 最早 60% 训练、中间 20% 校准、最后 20% 测试；同周期不跨分区。
- 三个扩展窗口分别重新拟合三种模型，保存各窗口预测和校准截止时间。
- 按月份、过去 24h 上涨/下跌/横盘、过去 24h 高/中/低波动、确切剩余秒数分组。
- 波动分位阈值只从对应训练期学习；趋势阈值固定为过去 24h ±1%。缺少连续 24h 数据标为不足，不补造行情状态。
- 按 UTC 日期整块重采样 500 次，所有模型使用同一组抽样比较 Brier；周期内部相关样本不被当作独立样本。

| 90 天实验模型 | 独立测试准确率 | Brier |
|---|---:|---:|
| 距离/剩余时间 | 74.40% | 0.17051 |
| 全特征 Logistic | 74.16% | 0.16964 |
| LightGBM | 74.47% | 0.16942 |

独立测试 5,184 个周期、18 个日期块。LightGBM 相对基线的 Brier 差值 95% 日块区间约 **[-0.00187, -0.00048]**：这一段样本有小幅改善，但幅度不大，也不是可交易收益证明。日期块仍可能相关，区间不是保证；完整滚动窗口对照见 `runtime/regimes/validation.json`，逐样本预测见 `walkforward_predictions.parquet`。

90 天实验的三个滚动测试窗口中，LightGBM / 简单基线的 Brier 分别是 **0.17167 / 0.17266、0.15890 / 0.15756、0.17296 / 0.17447**。第二个窗口反而变差，因此不能概括为所有行情阶段都有效。

## predict.fun 只读报价与模拟成交

已按 predict.fun 官方 API schema 实现 GET-only 适配器，**没有签名、钱包或真实下单代码**。

已实现：市场分页发现、BTC 身份与五分钟时间窗校验、UP/DOWN 映射校验、官方 `feeRateBps`、YES/NO 深度转换、完整快照录制、延迟后的新快照成交、逐档消耗深度、价格上限、部分成交、手续费、期望收益过滤、重启恢复、真实平台结果结算和录制数据回放。

其中：

- 买 NO/DOWN 的卖盘来自 YES 买盘的 `1-price`，数量对应原档位，不把 YES ask 错当 DOWN ask。
- 费用公式为 `shares × feeRateBps / 10000 × min(price,1-price)`；费率取市场元数据，不固定假设为 2%。默认无邀请折扣。
- 默认以股份扣费模拟，支持 `fee_deduction: collateral` 做对照；**扣费单位和数量舍入目前属于显式模拟假设，尚未取得实际账户成交回执核对**。
- 默认预算 10 USDT、至少 0.10 USDT 模型期望优势、500ms 最小延迟、1% 最大价格偏移；信号时冻结限价，不能事后用较差价格反推一个“已成交好单”。实际录制为 REST 约 2 秒轮询，因此有效模拟延迟可能大于 500ms。
- 只消费延迟之后源时间也更新的深度，旧快照不充当未来成交证据；深度不足可部分成交，零成交不记为赢。
- Binance 模型与平台预言机/开盘基准不一致时默认 WAIT。`allow_basis_risk: true` 可显式开展跨价格源代理实验，但结果仍标为 Binance proxy，不能声称概率已为 predict.fun 校准。
- 只接受平台明确 RESOLVED 的结果；不以 Binance 收盘替代，不凭相等的 startPrice/endPrice 猜测取消或 50/50 支付。模拟器支持明确给出的分摊支付比例；当前 API 没有明确可识别的分摊字段时保持待结算。

当前实际阻塞：本机未配置 `PREDICT_API_KEY`，主网匿名探测返回 **401**。因此本轮 **没有取得 predict.fun 真实盘口，也没有真实报价成交收益结果**。程序显示 `PREDICT_API_KEY_MISSING` 并 WAIT，回放显示 `NO_RECORDED_QUOTES` / PnL null；测试用的构造盘口仅存于测试临时库，不混入研究数据库。

在自己的 PowerShell 中配置行情开发者 Key 后启动（不要发到聊天）：

```powershell
$env:PREDICT_API_KEY = '在本机填写开发者行情Key'
.\.venv\Scripts\python.exe venue.py probe
powershell -ExecutionPolicy Bypass -File .\start-background.ps1
```

主程序自动启动报价录制与模拟成交；无需同时运行第二个录制进程。也可仅执行 `venue.py record`，或用 `venue.py replay` 重放已录制报价。`up_index_set` 默认空；平台只给 Yes/No 且无法明确识别 UP 时，需核对题意后设置，系统不会猜测。

新增数据库表：`venue_markets`、`venue_books`、`venue_orders`、`venue_outcomes`。旧版固定赔率交易仍保留在 `trades`，配置 `execution_mode: predictfun` 后不再新增旧式交易。历史研究报告中的固定赔率回放属于单独对照，不能与实际盘口模拟混在一起。

## 手机白屏处理与运行

新增 **8502 端口**的服务器直接生成 HTML 页面；首个响应已包含价格、概率、研究结果和报价状态，不依赖 JavaScript、CDN 或 WebSocket，每五秒刷新。8501 的 Streamlit 研究页仍保留。

```powershell
# 前台运行，Ctrl+C 停止
.\.venv\Scripts\python.exe app.py
# 后台启动或重启当前项目服务
powershell -ExecutionPolicy Bypass -File .\start-background.ps1
```

手机连接电脑相同 Wi-Fi 后打开 `http://电脑局域网IP:8502`。电脑端 HTTP 检查不等于已经从 iPhone/iPad 验证；如果新页面也完全无法返回内容，还需要检查无线接入点的客户端隔离或设备是否真在同一可互通网络。

## 验证与官方依据

运行 `.\.venv\Scripts\python.exe -m pytest -q`。测试覆盖秒级未来数据扰动不改变当前特征、缺秒拒用、微秒规范化、UP/NO 订单簿映射、费用、预算上限、延迟/旧快照/滑点、期望值、预言机与开盘价约束、重启恢复、录制回放一致性和无脚本 HTML。

本轮已实跑 **30 项测试全部通过**，Streamlit 页面测试通过，独立秒级回测通过数据指纹校验并复现 47,613 个测试样本。后台已加载 `lightgbm-f32e64fe1444`，Binance 连接为 CONNECTED。电脑端访问 Wi-Fi 地址 `http://PC-LAN-IP:8502/` 返回 HTTP 200，首个响应含完整页面；尚未获得用户设备访问成功的确认。

官方依据：[Binance 档案与微秒说明](https://github.com/binance/binance-public-data)、[predict.fun API 与主网 Key 要求](https://dev.predict.fun/)、[YES/NO 订单簿结构](https://dev.predict.fun/doc-685654)、[官方费用公式](https://predict.fun/id/news/revealed-polymarket-sports-markets-can-be-twice-as-expensive-as-predicts)、[市场字段](https://dev.predict.fun/market-14037477d0)、[价格源字段](https://dev.predict.fun/cryptoupdownvariantdata-14037469d0)。
