# Predict.fun 选边目标恢复审计 · 2026-11-05

状态：**目标未完成，真实选边 NOT_READY**。本轮是恢复后的第一轮实证检查，不把 Binance 页面、合成测试或固定 WAIT 当成目标完成。

## 当前权威状态

独立分支 `codex/predictfun-evidence-gates` 从 `bd12c2a1726399cdd1f4675f9a47737803f8e3f9` 建立。
原上线应用仍是 Binance 现货目标；本轮未连接 VPS、未部署改动、未改其服务。
没有读取密钥、旧观察数据库或 sealed payload，没有启动 collector 或账户/订单请求。
另一个 `chainlink-readonly-data` 工作区仍有五个暂存但未提交文件，本轮未修改或合并它们。

## 官方契约复核

本轮重新读取 [Predict.fun Chainlink Price Markets](https://docs.predict.fun/developers/chainlink-price-markets)。
文档仍指定 Chainlink Data Streams v3、严格上涨/下跌/相等，前轮终价传递到下一轮起价；
Predict forwarder 要求两个报告时间戳相同，CRE 路径允许最多五秒缓冲，并存在暂停状态下的紧急结算机制。
这不能证明 Binance 现货 close/open 与目标等价，也不能仅凭报告时间戳推断当前市场实际使用哪份报告。
该通用文档本身不是当前 BTC5m token mapping、支付向量、市场状态或权威结算的 API 样本。

[Chainlink 官方 Data Streams 入口](https://docs.chain.link/data-streams)仍区分 HMAC 报告访问与公开 Discovery。
本轮没有执行认证、购买数据或验证访问资格；不能宣称已有所需历史覆盖。
旧 probe 文档明确声明尚未做报告签名及 venue acceptance 验证，不能被视为已接通参考价。

## 本轮发现和修复

原 `decision_assistant/evaluation.py` 的问题：

1. 接收三分类概率却忽略 HALF_TIE 的半额支付，低估两侧预期支付。
2. 没有独立报价时间、报价市场/规则/token 绑定，无法正确处理“预测先生成、报价后到达”。
3. 检查五分钟长度但不检查 UTC 桶对齐；没有可执行的信号失效边界。
4. 缺证据时仍返回数值 edge；正常门槛未通过也一律叫 NOT_EVALUATED，混淆“未评估”和“评估后不选边”。

现有修复：

- 显式 HALF_TIE 合约用 `p_up + .5*p_tie - yes_ask - costs` 与 `p_down + .5*p_tie - no_ask - costs`。
  不能为当前市场猜测该支付契约；调用方必须先提供独立验证的 mapping。
- 预测和报价分别绑定同一 market、rule 与 target；报价晚于预测允许，但必须在评估时已可用。
- 独立限制 source/receipt quote age 和 prediction age，过期边界采用半开区间。
- UP/DOWN 的 `valid_until` 取预测、报价、市场与 TTE 的最早失效边界。
- 缺证据/非法绑定为 `WAIT + NOT_EVALUATED`，edge 与有效期为 null。
  已有完整证据但门槛不够为 `WAIT + EVALUATED`；保留原因和 edge，并要求下一时刻重新评估。

所有测试使用合成输入，未更改模型、训练集、校准、原阈值或证据。

## 完成矩阵与剩余 blocker

| 完整目标要求 | 当前证据 | 判定与下一步 |
|---|---|---|
| 当前 BTC5m 市场、token/规则、权威支付绑定 | 通用官方协议；已有旧样本不能替代当前市场 | OPEN：需要当前市场已脱敏、可审计的 metadata/status/映射与支付契约 |
| 与 Chainlink 目标一致的预测 | 现有冻结 artifact 明确是 Binance Spot close>open，负类含平盘 | OPEN：不能直接桥接，需独立研究预测器及完整目标定义 |
| 真实时间因果/校准验证 | 本轮及旧 M9.2/M10.2 为合成证明；不存在连接到本评估器的真实批准证据提供器 | OPEN：获准历史参考价、接收/可用时间、权威结算配对及未触碰验证窗口 |
| 实时真实报价、费用与深度 | 本评估器是纯函数，未连接真实 read-only quote provider | OPEN：真实绑定、时效与费用证据后接入，不能填默认费率 |
| UP/DOWN/WAIT 原因与有效期 | 本轮数学和绑定/失效回归 | PARTIAL：纯评估契约已修复，真实输入缺口仍在 |
| Dashboard 展示当前 Predict.fun 选边 | 当前发布页显示 Binance 研究模型 | OPEN：只有上述数据链通过后才连接，不把名称替换当成接入 |
| 冻结模型/旧 evidence 保护、无 collector/交易 | 本轮仅独立源码和合成测试，未操作部署 | 保持；不是预测有效性的证明 |

`approved_digests`、`calibration_verified` 和 `quality_verified` 仍是受信任调用方输入；
**不能把手填 True、REAL_VERIFIED 或任意 digest 当成外部证据通过**。
真实 adapter 必须从独立审阅的验证产物加载批准记录，并绑定目标、训练/验证范围、model/config hash；本轮没有假造批准记录。

## 下一步

先落实可用的参考价/权威结算配对及明确使用许可，或者用户提供已审核的独立预测服务和验证产物。
其次验证当前市场身份、支付与真实报价，再串联只读 adapter 和 Dashboard。
在此之前可继续完成批准产物的离线验证器；不能通过新增合成测试消除真实模型和数据 blocker。

用户本轮确认：目前没有上述配对数据或独立验证服务。尚未证明公开链上 round/结算事件能否形成满足时间绑定的研究档案；
下一步可只读审计官方合约与事件来源，不把缺少私有 API 凭证直接等同所有公开研究路径都不可行。
官方 [审计入口](https://docs.predict.fun/developers/audits)列出了 Chainlink 集成审计，可用于定位事件/合约契约，但审计报告本身不等于当前部署地址或数据档案。

## 验收

完整本地测试：**1221 passed, 2 skipped**；评估器回归 43 项全部通过。
95 个受保护文件 SHA256 一致；main 和 v2.0.0-frozen 引用未变；暂存凭证扫描零发现。
本轮完成的是评估契约修复与缺口审计，不是当前市场预测能力交付。
