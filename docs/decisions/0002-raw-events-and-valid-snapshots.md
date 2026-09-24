# ADR 0002: separate raw events, validation and valid snapshots

状态：pre-M1 接受为设计约束；仅文档，未创建表或实现代码。取代 ADR 0001 中尚未细化的市场存储边界。

## Decision

```text
received data → secret-safe RawMarketEvent → validation
                                              ├─ ACCEPTED → valid MarketSnapshot
                                              └─ REJECTED → ValidationFailure
```

`raw_market_events` 记录所有实际收到的输入，`market_validation_events` 记录每次验证，`market_snapshots` 只保存通过 normalize + validate 的合法对象。下游永远不通过检查 snapshot.validation_status 来区分“半合法”对象；无效输入不进入 snapshot 类型。

## Strict snapshot invariants

- market_id、venue、expiry、source/receive/validation 时间和已核实 outcome mapping、rule hash 均完整；市场类型被支持，规则与预期一致，市场处于可接收快照的有效期间。
- source_at 不晚于 received_at，received_at 不晚于 validated_at；负 age 和未来时间拒绝。首次实现采用严格边界，任何时钟容差须独立配置、版本化并测试，不能默默截断时间。
- 校验时 quote age 不超过配置，expiry 晚于 validated_at；所有价格有限且位于 (0,1)，每侧 bid ≤ ask，spread 不超过配置上限。
- YES/NO bid/ask 与深度都完整；逐档价格、数量有效，数量为正、档位排序和合并规则确定，top-of-book 与规范深度一致。负数量、不可解析档位、空必需深度拒绝。
- 推导 NO 盘口必须使用已验证映射并记录 derived/source 关系，不把互补深度当独立可重复消费的流动性。
- 必需参考价及其来源完整有效；可选字段显式 Optional，不使用 0 或 NaN 伪装缺失。

构造 factory 返回 `ValidatedSnapshot | ValidationFailure`，snapshot 不可变且不允许绕过 validator 直接创建。存储读取也必须重建满足结构 invariant 的对象；数据损坏应显式失败，而非返回半对象。

合法性以 validated_at 和 validation_context 为准，不意味着永远新鲜。稍后决策仍须检查当前 quote age、expiry、规则版本和来源一致性；这是时间推进后的使用门槛，不是让调用方补做最初结构校验。

## Rejection taxonomy

至少支持 `MALFORMED`、`MISSING_BID_ASK`、`NON_FINITE_NUMBER`、`INVALID_PROBABILITY`、`CROSSED_BOOK`、`QUOTE_STALE`、`FUTURE_SOURCE_TIMESTAMP`、`WRONG_MARKET`、`UNKNOWN_OUTCOME_MAPPING`、`RULE_MISMATCH`、`UNSUPPORTED_MARKET`、`INVALID_DEPTH`；补充 `SPREAD_TOO_WIDE`、`INVALID_TIMESTAMP`、`MARKET_EXPIRED` 和必要参考字段缺失。一个事件可有多个拒绝原因，顺序稳定；不可解析载荷仅报告可确定的问题，不编造更深层原因。

## Durable ingestion and secrets

在 parsing/validation 前将安全原始载荷持久化。raw event 的不可解析 source_at/market_id 为 null，不妨碍保留接收时间和序号。先提交原始事件；后续失败可重试，停在 RECEIVED 的事件可审计为待验证，不被静默跳过。VALIDATED/REJECTED 状态由验证事件投影，原始 payload 不改写。

只接收预定市场数据 body，不存请求对象或认证 headers。JSON 递归清除凭证字段；malformed body 先做安全过滤，再作为不透明字节 artifact 保留。无法安全判断的 body 不得落盘：持久化脱敏占位 artifact、hash、接收 envelope 及 `REDACTED_UNSAFE_PAYLOAD` 状态，明确记录原始字节未保留，不能声称可完整重放该 payload。artifact 使用受控相对路径及大小限制；临时写入、fsync/原子发布、校验 hash 后绑定记录，故障必须有可恢复待处理状态。

## M1 acceptance tests

每个拒绝类型：有 raw event、有 REJECTED validation、零 snapshot；每个合法输入：有 ACCEPTED validation，且 snapshot FK、字段和 invariant 完整。增加秘密过滤、malformed opaque payload、丢失 artifact、validator 崩溃恢复、重试幂等、跨实验引用拒绝、读取损坏 snapshot 拒绝、过去 snapshot 在决策时变 stale、未来数据扰动不影响过去结果等测试。

本 ADR 不改变 V2 任何表、模型、配置或源码。
