# V3 Milestone 1 delivery

范围：独立 prediction-market ingestion layer。实现 raw → validation → snapshot，不实现 Prediction、Edge、Decision、Risk、Execution、Calibration、Dashboard 或 trading loop。完成本阶段后停止，不进入 M2。

## Part A: V2 operational status only

状态 **BLOCKED_MISSING_CREDENTIAL**。北京时间 2026-09-25 01:53:59 的进程/端口检查未发现 app、venue、dashboard、mobile 服务或 8501/8502 监听。Process/User/Machine 中均没有 PREDICTFUN_API_KEY；没有从聊天、日志、Git 历史、数据库或其他进程查找旧 Key。

原目录仍为 main、HEAD `11c7d06b988b9177f84cf0f34920ad38c4021add`；model hash `5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f`；config hash `f45916edcb228df5837596e2e02ea912a1d96c30e96aacbfd36986b49b37a142`。对照 M0 基线核验 27 个保护文件，包括 manifest 和备份模型。冻结 tag object `fa9757a2e3fd132121a7c7e85307553b1f008a29` 保持不变。

作者已明确允许原冻结代码的 Binance candle synchronization/repair、upsert、warmup、pending local paper recovery 和正常重连；它们不再是恢复阻塞。此次因缺少环境凭证**没有启动**，所以这些恢复动作本次没有执行。resumed_at 和 first_new_genuine_observation_at 均为 null，不能声明 RESUMED。

此前已确认的最后真实 observation 为北京时间 2026-09-23 23:06:42.076。缺口仍未关闭，没有生成缺失 observation、补录平台历史 quotes 或重放冒充前瞻数据；没有改 manifest、window、源码、配置、模型或阈值。此次未打开 V2 数据库读取数据，未运行 forward.py report，也未查询任何盲测表现。恢复后的实际新增情况尚不可验证。

## Delivered files

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 可构建的独立 btc5-v3-ingestion 包，零运行依赖 |
| `src/btc5_v3/encoding.py` | 规范 JSON、Decimal 字符串、确定性 ID、标识符/时间校验 |
| `src/btc5_v3/config/models.py` | ValidatorConfig、StorageConfig、路径隔离 |
| `src/btc5_v3/experiments/models.py` | M1 实验身份、版本与配置哈希 |
| `src/btc5_v3/market/models.py` | RawMarketEvent、不可变 snapshot/depth、结构化 reason、独立 freshness |
| `src/btc5_v3/market/normalize.py` | 白名单安全载荷、raw 构造、规范深度合并 |
| `src/btc5_v3/market/validation.py` | 纯校验、确定性构造和 YES-derived-NO 来源标识 |
| `src/btc5_v3/storage/database.py` | 四表 DDL、WAL、FK、有效验证触发器、schema version |
| `src/btc5_v3/storage/repository.py` | 两阶段事务、唯一键、并发幂等、损坏读取拒绝 |
| `src/btc5_v3/demo.py` | 两条 synthetic 事件的非交易 demo |
| `tests/v3/test_ingestion.py` | synthetic 契约、失败注入、并发及文件别名测试 |
| `docs/architecture/V3_M1_CONTRACT.md` | 精确输入、schema、invariants、reason 和已知限制 |

另有包 init 文件；更新 README、架构/schema/路线/ADR 文档、pytest src 路径、构建输出 ignore 和 CI 安装/demo 步骤。冻结 `btc5/` 和 app.py 未修改。

## Schemas and invariants

仅四表：experiments、raw_market_events、market_validation_events、market_snapshots。配置/来源/版本通过关联可追溯；没有未来业务空表。raw 单独先提交，验证与 snapshot 原子提交；验证失败有 raw + INVALID，无 snapshot。相同 upstream event_key 重试保持首次接收/验证时间，只产生一个逻辑 snapshot，冲突 payload 拒绝覆盖。

