# V3 Milestone 4 delivery

M4 实现可重放的 probability calibration measurement 与 hypothetical edge analytics。未训练或重校准模型，未优化 threshold，未实现 execution、orders、fills、risk、portfolio 或 live trading。完成本阶段后停止，M5 等待单独授权。

## Preflight and frozen boundary

开发前 v3-dev HEAD=`23f648b7bce556e17b39e6e2cfc835ad4bd712bf`，working tree clean。M3 [Actions run 36121831745](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/36121831745) 已核验 success。原 main=`11c7d06b988b9177f84cf0f34920ad38c4021add`，`v2.0.0-frozen` tag object=`fa9757a2e3fd132121a7c7e85307553b1f008a29`；本地与远端引用、27 个 protected hashes 均在 preflight 核验一致。

本阶段没有打开 V2 blind observation 数据库，没有读取表现、选择参数或改变冻结源码、配置、模型及历史记录。本报告不沿用之前的进程检查来声称当前 collector 运行状态。

## Files and review entrypoints

| 文件 | 职责 |
|---|---|
| src/btc5_v3/analytics/models.py | immutable config、outcome、原始输入 archive、结果及 sensitivity 类型 |
| src/btc5_v3/analytics/statistics.py | Brier、binary Log Loss、固定 bins、signed buckets、Spearman |
| src/btc5_v3/analytics/engine.py | 时间因果、lineage、coverage、分组及固定 grid sensitivity |
| src/btc5_v3/storage/analytics_repository.py | schema 4、不可变事务写入、幂等、完整输入重放校验 |
| tests/v3/test_analytics.py | 68 项 M4 回归与持久化测试 |

另新增 analytics/__init__.py、report.py、demo.py 与 [M4 contract](../architecture/V3_M4_CONTRACT.md)。更新 storage/database.py 及 M2/M3 repository 的 schema 4 兼容判断，不改原有数学或准入策略。更新 README、architecture、database、roadmap、包版本 0.4.0 和 CI 的 M4 synthetic demo 步骤。

## Research semantics

YES=1、NO=0、SPLIT=0.5 显式保留；仅实现 synthetic settlement contract。Brier payout 可以包含 split，binary Log Loss/reliability/ECE 排除 split 并报告数量。p=0/1 只在 Log Loss 数值计算中 clip，原始概率和 epsilon 保留。

合法 outcome 必须满足 source/rule/version 和时间条件，只在 post-hoc analytics 中使用。未来、尚不可用的 outcome 不会被当作亏损。固定 bins、signed edge、YES/NO 分离、固定 TTE、UTC 日期及模型/settled direction 分组均保留显式分母与样本量。不把描述性相关当作显著性或稳定交易优势。

hypothetical return = `(net_shares * side_payout - collateral_spent) / gross_shares`，不是实际成交 PnL。全侧经济诊断与原 M3 admissible candidate 视图分开；combined 不代表同时持有两侧的 portfolio。

Sensitivity 按完整预注册 grid 输出：threshold .02/.03/.05/.07/.10/.15，成本 1/1.5/2/3 倍；不选出或推荐任何 threshold。保持原 M3 拒绝及选边，成本 stress 使用明确固定研究条件 `net_edge > .01`。费用、latency/extra 可放大，book notional 不重复计费；原始 M2 不变。

## Scope and limitations

M4 接收显式原始记录 archive，coverage 只针对提供的 archive，不能证明完整数据库覆盖率。多市场 demo 使用独立 research experiment，未削弱 M1 单市场 collector 注册约束。重复市场样本存在相关性；SE/CI、显著性检验和 cluster inference 未实现。Profit Factor/Sharpe 为 unavailable。单一 market 的 settlement revision 不支持。

固定原 M3 admissible cohort 是保守 sensitivity，不模拟降低 threshold 后重新执行整套策略。场景 mean edge 使用原 cohort；场景 realized return 仅使用通过条件且已结算的子集。未知真实结算规则、真实费用及真实 delayed fill 不能由这些 synthetic 结果验证。

## Validation evidence

本地完整旧测试及 M1–M4：**340 passed, 2 skipped**。M4 新增 **68 passed**。两个跳过为 Windows 当前环境的符号链接权限条件；CI Linux 对应执行符号链接检查，Windows junction 检查有平台条件。

回归覆盖：Brier `[.8,.2] / [1,0] = .04`；perfect/over/underconfidence；p=0/1；split；空/单行 bin；ECE weighting；p=.1 的固定边界；全部 edge 边界和 -.10 与 +.10 分离；完整 sensitivity grid 且禁止推荐字段；高 edge 的 STALE_SOURCE 不复活；3x 成本可使 edge 转负但原 M2 不变；改变未来 outcome 不改变 Prediction/Snapshot/Edge/Decision；TTE 只改变分组。

还覆盖不可变 config、低外部 Decimal 精度、输入顺序独立、cutoff/availability、跨实验拒绝、未结算 coverage、lineage、并发幂等、first-created 保留、事务故障回滚、FK、三表损坏检测与禁止 UPDATE/DELETE/REPLACE、迁移回滚、旧 run 不吸收后来标签。

Synthetic demo 含 64 个独立市场：40 个 well-calibrated、20 个 overconfident、4 个 split；包含双方候选、stale refusals、多个 edge/TTE buckets 和四个 UTC 日期。只生成 `runtime/v3/m4-demo.sqlite`、`m4-report.json`、`m4-report.md`，不输出最佳 threshold。这些是软件验证样本，不是实际市场研究结论。

## Delivery verification

CI workflow 在 Windows 与 Linux 上运行完整 pytest、M1–M4 synthetic demos 和 Git history credentials scan，不使用真实 API Key。最终 M4 commit SHA、双平台 CI 链接/状态、提交前后凭证扫描、冻结哈希复核和 clean working tree 以该提交对应的 Actions 与交付回复为准；此文档不提前宣称尚未运行的 CI 成功。
