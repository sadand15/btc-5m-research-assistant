# V3 Database proposal — not a migration

M0 仅设计，不执行 DDL，不连接 V2 数据库。后续使用 V3 worktree 内 `runtime/v3/research.sqlite`，禁止 ATTACH 或写入 V2 `runtime/research.sqlite`。SQLite WAL、foreign_keys=ON、单 writer 的事务序列适合第一版；实际迁移从 M1 开始逐步落地。

## Common event envelope

每个事件有唯一 `id`（可由 experiment_id + 类型 + 输入序号确定性生成）、`experiment_id` FK、`event_at`、`received_at/available_at`（适用时）、`recorded_at`、`sequence`、`version`、`model_version`、`config_version`（规范配置 SHA256）、`source`、`schema_version`。尚未产生模型结果的市场事件使用明确的 `not_applicable`，不伪造版本。

数值校验拒绝 NaN/Infinity。计价及费用明确 collateral/share 单位与舍入规则；精确记账计划使用 Decimal 和规范化十进制文本或带 scale 的整数，不依赖 float 累加余额。概率研究计算可以 float，原始报价保留可复核精度。

## Tables

下表字段补充共同 envelope；真实 DDL 和 CHECK/FK 约束由对应里程碑实现。

| 表 | 关键字段与关联 |
|---|---|
| `experiments` | id、git_commit、dirty_patch_hash（发布研究要求 clean）、model_version/hash、data_version/hash、feature_version、config_hash/config_json、start/end UTC、seed、运行模式、fee/execution/latency assumptions、依赖环境哈希、计划样本选择规则 |
| `market_snapshots` | market_id、cycle、expiry、source_at、bid/ask、YES/NO depth、reference prices/timestamps/feed、rule_hash、outcome_mapping、raw_payload_hash、validation_status、rejection_reason |
| `predictions` | snapshot_id（可为空）、market/cycle、input_cutoff、available_at、p_yes、target_definition、support_status、feature_hash/values、calibration_version；MODEL_UNAVAILABLE 也保存状态 |
| `edge_evaluations` | prediction_id、snapshot_id、evaluated_at、quantity、raw_yes/no_edge、net_yes/no_edge、双侧 fee/spread/depth/latency 成本、mid/ask 定义、preferred_side、confidence、reason |
| `decisions` | edge_id（可为空）、prediction_id/snapshot_id（输入缺失可空）、action、decision_at、所有 rejection reasons、primary_reason、gate 结果、attempt_id；每次评估必有结果 |
| `orders` | decision_id、side、requested_shares、max_collateral、limit_price、submitted_at、execution_due_at、expiry、risk_reservation_id、idempotency_key |
| `order_events` | order_id、event_type（accepted/rejected/partial/filled/cancelled/expired）、reason、execution_snapshot_id、remaining_qty；append-only |
| `fills` | order_id、execution_snapshot_id、executed_at、gross/net shares、逐档价格数量、VWAP、fee/currency、slippage、actual_delay_ms、collateral_debit |
| `settlements` | market_id、rule_hash、official_status、yes_payout、effective_at、available_at、evidence_hash、revision_of；未知结果保留 pending，不猜测 |
| `fill_settlements` | fill_id、settlement_id、net_shares、payout、collateral_credit、realized_pnl；相同 fill 和结算版本仅一次 |
| `risk_events` | decision_id/order_id（允许空）、guard、reason、limits、equity/high_watermark、UTC daily loss、loss_streak、reserved/open exposure、pause/resume、data-health 信息 |
| `ledger_entries` | order_id/fill_id/settlement_id/risk_event_id、reserve/release/debit/credit、amount/currency、unique business key；余额与风险状态可重建 |
| `experiment_events` | experiment_id、started/completed/failed、数据缺口、健康状态、结果 artifact hash；不覆盖既有实验参数 |

## Integrity and transactions

- FK 使用 `(experiment_id, id)` 组合约束，禁止跨实验串联。market_id 需含 venue namespace，不把相同编号的其他平台市场混合。
- decisions 对 `(experiment_id, attempt_id)` 唯一；orders 的 idempotency_key 唯一。一次输入重试不再创建新仓位。
- 一个 decision 至多一个 entry order（首版），order 可有多个 fill；市场结算可服务多个 fill。无需给所有 prediction 强造一个订单。
- 风险预留、order accepted、ledger entry 在一个事务；fill 与预留调整在一个事务；结算 credit 与 fill_settlements 在一个事务。重启重放不能重复扣款或入账。
- 事件 append-only，状态由投影重建。官方结算更正添加 revision 和冲正分录，不 UPDATE 掉历史 PnL。指标必须声明 as-of，避免用尚未发布的结算影响当时风险决策。
- 无效/缺失报价仍需保存接收事件及拒绝原因。不能用过强的原始表 CHECK 约束把坏数据静默丢掉；有效投影和决策层才要求完整有效字段。认证头、cookie、Key 和私人配置绝不进入 raw payload。
- 索引至少覆盖 `(experiment_id, market_id, received_at, sequence)`、prediction available_at、order execution_due_at、risk event_at、fill order_id、settlement market_id/available_at。

## Audit questions

从 fill → order → decision → edge → prediction/snapshot 可恢复当时可见输入、估计 EV、执行报价与实际费用；从 fill_settlements/ledger 可分解估值误差、延迟及深度成本、已实现支付。

NO_TRADE 保留 raw/net edge 和拒绝 gate，支持阈值敏感性。但如果当时没有录到延迟后盘口或结算，只能比较候选覆盖率，不能凭信号时 mid 补造 counterfactual PnL。不同阈值需按时间重新模拟风险预留及资金路径，不能简单过滤原 fills。

完整数据及完整输入 artifact 才能保证 replay；哈希只能验证身份，不能替代数据保存。数据留在私有持久卷，Git 只保留 schema、合成 fixture、配置模板和脱敏摘要。
