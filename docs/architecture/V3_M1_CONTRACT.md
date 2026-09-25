# M1 implemented ingestion contract

这里只描述已经实现的功能。唯一输入是调用者提供的市场 body；没有网络 collector、预测、决策、执行或交易服务。全部验收使用 synthetic fixtures，不读取当前 V2 数据。

## Public entry and safe raw events

`Repository.ingest(payload, experiment_id, source, received_at, sequence, evaluation_at, event_key=None, recorded_at=None, transport_metadata=None)`：所有时间显式给定，单位 UTC epoch milliseconds；没有内部 wall-clock now。recorded_at 省略时采用“到达即持久化”的 synthetic 默认 received_at；真实 adapter 必须提供实际记录时点，满足 received_at ≤ recorded_at ≤ evaluation_at。每个 experiment 的 sequence 全局唯一，按 `(received_at, sequence)` 重放；支持时间和同毫秒 sequence 截止，不把未来事件返回给过去查询。

先注册 `Experiment`：精确 Git SHA、数据版本、seed、created_at、配置 hash，model_version 固定 not_applicable；不是研究/模型实验的完整未来 schema。相同 ID 不允许不同 metadata 或配置。`ValidatorConfig` 固定预期 market、feed、rule hash、outcome mapping、最大档数和显式 clock skew tolerance。

当前 body dialect：`market_id`、整数 `source_at`、整数 `expiry`、`market_type=CRYPTO_UP_DOWN`、`feed`、`rule_hash`、`outcome_mapping=YES_UP|YES_DOWN`、`yes_bids`、`yes_asks`，可选 `reference_underlying_price` / `reference_price_at`。深度为 `[[price,quantity],...]`。M1 不假装这就是官方 API wire schema；未来 adapter 需要独立验证。YES/NO 与 UP/DOWN 不能混为一谈。

未知字段、headers、Authorization、Cookie 等不进入存储；transport_metadata 整体丢弃。已知文本字段限定字符和长度、拒绝凭证形态，数字字段只保留允许的数值语法。malformed JSON、重复 JSON key、超大或不能安全表示的 body 替换成 deterministic `_malformed` 标记，保留 envelope 并记录 REDACTED_UNSAFE_PAYLOAD。非有限数改成 `[NON_FINITE]`，不写 NaN/Infinity JSON 数字。未知对象不调用 repr，也不把错误文本当 raw data 保存。

安全载荷上限 256 KiB，最多 1000 档；原始内容发生删减时记录 redaction_status 和 allowlist-v1 版本。payload_hash 为**实际持久化安全字节**的 SHA256，不是原秘密内容的哈希。信息丢失是显式限制，不能声称此类记录可还原原始秘密或字节。M1 使用内联 JSON，避免半写外部 artifact 的附加问题。

## Snapshot and temporal semantics

`MarketSnapshot()` 普通直接构造被拒绝；只能通过纯 `validate_market` 返回。frozen dataclass、不可变 tuple 深度和 Decimal 数值构成公开类型；没有 snapshot.validation_status。Python 低层反射不是安全沙箱，调用者仍不得绕过私有实现。

结构校验：完整的市场映射和规则、有限价格且 0 < price < 1、正数量且单个合并档位不超过 1e18、无 crossed book、合法时间、参考价与参考时间配对。相同价格档位以明确 Decimal 精度合并，排序确定；零量和负量档位拒绝整个事件，不静默删除。有效数值最多 28 位有效数字、18 位小数，超出则拒绝；这是 M1 数值边界，不是声称平台采用同一 tick size。

快照保存 snapshot/raw/experiment IDs、market/source、source_at、received_at、available_at（首次 evaluation_at）、sequence、expiry、四侧逐档 book、feed/rule/outcome、可选参考价及时间、容差、validator/config 版本。best bid/ask、mid、spread 是不可变 book 的确定性属性。价格单位为 collateral/share，数量为 shares；mid 明确是描述性均值，不是可成交报价。M1 未实现资金账本。

`temporal_usability(snapshot, decision_at, max_quote_age_ms)` 使用 `decision_at - received_at`，返回原始 signed age 及 QUOTE_STALE、NEGATIVE_QUOTE_AGE、NOT_YET_AVAILABLE、MARKET_EXPIRED 原因。它不改变 snapshot、不生成交易决定。延迟验证的快照不能用于验证完成前的决策，即使 received_at 较早。