价格单位 collateral/share，数量单位 shares；有效数值是有限 Decimal、价格在 (0,1)、数量为正、档位排序确定且不 crossed。snapshot 普通构造被禁止，读回时重新验证并校验持久化表示。同毫秒按 sequence 排序；显式 source/received/evaluation 时间与 clock skew tolerance 决定结构时序合法性，不调用 wall-clock。

temporal_usability 用显式 decision_at 重新计算 signed age，并区分尚未 available、stale 和 expired。YES-derived-NO 携带相同物理 liquidity_id、derived 标志与 origin_side；只在 liquidity_groups 枚举原始物理档位。后续执行层必须尊重这项约束，M1 没有实现额度消费或撮合。

完整结构化 reason 列表与具体列约束见 M1 契约，不把拒绝仅存成自由文本。脱敏过的内容明确标识信息损失；malformed body 不作为潜在秘密容器原样保存。

## Validation evidence

- 测试驱动：先新增测试，确认因 V3 包不存在而失败，再逐步实现。
- 本机完整 suite：**106 passed, 2 skipped**，其中旧测试 52 passed，V3 54 passed / 2 skipped。两项 skip 是 Windows 当前权限不允许创建 symlink；hardlink 和 Windows junction 测试已通过。Linux CI 会执行 symlink 测试并跳过 Windows 专用 junction。
- 事务失败注入确认：快照写入失败不留下已接受验证的半事务；原始事件仍在。并发重复 ingestion 只保留一个逻辑 snapshot。
- 初次 Linux CI 暴露并发打开已有库时重复 DDL 的锁竞争；已改成已有库只校验 schema/version/WAL，不重写 schema，并增加 SQL trace 回归测试。新库首次初始化由单一 owner 完成，之后支持并发连接的事务串行写入。CI 关闭 matrix fail-fast，确保两平台结果均可见。
- Synthetic demo：2 raw、2 validation、1 snapshot；crossed event 为 INVALID / CROSSED_BOOK。相同 commit 重跑幂等。正式 CLI 拒绝 dirty working tree，防止用旧 HEAD 冒充当前未提交代码；unit fixtures 直接注入 synthetic commit 标识。
- 正式 wheel 已成功构建；构建隔离环境没有修改 V2 虚拟环境依赖。
- 发布门槛包括暂存/历史凭证扫描、V2 27 个保护哈希、冻结 tag 和真实 worktree 路径隔离核验。CI 在本提交上安装包、运行完整 pytest、执行 demo 和历史凭证扫描；最终结果以该提交 Actions 及交付消息为准，不沿用 pre-M1 状态。

## Known limits and unverified assumptions

M1 输入是显式约定的 YES-book dialect，尚未验证真实 Predict.fun wire schema、认证后规则来源或 collector 行为。支持二元 YES/NO 互补报价，不支持独立 NO book、其他市场或订单。固定有限精度边界不是平台 tick size 证明。

malformed/未知字段可能被不可逆脱敏；同一安全表示不证明原始未脱敏字节相同。身份冲突以安全 payload 为准。单实验保留首次验证，变更配置或 validator 必须另建实验。调用方应为真实接收提供可信 received_at/sequence/记录时点；M1 不提供网络时钟认证。

路径守卫检查 resolved path、symlink/junction/hardlink 和共享 Git 原仓库的数据库身份，但不防本机管理员检查后的恶意路径替换。尚未完成断电耐久性、真实高吞吐和跨机运行测试。Python 不可变类型是正常 API 契约，不是防恶意反射的沙箱。

## Author reading order

1. `market/models.py`：理解合法对象、时间与共享深度身份。
2. `market/normalize.py`：理解安全原始事件、删减和 payload hash 的含义。
3. `market/validation.py`：逐条跟踪合法输入与拒绝原因。
4. `storage/repository.py`：理解 raw 先持久化、第二笔原子事务、幂等与读回校验。
5. `tests/v3/test_ingestion.py`：从 synthetic 失败案例检查上述承诺。
