# V3 Milestone 2 delivery

范围仅为合法 MarketSnapshot + 显式 Prediction + 固定模拟成本 → 双边 EdgeEvaluation → candidate。完成后停止，不进入 M3。精确公式、单位、拒绝原因和 schema 见 [M2 契约](../architecture/V3_M2_CONTRACT.md)。

## Preflight and V2 operational status

开发前核验 v3-dev HEAD 为 `92577a22df347b0f09d886ca29890225d353547a`、working tree clean、M1 Windows/Linux Actions success。原目录 main HEAD 仍为 `11c7d06b988b9177f84cf0f34920ad38c4021add`，27 个保护文件哈希与 M0 基线一致，冻结 tag object `fa9757a2e3fd132121a7c7e85307553b1f008a29` 未变，远端 main/frozen tag 同样核验通过。

北京时间 2026-09-25 14:28 的健康检查未见 Python 服务或 8501/8502 监听；Process/User/Machine 均缺 PREDICTFUN_API_KEY。状态 **BLOCKED_MISSING_CREDENTIAL**，没有启动 V2，没有恢复或补写 observations，缺口未关闭。未打开 V2 blind database，未运行 forward report，未读取或计算盲测表现。原模型、配置、manifest、window 和 thresholds 均保持不变。

## Files

| 文件 | 职责 |
|---|---|
| src/btc5_v3/models/models.py | frozen Prediction / TargetDefinition，明确 YES 概率、身份和时间 |
| src/btc5_v3/edge/numeric.py | 有限 Decimal、float 入口规范化、确定性舍入 |
| src/btc5_v3/edge/costs.py | FeeModel、EdgeConfig/hash、CostBreakdown 与单位 |
| src/btc5_v3/edge/models.py | frozen EdgeEvaluation、SideEvaluation、LiquidityUse |
| src/btc5_v3/edge/engine.py | 兼容/因果检查、双边 depth walk、EV 和互斥候选 |
| src/btc5_v3/storage/edge_repository.py | 显式 schema 2 迁移、复合 FK、幂等、原子与读回重算 |
| src/btc5_v3/edge/demo.py | 两个 synthetic 场景；无交易 |
| tests/v3/test_edge.py | 数学、时间、单位、身份、迁移/事务失败及并发回归 |

另新增两个包 init，修改 storage/database.py 以识别 schema 2；更新 README、architecture、database、roadmap、独立包版本 0.2.0 和 CI demo 步骤。未修改冻结 V2 源码。数据库最多六张表；新表 predictions / edge_evaluations 的输出字段保存于可校验 canonical JSON。

## Critical invariants

- p_yes 是绑定当前 market YES 的概率，不默认 YES=UP；experiment、market、mapping、rule、expiry 和 target semantics 必须一致。
- source/receipt age 分开计算；未来来源时间、未来可用输入和到期均 fail closed，NO_TRADE 是正常结果。
- raw 用 mid，可执行假设用 ask/depth VWAP；spread/depth 解释项不重复扣。
- collateral fee 加入 collateral_spent，shares fee 降低 net_shares；EV_total=net_shares×side_probability−collateral_spent，per-share 分母为 gross executed shares。
- 深度不足保留实际可计算子集和 unfilled；derived NO 保留 YES lot 身份，两侧是互斥假设，不消耗流动性。
- 严格 net_edge > threshold；默认 0.01 是未优化的研究占位参数。split unavailable，忽略 split 仅是显式 proxy 假设。
- M2 记录 append-only、同实验 FK、确定性 ID；冲突重试拒绝，读回重新计算完整输出。

结构化拒绝涵盖 EDGE_BELOW_THRESHOLD、INSUFFICIENT_DEPTH、未来 snapshot/prediction、负 source/receipt age、MARKET_EXPIRED、UNSUPPORTED_PREDICTION、MARKET/EXPERIMENT/TARGET_MISMATCH、EXACT_EDGE_TIE。非法概率在 Prediction 构造时拒绝，不伪造可用预测。

## Validation evidence

- 本机完整 pytest：**178 passed, 2 skipped**；其中 legacy 52、M1 54、M2 72 通过。两项 skip 为当前 Windows symlink 权限限制，Linux CI 执行对应测试。
- 必需 spread 回归：p=.70，YES .59/.61，raw=.10，executable=.09，不是 .08。
- 必需时间回归：source=1000、received=4000、evaluation=5000，source_age=4000、receipt_age=1000。
- 合成测试覆盖单/多档、partial depth、NO VWAP、两类 fee、零 fee、压力/延迟假设、严格 threshold 边界、双方候选/精确相同、float 噪声、Decimal context/half-even、未来信息、身份冲突、FK、幂等、并发、损坏读回、原子写入与迁移失败回滚。
- Demo 测试验证 BUY_YES 与 NO_TRADE 两场景、落库读回与重复运行幂等。正式 CLI 由当前 clean commit 与 GitHub Actions 再验证。
- 发布门槛包括暂存/历史 credentials scan、V2 27 hashes、frozen tag、working tree、两个平台 CI。最终状态以本提交 Actions 和交付消息为准，不借用 M1 CI。

## Limits and unverified assumptions

所有模型输入/报价均 synthetic，没有真实 Predict.fun integration、模型训练或盲测调参。费用率、扣费单位、split treatment、结算映射、真实成交与延迟尚未由平台证据验证，不声称完整真实 EV 或成交能力。成本/threshold 均由显式配置给定，没有历史优化。

M2 只有最小可执行比例筛选，没有 M3 完整 stale/spread/source/liquidity gate 或 M6 Risk。derived liquidity 保留身份，不实现实际消费锁。ratio 输出按 18 位 HALF_EVEN；总额保留高精度研究计算，不能当 venue ledger/tick rounding。高吞吐、断电和管理员恶意篡改防护未验证。

## Author reading order

1. `models/models.py`：Prediction 如何明确 YES 语义、目标与可用时间。
2. `edge/costs.py`：模拟假设、费用单位、config hash。
3. `edge/engine.py`：VWAP、单位一致的 EV、因果检查与候选选择。
4. `storage/edge_repository.py`：schema migration、不可变写入与读回重算。
5. `tests/v3/test_edge.py`：必需回归、失败注入及边界例子。