## Derived liquidity

只接受直接 YES book；NO bids = 1 − YES asks，NO asks = 1 − YES bids。每个派生档位 `derived=True`，保留原 origin_side 和同一 liquidity_id；snapshot.no_derived=True、liquidity_independent=False。`liquidity_groups` 只枚举物理原始 YES 档位，不把 NO 视图再计一次。

这是一项数据契约，不是已实现的撮合资源锁。未来 execution 必须按同一 liquidity_id 共用消费额度；M1 没有订单、fills 或消费函数。

## Actual four-table schema

完整 DDL：`src/btc5_v3/storage/database.py`，SQLite user_version=1。

| 表 | 实际信息与关键约束 |
|---|---|
| experiments | id PK、config_hash、规范 config_json、metadata_json；注册幂等且不可改身份 |
| raw_market_events | id PK、experiment FK、source/source_at、received_at/recorded_at、sequence、可空 market_id、safe_payload/hash、schema/redaction/ingestion versions、event_key；experiment 内 sequence 唯一、source+event_key 唯一 |
| market_validation_events | id PK、experiment+raw 复合 FK、VALID/INVALID、primary_reason、完整 reasons JSON、validator_version、evaluation_at、context_hash；每 experiment/raw 只一条首次结论 |
| market_snapshots | id PK、experiment/raw/validation 三字段 FK、规范 snapshot_json/hash；每 experiment/raw 唯一，validation_id 唯一；trigger 拒绝关联 INVALID 的 snapshot |

仅创建这四张表和索引/触发器，不创建后续业务表。schema 检查拒绝打开未知版本或已有非 M1 表的数据库。WAL、foreign_keys=ON；新库由单一 owner 初始化，已有库打开仅验证表集合、版本和 WAL，不重复 DDL 或修改 user_version。repository 使用 BEGIN IMMEDIATE 串行写事务，同进程不同连接并发重试也只形成一个逻辑结果。

第一笔事务持久化 raw；第二笔事务原子写 validation + 可选 snapshot。验证器异常时 raw 保留为 RECEIVED，重试恢复；snapshot 插入失败则第二笔整体回滚。原始 ingestion_status 保持不可变 RECEIVED；是否已验证由关联 validation 表判断。

ID 由规范化业务键生成。若调用者提供稳定 upstream event_key，重试沿用首条接收时间/sequence；否则以 sequence 作为事件键。相同键而不同安全 payload 拒绝为 conflict，不能静默覆盖。换验证配置、版本或希望独立再次验证，需新 experiment；M1 不提供覆盖旧结论的接口。读取 snapshot 会根据原 raw/config/显式 evaluation time 重新验证，再比较持久化内容和哈希；损坏数据不变成半合法对象。

## Storage isolation

StorageConfig 必须显式提供 project_root，默认 database 为该目录的 runtime/v3/research.sqlite。打开前检查 resolved path，禁止越界、runtime/database symlink 或 junction、hardlink 及 V2 database/WAL/SHM 相同文件；在 linked worktree 中通过 Git common dir 定位原 V2 保护路径（只检查路径/文件身份，不读内容）。这些检查不防御具有本机管理员权限的进程在检查后恶意替换目录。

## Reasons and limits

结构化原因：MALFORMED、MISSING_BID、MISSING_ASK、NON_FINITE、INVALID_PRICE、INVALID_QUANTITY、CROSSED_BOOK、FUTURE_SOURCE_TIME、NEGATIVE_QUOTE_AGE、INVALID_TIMESTAMP、WRONG_MARKET、UNKNOWN_OUTCOME_MAPPING、RULE_MISMATCH、UNSUPPORTED_MARKET、INVALID_DEPTH。primary_reason 为稳定检查顺序第一项，all_reasons 去重且顺序稳定；不可解析输入不会编造深入校验结果。

预期 feed/rule/mapping 由配置提供，尚未通过真实 adapter 认证或实时规则核验。没有验证真实平台 payload、网络吞吐、断电耐久性、未知敏感字段变体或后续 execution 对共享深度的消费。测试验证受支持 synthetic dialect 与失败关闭策略，不构成真实采集上线验收。
