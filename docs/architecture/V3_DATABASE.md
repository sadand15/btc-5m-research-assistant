# V3 Database — M1–M4 implementation and future proposal

## Current schema 5 — M4.5

新增 `path_analysis_runs` 与 `path_analysis_results`，合计十二表。前者保存同实验的原始 point/outcome archives、config/hash、input hash、Git SHA、cutoff 和显式 creation metadata；后者保存完整 deterministic report/hash，通过同实验复合外键链接 run。原子写入，UPDATE/DELETE/REPLACE 拒绝，重试保留首次创建元数据，读回重放完整输入核验结果。未向 MarketSnapshot 写入未来派生字段；无 orders/fills/positions。详见 [M4.5 contract](V3_M4_5_PATH_CONTRACT.md)。下方保留此前 schema 设计。

M4 当前为 user_version=4、十表，只新增下列三表。AnalyticsRepository 显式执行 M2/M3/M4 迁移，各阶段有事务和版本检查；普通 Database reopen 不重跑 DDL。所有文件继续受 V3 runtime/v3 路径保护。M4 不创建 execution/order/fill/risk 表。

| M4 表 | 实际列与约束 |
|---|---|
| resolved_outcomes | id、experiment_id FK、market_id、payload_json/hash；UNIQUE(experiment_id,market_id)；payout/时间/来源/rule/version/semantics 保存在 canonical JSON |
| analysis_runs | id、experiment_id FK、code_git、cutoff、created_at、config_json/hash、inputs_json、input_hash；UNIQUE(experiment_id,id) |
| analysis_results | analysis_id PK、experiment_id、result_json/hash；复合 FK 指向同实验 analysis_runs |

inputs_json 保存完整上游研究归档和显式 outcome ID 清单；读取不会自动查询 latest outcome 或新增 prediction。run 的 analysis_id 由 experiment、config hash、code Git SHA、cutoff 和内容 fingerprint 派生，creation time 不改变逻辑身份。重试保留第一次 creation metadata。outcome 同一市场的冲突重试拒绝，v1 未实现结算修订；隔离研究若需不同 fixture outcome 使用不同独立存储/experiment，不覆盖旧结果。

三表均拒绝 UPDATE/DELETE/REPLACE。一次新 run 的 outcomes、run、result 在同一事务；失败全部回滚。读回核验 outcome/输入 hash、配置和完整分析重放结果。归档与 outcomes 的 experiment 必须一致；API 不静默跨 experiment 聚合。哈希不是防管理员整体改库的签名。

新增研究 experiment 通过 M4_SYNTHETIC_ARCHIVE_V1 合同显式注册。M4 archive 是已产生上游记录的不可变导出，不向 M1/M2/M3 表回填 records，也不绕过原逐市场 validator 约束。现有同实验记录可显式导出后输入，但采样完整性/来源可信度需外部证据，API 不承诺自动全库 coverage。详见 [M4 契约](V3_M4_CONTRACT.md)。

以下保留 M1–M3 的版本演进说明与未来提案。

M3 当前为 schema user_version=3，共七表，只比 M2 增加 decisions。`DecisionRepository` 显式调用 storage/decision_repository.py 的事务迁移；先建立同实验 edge parent unique index，再建 decisions 与不可变触发器，最后更新 version。失败整个迁移回滚。M1/M2 原始记录不重写；Database 支持打开 version 1/2/3，普通 reopen 不执行 DDL。

| M3 表 | 实际列与约束 |
|---|---|
| decisions | id、experiment_id FK、attempt_key、prediction_id、snapshot_id、edge_id、evaluated_at、config_hash/config_json、payload_json/payload_hash；UNIQUE(experiment_id,attempt_key)，三个输入均有 same-experiment 复合 FK |

三个输入 FK 可空，以保留显式缺失输入的 NO_TRADE；传入未知非空 ID 报查找失败，跨实验 ID 拒绝落库，不能伪装成同实验引用。Prediction/Snapshot/Edge 同实验但彼此不匹配时，可保存有 lineage rejection 的 Decision。所有 gate diagnostics、原因、原 edge 值、liquidity identity、输入 hash 保存在 canonical payload。DecisionConfig（包括来源合同 hash）完整保留，可确定性重放。

