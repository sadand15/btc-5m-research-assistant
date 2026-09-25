# V3 Milestone 4.5 — Intracycle Price Path Research

本阶段建立可重放的周期内路径研究工具。M4 是 probability/edge evidence，M4.5 是 intracycle market path evidence，M5 execution realism 未实现。本阶段完成后停止，不开始 M5。

## Preflight

本轮实际核验 branch=`v3-dev`，开发前 HEAD=`1a3dd57e8be78e0f09fd190fb16166fed627e78c`，工作区干净。[M4 CI](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/36132775953) success。V2 main=`11c7d06b988b9177f84cf0f34920ad38c4021add`，冻结 tag object=`fa9757a2e3fd132121a7c7e85307553b1f008a29`，27 protected hashes 与冻结基线一致。

未打开当前 V2 blind 数据库、未读取表现、未用 blind period 选择参数、未操作 V2 服务。所有实现测试和演示均为 isolated synthetic fixtures。本轮不根据先前服务状态声称 collector 当前是否运行。

## Implementation and review entrypoints

| 文件 | 职责 |
|---|---|
| src/btc5_v3/path/models.py | immutable path archive/config/result，合法报价投影和因果可用状态 |
| src/btc5_v3/path/engine.py | received/sequence 重建、双新鲜度视图、缺失/截断、分桶和描述性统计 |
| src/btc5_v3/storage/path_repository.py | schema 5 两表、原始 archive、原子幂等写入和读回重放 |
| src/btc5_v3/path/demo.py | 8 个纯合成市场，所有示例及 missing/stale/whipsaw |
| tests/v3/test_paths.py | 数值、时间因果、分桶、拒绝与持久化回归 |

另新增 path/__init__.py、path/report.py 和 [M4.5 契约](../architecture/V3_M4_5_PATH_CONTRACT.md)。更新 V3 storage schema 兼容判断、README、architecture/database/roadmap、包版本和 CI demo 步骤。M1–M4 数学与策略逻辑不变；V2 保护文件不变。

## Coverage and repricing distribution

演示包含 8 个市场、23 个合法报价点，其中 1 个 stale peak，clean view 保留 22 点。演示刻意包含稀疏路径；missing intervals 保持缺失，不能称为完整连续行情。真实研究必须先明确合法历史/V3 数据来源、覆盖窗口、观测密度和独立市场样本；本轮没有导入实际市场路径。

输出起始 price bucket × TTE × YES/NO × mid/bid × freshness 的完整固定表，包含 +.05/.10/.20/.30/.40/.60 的所有阈值、observed-future 分母、独立市场数和 market-balanced fraction。没有未来报价时为 null，不能记作未反弹。额外提供 spread/normalized spread/depth/age/M3 分层、固定 240/180/120/60/30 秒 as-of 视图、市场 range、方向变化、large reversals 与 whipsaw。

默认最少 20 个独立市场；合成演示的 cells 因样本不足均只适合检查实现，不能支持可重复模式结论。价格路径是 observed extrema，不提供实际成交概率。BTC shock/volatility 暂不可用：没有提供具有完整 availability 语义的 BTC series，不能把 settlement reference 当成当前 BTC price。

## Mandatory synthetic evidence

- A：TTE 240/180/60 秒，YES .09/.11 → .18/.21 → .88/.91；mid rebound=.795，bid rebound=.79，最大反弹发生在观察后 180 秒。存在大缺口并显式披露。
- B 原始要求 mid=.90、bid=.25 需要 ask=1.55，违反概率报价 invariant。精确非法报价被拒绝；合法替代 .05/.15 → .25/.95 得到 mid rebound=.50、bid rebound=.20，显示两者不可混为一谈。
- C：.10 → .60 → .08、settlement=0；仍记录 .50 的 temporary rebound。末端 payout 不会替代报价或消除曾经的反弹。
- D：.10 → .30 → .80、settlement=1；记录 .70 rebound 与 winning settlement，二者分别存储。
- Continuation：.10 → .06 → .03；future-only 最大 rebound=-.04，不取绝对值、不截断成零，drawdown=.07。
- Whipsaw：.20 → .70 → .25 → .80；在连续采样段确认两次 large reversal。微小 tick 或跨缺口跳变不会制造方向变化。
- Stale peak：all view 的 mid rebound=.80，freshness-filtered view 为 .10；两个群体独立披露。

上述数值全部来自合成软件回归，不是 BTC 实盘或 V2 blind observation 的统计。

## Causality and storage

按 `(received_at,sequence)` 排序，同 ms 由 sequence 决定，不按 source 或 settlement 重排。Point 保存原始可用时间，显式 observation_at 可延后；未来 Decision 状态不会提前进入 M3 分层。未来 quote 只能改变 PathAnalysisResult，不改变原 Snapshot/Prediction/Edge/Decision。

只新增 path_analysis_runs/results，合计 schema 5 十二表。归档包括 code SHA、config/input hashes、cutoff 与创建时间，原始快照没有写回派生结果。事务失败回滚、重复运行保留首次创建 metadata、UPDATE/DELETE/REPLACE 拒绝、读回完整重放验证。输入覆盖仅代表显式 archive；hash 不能证明外部记录真实性或数据完整性。

## Tests and delivery

本地完整 legacy + M1–M4.5 实际结果：**412 passed, 2 skipped**（Windows 本地符号链接权限条件）。M4.5 新增 **72 项测试**。涵盖要求的 ordering/same-ms/missing/stale/mid-vs-bid/rebound/continuation/whipsaw/settlement/TTE/boundaries/negative-zero/side/causality/config/idempotency/immutability，另含 cutoff、availability lag、固定视图禁止未来回填、M3 状态时间、损坏检测、迁移与事务回滚。

提交验收运行完整旧测试和 M1–M4.5，并在 Windows/Linux CI 运行五个 synthetic demos 及 Git history credentials scan。最终测试计数、CI 状态、M4.5 commit SHA、安全扫描与冻结复核以对应提交的 Actions 和交付回复为准，本报告不提前宣称尚未完成的 CI 成功。

## Limitations and stop condition

无 execution simulation、真实 fills、queue、latency、fees、partial fill 或真实 PnL；bid 不保证成交。没有策略推荐、最优价格/TTE/threshold 或实际入场/退出指令。真实平台 settlement semantics 与真实 BTC shock series 未验证。同市场多行存在相关性，未实现 cluster confidence intervals 或显著性检验；不能从合成数据回答真实市场模式是否存在。完成 M4.5 后 STOP，M5 需单独授权。
