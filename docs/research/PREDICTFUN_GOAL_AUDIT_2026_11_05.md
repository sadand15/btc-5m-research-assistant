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

## 公开链上证据可达性复核

用户再次确认没有参考价/权威结果配对档案或独立验证预测服务。
本次未读取凭证、账户或旧 observation；仅执行一次公开节点
`eth_getTransactionReceipt`，没有发送交易、启动 collector 或创建 study。

从公开浏览器索引发现的候选交易：
[0xac2eecef…131d4d2](https://bscscan.com/tx/0xac2eecefd4342b33b52557fd4c796c97893266e75d535aae09b851871131d4d2)。
浏览器全文访问失败，随后使用公开 BNB Chain 节点
`https://bsc-dataseed.bnbchain.org/` 只读核验回执：

- transaction hash：`0xac2eecefd4342b33b52557fd4c796c97893266e75d535aae09b851871131d4d2`
- block number：`0x61bfba3`
- block hash：`0x48801b75e194a46ed16cca37923c5306e153c35c31c35950b4b376aedbd53861`
- receipt status：`0x1`；相关日志 `removed=false`。
- 日志 `0x45` 来自 `0x22da1810b194ca018378464a58f6ac2b10c9d244`，
  topic0 为 `0xb44d84d3289691f71497564b85d4233648d9dbae8cbdbb4329f301c3a0185894`，
  condition ID 为 `0x324f719fe5e62e8adef30023616634e51afe81a0d14976a5674b9ddc82488ea0`。
- 同一回执还含候选 adapter `0x77620fab2969df2d5696f1f081940e416cf17ca5`
  的日志和 feed ID `0x0003ef42b4d20a19409a187c39670a6f5be7ce17fc78c290d25eb45bbf769d37`。

这些仅证明候选历史回执可以公开读取。事件语义仍需通过部署 ABI 核验；
不能由日志相邻关系推定同一轮次绑定，不能把 feed ID 直接标注为 BTC，
不能把 topic 中的整数 `0x12c` 自动解释为已证明的五分钟周期。
本次没有证明该地址属于当前 Predict.fun BTC5m 部署，也没有完成 market/token/
condition/round/feed 的关联。回执成功及 `removed=false` 不等于已独立验证链最终性；
区块时间不等于原生 `settled_at`、报告源时间或历史研究系统的接收时间。

公开链路径因此从“尚未验证可达”推进为“候选回执可达”，**仍非合格数据集**。
下一步需固定官方部署来源和 ABI、核验 feed 语义及精确轮次/市场映射，再评估
是否存在足够的周期内参考价覆盖、可用时间和合法研究使用条件。
即便获得轮次端点与 payout，也不能替代周期内历史特征或独立模型验证。
当前真实决策保持 `NOT_EVALUATED`，数据准备状态保持 `NOT_READY`。

提交 `8f3eb936e0cbe79440a979984a7ad999a7661ce9` 的远程 CI 本次实查全部成功：
[Tests](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/42050965367)、
[M10.2 Offline Reproduction](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/42050965289)、
[Realtime Dashboard](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/42050965336)。
本节仅补充审计记录，没有修改运行代码；以上 CI 对应前述代码提交。
