# BTC 5 分钟实时交易研究助手

Python 3.11+，公开 Binance BTCUSDT 行情，**PAPER TRADING ONLY**。实现行情、周期聚合、因果特征、LightGBM/Logistic 概率、独立校准、模拟交易、SQLite、时间顺序回测和 Streamlit。无需 API Key，代码中没有真实下单接口。

本机首轮实测、模型比较和明确能力边界见 **[FIRST_RUN.md](FIRST_RUN.md)**。如需复现已验证的依赖组合，使用 `pip install -r requirements.lock.txt`；该锁文件记录本机 Python 3.12 环境。

## 快速运行

Windows PowerShell，进入本目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

本机已创建 `.venv` 时直接运行最后一行，或 `powershell -ExecutionPolicy Bypass -File .\start.ps1`。
通用环境可使用 `pip install -r requirements.txt`、`python app.py`。

首次无模型时，自动下载最近 14 天已结束 1m K 线，构造训练样本，按时间训练、校准、测试并保存模型，然后启动 WebSocket 和本地页面：**http://localhost:8501**。首次特征生成需要几分钟。已有模型时直接启动，不会悄悄用新测试集重新训练。Ctrl+C 停止行情与其启动的页面进程。不要在同一数据库上同时启动多个行情进程。

```powershell
# 分阶段运行；下载增加数据，按 timestamp 去重
.\.venv\Scripts\python.exe app.py download --days 30
.\.venv\Scripts\python.exe app.py train
.\.venv\Scripts\python.exe app.py backtest
# 无界面 / 有限时间联调
.\.venv\Scripts\python.exe app.py --no-dashboard --seconds 60
# 单独启动只读界面
.\.venv\Scripts\python.exe -m streamlit run dashboard.py --server.address 127.0.0.1
# 测试
.\.venv\Scripts\python.exe -m pytest -q
```

`--config path/to/config.yaml` 适用于全部 CLI 命令；界面自定义配置：`streamlit run dashboard.py -- --config path/to/config.yaml`。文件路径相对配置文件解析。`config.yaml` 包含概率阈值、时间窗口、波动/趋势/价差过滤、采样间隔、假设赔率和模型参数。

## 预测的确切含义

预测 **当前 UTC 对齐五分钟周期的收盘价是否高于该周期的开盘价**，不是从当前时刻再向后滚动五分钟。当前周期从 `floor(exchange_timestamp / 300000) * 300000` 开始；结算价来自该周期五根完整 1m K 线的最后收盘价。开盘必须来自周期第一根 1m K 线，不用程序启动价格替代。

严格事件：`UP = close > open`；模型补概率 `1-P(UP)` 包含 `close <= open`。页面将第二项标注为 DOWN / non-UP。价格相等在方向标签中属于 non-UP，但模拟交易双方均 **VOID**，退还本金，仅扣配置手续费。数据库保留 TIE，而不是把持平谎记为下跌获胜。

## 数据与时间正确性

- 使用官方 market-data-only REST 和 WebSocket 域名，只订阅 `kline_1m`、`depth20@100ms`。K 线流约两秒更新，模型默认每两秒更新一次；不宣称逐笔成交延迟。5m/15m 从同一基础流聚合，不重复订阅。
- 订单簿用完整 top-20 快照，以 update ID 去重，计算 top-5/top-10 数量、价差和 OBI。不是误用 diff-depth 增量的伪订单簿。
- 同分钟快照替换，成交量不累加重复消息；已结束 K 线不被未结束快照覆盖；先检查连续性再聚合。缺口不会前向填充，也不会静默当作零波动。
- 启动、重连和每分钟通过 REST 修复；断线指数退避，自动响应 WebSocket ping/pong；过期行情停止入场，页面显示 STALE。服务器时间估计本机时钟偏移，周期基于交易所事件时间。
- 缺失结算数据的交易保持 PENDING；恢复后用完整五分钟 K 线结算。SQLite 唯一周期约束和事务保证重启后不重复交易、不重复结算。
- 技术指标用最近 90 根完整 1m K 线；当前价格、当前分钟累计量、开盘距离、剩余秒数使用当时快照。VWAP 是滚动 20 根 1m 典型价格加权值；RV 是完整分钟对数收益平方和的平方根；`sigma_5m_price = cycle_open * std(last30 minute log returns) * sqrt(5)`；Z 无量纲。1m RV 为上一根完整分钟绝对对数收益，不是逐笔实现波动率。
- 15m 趋势来自相邻两根完整、UTC 对齐 15m K 线的收盘收益；1m/5m momentum 参与入场确认。订单簿只做实时辅助/价差过滤，未被假装成已有历史训练特征。

## 历史数据能力边界：不要把分钟数据冒充秒级数据

