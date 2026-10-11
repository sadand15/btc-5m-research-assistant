# Binance 现货五分钟方向

本分支只预测 Binance Spot BTCUSDT **当前 UTC 五分钟桶**最终 close 相对 open；不是从点击时刻开始向后五分钟。
这与冻结模型 `v2-9e452c59ebf7` 的训练目标匹配，不以 Predict.fun/Chainlink 兼容性阻断。

UP 表示 close > open。冻结负类是 close <= open，因此 DOWN 在页面中明确解释为“下跌或持平”；没有严格下跌或平盘的独立概率。
WAIT 是不展示方向的门控状态，不是第三种价格标签。概率是模型输出，不是保证胜率。

运行（安装原 requirements，使用项目 Python 环境）：

```powershell
python scripts/start_binance_direction.py
```

默认 `http://127.0.0.1:8767`，独立于原 Dashboard 与生产服务；每五秒尝试更新。
模型位于忽略的 `runtime/binance-model.joblib`，只接受 SHA256
`5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f`。
本机已从原冻结备份只读复制；新 clone 必须提供同一可信本地模型，可用 `--binance-model PATH`。
模型文件、训练器、calibration、旧配置均未改变。无凭证、账户、交易或观察数据库。

使用公开 Binance `/api/v3/klines`，UTC `1m` 与 `1s` 数据。
见 [官方接口定义](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)。
分钟历史必须连续；当前部分分钟只由已结束的秒线聚合，不使用最终完整分钟冒充中途快照。
接受交易所实际返回的零成交秒线，但要求零成交量及平坦 OHLC；缺失的秒线仍拒绝，不在本地补造。
预测输入时间为最后已结束秒的 close time，接收时间单独记录；请求和推理结束后检查年龄及周期。
REST 没有独立发布时刻，因此这里的接收时间不宣称为交易所发布时刻。

沿用 .70/.30 概率展示门槛、剩余 30–180 秒、训练采样支持检查；无调参或新的有效性声明。
模型失败、缺行情、数据年龄超过十秒、跨周期或概率不足时 WAIT。浏览器与后端都检查过期。
预测定时任务单线程，无排队推理；超慢计算的结果在返回后丢弃，UI 期间自动过期为 WAIT。

未调用原 V2 app、paper engine 或任何 venue 接口；不读取盲测表现。
这使实时研究预测可用，不证明复杂模型超过 naive baseline，也不证明费用后的交易优势。

本地验收：完整测试 1193 passed、2 skipped；95 个保护文件哈希一致；暂存凭证扫描零发现。
公开 Binance 行情的真实推理已跑通。本机 Edge 验证方向卡片及断连撤下概率/回到 WAIT 通过。
验收数值仅描述功能测试，不表示真实方向准确率。
