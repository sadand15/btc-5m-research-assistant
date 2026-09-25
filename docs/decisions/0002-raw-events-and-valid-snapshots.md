# ADR 0002: separate raw events, validation and valid snapshots

状态：M1 已落实三层市场存储及实验表。根据作者最新指令，以下补充取代 pre-M1 对 staleness 和重复验证的早期设想：VALID/INVALID 结构验证与 temporal usability 分开；单个实验保留首次验证结果；内联安全 JSON 代替外部 artifact。精确实现见 [M1 契约](../architecture/V3_M1_CONTRACT.md)。

## Decision

```text
received data → secret-safe RawMarketEvent → validation
                                              ├─ ACCEPTED → valid MarketSnapshot
                                              └─ REJECTED → ValidationFailure
```

`raw_market_events` 记录所有实际收到的输入，`market_validation_events` 记录每次验证，`market_snapshots` 只保存通过 normalize + validate 的合法对象。下游永远不通过检查 snapshot.validation_status 来区分“半合法”对象；无效输入不进入 snapshot 类型。

## Strict snapshot invariants

- market_id、venue、expiry、source/receive/validation 时间和已核实 outcome mapping、rule hash 均完整；市场类型被支持，规则与预期一致，市场处于可接收快照的有效期间。
- source_at 不晚于 received_at + 显式 clock_skew_tolerance_ms（默认 0），received_at 不晚于 evaluation_at/available_at；负 quote age 不截断，时钟容差进入配置哈希。
- 结构要求 expiry 晚于收到事件时刻和 source_at；价格有限且位于 (0,1)，每侧 bid ≤ ask。校验过程可以重放旧报价，不把当前 wall-clock 或最大 age 混入结构合法性；是否 stale/expired 在显式使用时点计算，spread 门槛属于后续使用策略。
- YES/NO bid/ask 与深度都完整；逐档价格、数量有效，数量为正、档位排序和合并规则确定，top-of-book 与规范深度一致。负数量、不可解析档位、空必需深度拒绝。
- 推导 NO 盘口必须使用已验证映射并记录 derived/source 关系，不把互补深度当独立可重复消费的流动性。
- 必需参考价及其来源完整有效；可选字段显式 Optional，不使用 0 或 NaN 伪装缺失。

构造 factory 返回 `ValidatedSnapshot | ValidationFailure`，snapshot 不可变且不允许绕过 validator 直接创建。存储读取也必须重建满足结构 invariant 的对象；数据损坏应显式失败，而非返回半对象。

合法性以 validated_at 和 validation_context 为准，不意味着永远新鲜。稍后决策仍须检查当前 quote age、expiry、规则版本和来源一致性；这是时间推进后的使用门槛，不是让调用方补做最初结构校验。

## Rejection taxonomy

M1 实际结构原因：`MALFORMED`、`MISSING_BID`、`MISSING_ASK`、`NON_FINITE`、`INVALID_PRICE`、`INVALID_QUANTITY`、`CROSSED_BOOK`、`FUTURE_SOURCE_TIME`、`NEGATIVE_QUOTE_AGE`、`INVALID_TIMESTAMP`、`WRONG_MARKET`、`UNKNOWN_OUTCOME_MAPPING`、`RULE_MISMATCH`、`UNSUPPORTED_MARKET`、`INVALID_DEPTH`。`QUOTE_STALE` / `MARKET_EXPIRED` 等由独立 freshness 函数返回，spread 策略留待后续。一个事件可有多个拒绝原因，顺序稳定；不可解析载荷仅报告可确定的问题，不编造更深层原因。

## Durable ingestion and secrets

在语义 validation 前完成安全解析/脱敏并持久化 raw。raw event 的不可解析 source_at/market_id 为 null，不妨碍保留接收时间和序号。先提交原始事件；后续失败可重试，停在 RECEIVED 且没有关联验证记录的事件可审计为待验证，不被静默跳过。VALID/INVALID 状态由验证事件给出，原始 payload 不改写。

只接收预定市场 body，不存请求对象或认证 headers。M1 以字段/数值白名单生成内联安全 JSON；未知字段及嵌套 transport metadata 丢弃。malformed 或无法安全判断的 body 不原样落盘：持久化 deterministic 占位内容、其 hash、接收 envelope 及 `REDACTED_UNSAFE_PAYLOAD`，明确记录原始字节未保留。外部 artifact 管理不在 M1 范围。

## M1 acceptance tests

每个拒绝类型：有 raw event、有 INVALID validation、零 snapshot；每个合法输入：有 VALID validation，且 snapshot FK、字段和 invariant 完整。验收覆盖秘密过滤、malformed 安全表示、validator 崩溃恢复、快照事务失败回滚、并发幂等、跨实验引用拒绝、读取损坏 snapshot 拒绝、未来不可用和时效变化。symlink 测试在系统允许时执行，Windows 增加 junction 测试。

本 ADR 不改变 V2 任何表、模型、配置或源码。