第一版下载 1m 历史并聚合 5m/15m，样本位于每轮已过去 **60、120、180、240 秒**（最后一根毫秒时间戳近似为整秒）。第五分钟收盘已经揭晓答案，绝不作为待预测样本。历史特征调用与实时相同的函数，不插值生成虚假的秒线或订单簿。

模型持续显示概率，但首轮校准证据只覆盖上述分钟收盘附近。默认仅在这些时间点**之前四秒内**允许入场，其他秒位显示 `OUTSIDE_CALIBRATION_TIME_SUPPORT`。分钟刚开始的快照不因接近上一个分钟收盘而获得支持。这保证仍然持续监测，而不把未经验证的秒位当成已校准结果。放宽配置容差属于新的研究假设，需后续秒级历史或实盘采样验证。

实时 `predictions.features` 保存每次特征与当时订单簿，`outcomes` 保存真实周期结果，可按 cycle_id 连接开展未来秒级训练；**第一版尚不提供录制样本自动再训练，也不提供历史深度回放**。

## 训练、校准、回测

按完整 cycle_id 排序分组：最早 60% 训练，中间 20% sigmoid 校准，最后 20% 测试，无 shuffle、同周期不跨分区。校准用冻结的已拟合模型，校准集不参与基础模型训练。三种模型都报告独立测试结果：

1. `distance_time`：只使用领先幅度和剩余时间的 Logistic 基线。
2. `logistic`：标准化后的全特征 Logistic Regression。
3. `lightgbm`：预设小树模型，默认实时使用该模型，不按测试表现自动挑选。

还报告训练上涨先验、当前价格所在开盘方向的固定置信度参照，以及扩展窗口 walk-forward（重新训练和重新校准）。报告 accuracy、precision、recall、F1、Brier、log loss、校准桶、时间/概率分组、置换重要性。高于常数先验并不意味着技术指标有效，应同时比较 distance_time，且后者已使用周期内实际发生的价格运动。

`app.py backtest` 拒绝使用模型校准截止之前的样本，只回放保留测试期和更晚的数据。每轮至多一笔，允许 NO TRADE，统计胜负、持平、最大回撤、profit factor、按入场置信度和剩余时间分组。空交易桶为 null，不捏造零样本胜率；profit factor 无损失分母时为 null。

**OHLCV 回测显式跳过订单簿/价差过滤，因此不等同完整实时策略回放。** 历史 minute-close 采用理想观察时刻，未模拟网络延迟。盈亏为固定 stake 的假设二元合约单位（默认赢 +1、输 -1），不是 BTC 现货做多做空收益，也不是任何预测市场的可执行收益。赔率、手续费、初始权益均可配置，无真实买卖价或实际成交模型。

重要性只作测试集上的探索性排名，不反馈筛选特征；没有调参寻优。周期内四个样本相关，不能把样本数当作独立观察数。当前报告不含块 bootstrap 置信区间；短历史胜率不能证明持久信号。

## 项目结构与持久化

```text
app.py                 下载/训练/回测/实时统一入口与页面生命周期
dashboard.py           Streamlit，只读数据库，图表/倒计时/校准
config.yaml            所有交易阈值及运行参数
btc5/config.py         配置与校验
btc5/data.py           Candle、聚合、历史 REST、订单簿
btc5/features.py       共享的因果特征实现
btc5/database.py       SQLite WAL、幂等写入
btc5/research.py       数据集、三种模型、校准、walk-forward、回测
btc5/strategy.py       独立 Entry Engine、Paper Engine
btc5/live.py           WebSocket、补缺、实时推断调度
tests/test_core.py     数据完整性、泄漏、时间切分、结算测试
runtime/               本机生成，gitignore
```

`runtime/research.sqlite`：candles、predictions、trades、outcomes、state。
`runtime/model.joblib`：模型、特征列、模式版本、数据指纹、训练配置、校准截止时间。
`runtime/report.json`：完整研究报告；`heldout_samples.csv`、`backtest_trades.csv`：可审查测试数据/交易；`backtest.json`：独立回测结果；`research.log`：轮转日志。

## 运行故障与后续方向

网络无法访问 Binance 时会记录错误并重试，不自动切换为虚构数据。如果首次下载失败，修复网络后重新运行；历史和模型不会假装已经可用。终端只认不到 python 时可直接使用上面的 `.venv\Scripts\python.exe`。页面端口已占用时修改 config 的 dashboard.port，或单独启动页面。

后续优先级：① 加入真实 1s/逐笔历史和订单簿录制重放，覆盖所有剩余秒位并统一历史/实时策略；② 延长历史、按市场状态做滚动测试及周期块 bootstrap，比较 distance/time 基线与技术指标增量；③ 接入只读二元市场报价，按可成交赔率、价差与费用计算期望收益，保留纯模拟执行。

API / 校准依据：[Binance public market data](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)、[WebSocket streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)、[scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html)。
