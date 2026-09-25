# V3 Milestone 3 delivery

M3 只将 M2 EdgeEvaluation 转换为有数据质量、时效、来源、状态、spread、depth 与 TTE 检查的 Decision。输出仅为 research/simulation candidate。完成后停止，不进入 M4。

## Development gate

开发前 v3-dev HEAD=`4b570cff39109d54ec68fac27bc0d70f3418fe8e`，working tree clean，M2 Actions run 36104330484 success。原 main=`11c7d06b988b9177f84cf0f34920ad38c4021add`、冻结 tag object=`fa9757a2e3fd132121a7c7e85307553b1f008a29`，远端引用和本地 27 个 protected hashes 均核验一致。没有读取当前 V2 blind performance。

## V2 operational health — fresh checks

本轮重新实时检查，没有沿用旧的 BLOCKED_MISSING_CREDENTIAL 状态。北京时间 2026-09-25 17:40:17 与 17:59:03 的只读检查均发现 app/dashboard/mobile 相关进程，8501/8502 监听，冻结目录数据库的 connection 与 venue_status 均为 CONNECTED。后一检查 heartbeat age 1080 ms，quote heartbeat age 2337 ms，表明检查时 collector 心跳及 quote 心跳在更新。

仅查询 state 中 heartbeat、connection、venue_status、forward_last_quote 四个允许的健康键；未读 observation payload、结算或任何表现数据。未调用 forward report、未启动/停止/重启服务、未修改生产数据库记录、模型、配置或源码。检测到多个 app.py 父子启动链；本次未调整进程，也未把每个 Python PID 都算成独立 collector。各启动链的完整进程内加载版本/数据库归属未逐一证明，健康结论限定为进程、端口和指定冻结路径数据库的实时心跳/连接状态。

## Files and design

| 文件 | 职责 |
|---|---|
| src/btc5_v3/decision/config.py | immutable DecisionConfig、固定参数、允许来源/模型/规则及 semantic contract hash |
| src/btc5_v3/decision/models.py | immutable Decision、GateResult、固定 gate/reason 顺序 |
| src/btc5_v3/decision/policy.py | 纯 admissibility、双年龄、来源语义、状态、spread/depth/TTE 与可选 basis |
| src/btc5_v3/decision/demo.py | 四种 synthetic scenario，幂等落库与完整审计输出 |
| src/btc5_v3/storage/decision_repository.py | schema 3 单表迁移、same-experiment FK、immutable/idempotent 写入、读回校验 |
| tests/v3/test_decision.py | 必需回归、边界、lineage、时间、来源、持久化、并发与因果测试 |

另新增 decision/__init__.py。修改 V3 的 market/models.py、normalize.py、validation.py 支持版本化市场状态元数据；models/models.py 增加 optional target source/feed/reference。保留旧记录 canonical bytes/IDs，未重新计算历史预测。storage/database.py 识别 schema 3，edge_repository.py 允许在更高 schema 上使用 M2 repository。更新 README、architecture、database、roadmap、独立包版本 0.3.0 与 CI 的 M3 demo 步骤。未修改原 V2。

数据库只新增 `decisions`，当前总共七表；没有 orders/fills/positions/ledger/settlements/risk。Decision attempt 的唯一身份由 experiment_id + attempt_key 派生，同一 attempt 变更输入、时间或 config 拒绝。三个输入都有同实验 FK，可空以记录显式缺失数据；非空未知 ID 不会被静默替换。UPDATE/DELETE/REPLACE 拒绝，读回验证全部输入与完整 Decision 重放结果。

## Invariants and mandatory evidence

固定顺序：IDENTITY → AVAILABILITY → MARKET_STATUS → FRESHNESS → SOURCE_RULE → EDGE → SPREAD → LIQUIDITY → NEAR_EXPIRY → FINAL。primary_reason 和 all_reasons 由固定版本顺序决定。M2 选哪侧就检查哪侧；NO_TRADE 永不重新变成交易。