id = SHA256([experiment_id,attempt_key])。同一 attempt 的时间、输入或 config 变化是 conflict，不覆写；新决策需要新 attempt_key。UPDATE/DELETE/REPLACE 均被触发器拒绝。读回先验证全部输入，再重跑 M3 policy 并核验全部 payload/hash/列身份。只按记录 ID 读取，不使用 latest，因此未来事件不能改写过去结果。哈希不防管理员整体重写，不是签名。精确语义见 [M3 契约](V3_M3_CONTRACT.md)。

下面保留 M1/M2 schema 说明和完整未来提案；orders/fills/positions/ledger/settlements/risk 未创建。

M1 四表仍保留。M2 通过 `EdgeRepository` 显式调用事务迁移，将 user_version=1 升为 2，只新增 predictions 与 edge_evaluations，共六表；不创建 orders/fills/risk。纯 M1 Database 新建仍为 version 1，能打开 version 2，普通打开不重复 schema 写入。DDL 位于 `storage/database.py` 与 `storage/edge_repository.py`。迁移、写入均 BEGIN IMMEDIATE，失败回滚。路径隔离在打开 SQLite 前执行，只允许 V3 worktree 的 runtime/v3/；不连接 V2。

M2 实际列：

| 表 | 列与约束 |
|---|---|
| predictions | id、experiment_id FK、prediction_key、payload_json、payload_hash；UNIQUE(experiment_id,id) / UNIQUE(experiment_id,prediction_key) |
| edge_evaluations | id、experiment_id、prediction_id、snapshot_id、evaluated_at、config_hash、config_json、payload_json、payload_hash；同实验复合 FK 指向 prediction/snapshot；UNIQUE(experiment_id,prediction_id,snapshot_id,evaluated_at,config_hash) |

Prediction 的模型/特征哈希、时间、目标与概率保存在规范 JSON；Edge 的两侧值、成本、liquidity references、时间诊断、split assumption 同样保存于规范 JSON。数值保存有限 Decimal 文本。prediction_id 由实验与逻辑 prediction_key 派生；edge_id 由实验、两个输入 ID、显式评估时间与 config hash 派生。相同身份相同内容重试幂等，冲突拒绝。新配置/新评估时间是新记录而非覆盖。

M2 两表有 UPDATE/DELETE/REPLACE 拒绝触发器；repository 先查重，不用 REPLACE。预测与 edge 首次写入为同一事务；跨实验输入拒绝且不能落关联记录。读回验证 canonical/hash/身份，再从已验证 snapshot、prediction、config 重新计算 edge 对照全部输出。数据库哈希用于检测意外损坏，不是防管理员重写的数字签名。精确语义见 [M2 契约](V3_M2_CONTRACT.md)。

M1 使用 VALID / INVALID，而不是提案中的 ACCEPTED / REJECTED；每个实验内同一原始事件只有首次验证结果及至多一个逻辑快照。重试保持首次接收与验证时间。换 validator/config 或另行复核必须新建 experiment，不覆盖原结果。原始 payload 内联存储为受大小限制的安全 JSON，未实现外部 artifact 管理或完整账本。价格/数量为有限 Decimal 的规范文本，非法非有限输入改为 `[NON_FINITE]` 符号，不存非有限 JSON 数字。model_version 固定 not_applicable，配置/来源/版本通过 experiment、raw 和 validation FK 关联，不在每行重复全部字段。

## Common event envelope

每个事件有唯一 `id`（可由 experiment_id + 类型 + 输入序号确定性生成）、`experiment_id` FK、`event_at`、`received_at/available_at`（适用时）、`recorded_at`、`sequence`、`version`、`model_version`、`config_version`（规范配置 SHA256）、`source`、`schema_version`。尚未产生模型结果的市场事件使用明确的 `not_applicable`，不伪造版本。

合法快照的数值校验拒绝 NaN/Infinity；原始事件仍保留包含非法数值的安全载荷及失败记录，不能因解析失败丢掉事件。计价及费用明确 collateral/share 单位与舍入规则；精确记账计划使用 Decimal 和规范化十进制文本或带 scale 的整数，不依赖 float 累加余额。概率研究计算可以 float，原始报价保留可复核精度。

## Tables

下表保留总体未来设计；M1/M2/M3 的精确实现以上述说明、各阶段契约与 DDL 为准。下表的未来字段不代表已经实现。

| 表 | 关键字段与关联 |
|---|---|
| `experiments` | id、git_commit、dirty_patch_hash（发布研究要求 clean）、model_version/hash、data_version/hash、feature_version、config_hash/config_json、start/end UTC、seed、运行模式、fee/execution/latency assumptions、依赖环境哈希、计划样本选择规则 |
| `raw_market_events` | id、experiment_id、source、source_at（无法解析时 null）、received_at、sequence、market_id（无法解析时 null）、安全 raw payload 或持久 artifact reference、payload_hash、schema_version、version、ingestion_status、redaction_version；保存每个实际收到的事件，包括 malformed |
| `market_validation_events` | raw_event_id、validation_status（ACCEPTED/REJECTED）、rejection_reasons 列表、validator_version、validation_context_hash、validated_at；同一原始事件的不同验证版本保留独立记录 |
| `market_snapshots` | raw_event_id、validation_event_id、market_id、cycle、expiry、source_at、received_at/observed_at、validated_at、bid/ask、YES/NO depth、reference prices/timestamps/feed、rule_hash、outcome_mapping、normalizer_version、validation_context_hash；只插入验证成功的完整合法快照，不含用于辨别半合法对象的 validation_status |
| `predictions` | snapshot_id（可为空）、market/cycle、input_cutoff、available_at、p_yes、target_definition、support_status、feature_hash/values、calibration_version；MODEL_UNAVAILABLE 也保存状态 |
| `edge_evaluations` | prediction_id、snapshot_id、evaluated_at、quantity、raw_yes/no_edge、net_yes/no_edge、双侧 fee/spread/depth/latency 成本、mid/ask 定义、preferred_side、confidence、reason |
| `decisions` | edge_id（可为空）、prediction_id/snapshot_id（输入缺失可空）、raw_event_id/validation_event_id（输入拒绝时关联）、action、decision_at、所有 rejection reasons、primary_reason、gate 结果、attempt_id；每次评估必有结果 |
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
- 原始事件先持久化；验证失败只生成 REJECTED validation event，不生成 market_snapshots 行。验证成功时 ACCEPTED event 与合法 snapshot 在同一事务写入。snapshot 的 `(experiment_id, raw_event_id, validation_event_id)` 必须关联同一来源且被接受的验证事件；由事务 repository、FK/唯一约束及对应数据库约束共同保证，不能只靠调用者自觉检查。
- 对同一 raw_event、validator_version、validation_context_hash 重试幂等；上下文包含验证时点、规则、时效阈值和 normalizer_version。重放保留原收到时间，不能使用未来规则重新标记过去输入。新版本重验证新增事件，不覆盖原验证结论和快照。
- 原始表仅对 envelope 作约束，无法解析的市场字段允许 null；合法快照表对所有必需字段、范围与关联作严格约束。无效事件的拒绝可通过 decision 的 raw_event_id/validation_event_id 记录，snapshot_id 为 null，不能伪造占位快照。
- 认证头、cookie、API Key 和私人配置绝不进入任何 payload、artifact、日志或错误文本。先剥离传输认证元数据，再对市场 body 脱敏；payload_hash 计算存储后的安全字节，并记录编码、redaction_version 和是否有脱敏。不得为了“原始”而保存秘密。
- 索引至少覆盖 `(experiment_id, market_id, received_at, sequence)`、prediction available_at、order execution_due_at、risk event_at、fill order_id、settlement market_id/available_at。

## Audit questions

从 fill → order → decision → edge → prediction/snapshot 可恢复当时可见输入、估计 EV、执行报价与实际费用；从 fill_settlements/ledger 可分解估值误差、延迟及深度成本、已实现支付。

NO_TRADE 保留 raw/net edge 和拒绝 gate，支持阈值敏感性。但如果当时没有录到延迟后盘口或结算，只能比较候选覆盖率，不能凭信号时 mid 补造 counterfactual PnL。不同阈值需按时间重新模拟风险预留及资金路径，不能简单过滤原 fills。

完整数据及完整输入 artifact 才能保证 replay；哈希只能验证身份，不能替代数据保存。数据留在私有持久卷，Git 只保留 schema、合成 fixture、配置模板和脱敏摘要。