- source=1000 / received=4000 / decision=5000：receipt age=1000 通过，source age=4000 超过 3000，拒绝 STALE_SOURCE。
- bid=.59 / ask=.61 / p=.70：spread=.02；M2 edge=.09 在 M3 原样保留，既不变成 .08 也不变成 .07。测试禁止 policy 调用 M2 engine。
- requested=100 / executable=60 / minimum fraction=.8：拒绝 INSUFFICIENT_DEPTH，即使 M2 数学 edge 通过。
- TTE=5000 ms / minimum=10000 ms：拒绝 MARKET_NEAR_SETTLEMENT，不由概率高低绕过。
- spread 上限、age 上限、depth 下限和最低 TTE 均包含等号；expiry 时刻本身拒绝。比例 gate 用 cross-product 比较，不因显示舍入放宽边界。
- source/feed/rule/mapping/model 与显式 semantic contract 共同约束目标语义。缺失来源/状态 fail closed；价格接近不等于 oracle 语义相同。
- derived NO 保留 physical liquidity IDs/origin/derived，liquidity_independent=false；不消费深度，不能解释成 M5 成交许可。
- 在 t+10000 加入新事件后，按原输入 ID 重算 t 的 Decision 完全相同。

完整结构化 reasons、缺失/非法输入边界、公式与 schema 在 [M3 契约](../architecture/V3_M3_CONTRACT.md)；不是一条自由文本拒绝信息。

## Tests and delivery checks

本机完整 pytest：**272 passed, 2 skipped**；其中 legacy 52、M1 54、M2 72、M3 94 通过。两项 skip 为当前 Windows symlink 权限限制；Linux CI 执行相应测试。测试均 synthetic-only。覆盖迁移失败回滚、单次写入失败、并发幂等、冲突 retry、FK、不可变 SQL、损坏读回、未来事件不改过去，以及时间/spread/liquidity/basis 精确边界。

额外用新版 repository 对 M2 提交 `4b570cf` 已保存的两个 **V3 synthetic demo** 历史 edge 做实际读回，均通过原字节与重算完整性核验；没有打开 V2 observation 数据做兼容测试。M3 demo 单测验证四场景及同版本幂等；正式 clean-commit demo 与 Windows/Linux CI 是交付门槛，最终状态以本提交 Actions 及交付消息为准，不沿用 M2 CI。

发布门槛还包括 credentials scan、27 个 V2 protected hashes、main/frozen tag 不变与 clean working tree。所有变更集中在单独 M3 commit；未创建真实接口/执行/风险模块。

## Demo

| Synthetic scenario | Requested | Final | Primary reason |
|---|---|---|---|
| A：fresh、正常 spread、足够 depth/TTE | BUY_YES | BUY_YES | null |
| B：高 edge，但 source stale | BUY_YES | NO_TRADE | STALE_SOURCE |
| C：高 edge，但 spread 过宽 | BUY_YES | NO_TRADE | SPREAD_TOO_WIDE |
| D：高 edge，但 60/100 shares 不足 80% | BUY_YES | NO_TRADE | INSUFFICIENT_DEPTH |

运行 `python -m btc5_v3.decision.demo --project-root .`，仅使用本 worktree runtime/v3/m3-demo.sqlite，不生成订单。

## Limitations and unverified assumptions

**M2 economic edge、M3 admissibility、M5 execution reality、M6 portfolio/risk permission 严格分层。** M3 通过并不证明能成交、有风险许可或可盈利。没有 PaperBroker、实际 latency fill、仓位、settlement、PnL、训练、调参或 Dashboard。

市场状态与 target/source 元数据目前来自明确的合成合同；真实 venue status/feed、预测目标语义和 basis 参考来源尚未经过真实 adapter 验证。semantic_contract_hash 是外部研究断言的绑定，不是系统自动证明语义等价。旧数据缺元数据时保留原记录且拒绝放行，不反向补证据。费用与 split 的 M2 proxy 限制继续有效。

纯 policy 信任合法 M1/M2 API 输入，不重算 EV；持久化路径先做 M1/M2 的输入完整性验证。Python frozen 类型和内容 hash 不能防恶意反射或管理员整体改库。高吞吐、断电耐久性、网络状态实际提供机制和共享流动性的真实消费仍未验证。

## Author reading order

1. `decision/config.py`：允许来源、显式假设和配置 hash。
2. `decision/models.py`：固定 gate/reason precedence 与不可变审计结果。
3. `decision/policy.py`：只 gate、不重新定价/选侧的核心实现。
4. `storage/decision_repository.py`：事务迁移、同实验关联、幂等与重放。
5. `tests/v3/test_decision.py`：必需回归、边界及 failure injection。
