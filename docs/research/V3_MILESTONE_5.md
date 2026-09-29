# V3 Milestone 5 — Execution Simulation + Intracycle Early-Exit Research

M5 实现离线、时间因果正确、可重放的执行研究。M4.5 = path evidence；M5 = execution realism；M6 = risk permission，未实现。没有真实账户、钱包、签名、真实订单或真实资金操作。完成后停止，不开始 M6。

## Preflight and V2 boundary

开发前分支 v3-dev，HEAD=`e144c31384447157497a4848d63679fc2a1fe89b`，working tree clean；[M4.5 CI](https://github.com/sadand15/btc-5m-research-assistant/actions/runs/36140492555) 已实际核验 success。V2 main=`11c7d06b988b9177f84cf0f34920ad38c4021add`，冻结 tag object=`fa9757a2e3fd132121a7c7e85307553b1f008a29`，本地/远端引用及 27 protected hashes 一致。

本轮没有打开当前 V2 blind 数据库或读取表现，没有选择/优化 latency、threshold、价格/TTE buckets 或退出策略；未操作 V2 进程、模型、配置和历史记录。

## Implementation and review files

| 文件 | 职责 |
|---|---|
| src/btc5_v3/execution/models.py | immutable ExecutionConfig、ExitPolicy、intent、opening position、result 与固定 grids |
| src/btc5_v3/execution/depth.py | Decimal ASK/BID walk、partial/zero fill、physical liquidity budget |
| src/btc5_v3/execution/engine.py | 因果选书、双侧执行、exit latency/retries、费用、结算与守恒 ledger |
| src/btc5_v3/storage/execution_repository.py | schema 6、原子不可变写入、幂等及逐表重放核验 |
| tests/v3/test_v3_execution.py | M5 核心数值、因果、费用、守恒、重放、损坏和事务回归 |

另新增 execution/demo.py、report.py、__init__.py 与 [M5 执行契约](../architecture/V3_M5_EXECUTION_CONTRACT.md)。更新 V3 schema compatibility、README、architecture/database/roadmap、包版本和 CI demo。旧 V2 测试文件不变；新增测试使用唯一文件名，避免 pytest 与旧 tests/test_execution.py 冲突。

## Execution semantics

M3 NO_TRADE 不生成 intent；requested size 不得超过 M3 原批准量。Entry 在 decision+latency 之后寻找第一份 source/received/available 均不早于 ready 的 fresh OPEN book，按 availability/received/sequence 确定顺序。买 ASK、卖 BID，逐档计算 VWAP；IOC 剩余明确取消。无合法报价则等待至固定 deadline，过期 NO_FILL；尚未到 deadline 则 pending。绝不回用 signal book 或在延迟盘口价格之外再扣人工 latency cost。

Partial entry 只创建实际 net shares。Partial exit 只移除成交及明确 share fee，其余继续存在，可在后续因果 trigger 下再次退出或结算。Entry/exit/settlement 费用分别记录 collateral 与 shares。Gross PnL 明确为实际数量流（已含 share deductions）但未扣 collateral fee 的结果，不能再把 share fee 当 collateral 扣一次。

Ledger 每次资产变化都有事件来源和相反账户分录，逐资产平衡；net opening shares = exited inventory + settled inventory + remaining。成交源、订单、fill、position、exit attempt、settlement 和费用均可重放。

## Synthetic mandatory regressions

- Full entry：50 shares，20@.61 + 30@.62，VWAP=.616。另测试 10@.50 + 20@.55 + 10@.60，40 shares 的 VWAP=.55。
- Partial entry：请求100、后续depth60，只创建60份 position，40份 IOC 取消。
- Latency：signal ask=.20、later=.35 按 .35 成交；signal=.50、later=.40 也按 .40 成交，不只模拟 adverse slippage。
- Rebound latency：trigger bid=.70，延迟后 bid=.35，模拟成交使用 .35，不使用 .70。
- Temporary rebound：零费用独立 fixture 中 entry=.10、exit=.60、payout=0，100份 simulated PnL=50，hold=-10；同样路径 payout=1 时 hold=90，提前退出反而少40。
- Partial exit：100份，20@.80 + 30@.77 + 40@.70，最多退出90，10份以 split .5 结算。另一 fixture 先退出30、再40、最后30结算。
- Thin/stale/no-book：mid 上升但 bid depth=.000001 只能微量退出；触发后缺少因果新报价保留 NO_EXIT_FILL；stale trigger 单独计数。
- Shares fee：entry、exit、settlement 都不再重复扣现金；退出预留 inventory fee 并处理 1e-18 舍入，100% entry share fee 与 dust 也保持守恒。
- Future event：加入 t+10000 的 book 不改变此前 intent、fill、opening position 或 business event；改变 future outcome 不改变已经生成的 fills。

这些是合成回归断言，不是实际市场收益结果。

## Intracycle Reversal Execution Study

H1 保持未证实。演示使用8个独立 synthetic markets：full hold、partial entry、adverse latency、temporary rebound、hold better、missed exit、multiple partial split、derived NO。固定 Entry/Exit fees=.005、Settlement fee=.001，均为研究假设，不代表 Predict.fun 当前费率。

完整输出160个 case/grid rows：每市场10个 exit policies（HOLD、六个 rebound、三个 fixed TTE），6个 latency、4个 size。采用 one-factor-at-a-time，非全因子搜索：默认250ms和M3批准100份，latency/size研究使用 BID_REBOUND +.20。不按 PnL 排序，不返回最优参数。

按 M4.5 起始价格/TTE buckets、YES/NO 和 rebound grid 输出完整 trace 与 funnel：observed path rebound、causal trigger、attempt、fresh delayed book、rebound survival、sufficient depth、full/partial/failed/pending exit。Observed rebound 是 position/path 级，attempt 是执行尝试级，多次退出不能伪装成独立样本。退出失败后持仓结算仍进入比较；无入场成交的终止路径结果为0，不删除；未结算 open position 为 null，保留分母。

Hold comparison 使用同一实际入场 fill/net quantity/cost，比较 early simulated exit 加剩余结算与全部 hold 的结果。只能回答记录盘口和明确假设下的 counterfactual simulation，不能回答真实账户必然能成交或应该提前卖。

## Persistence and tests

Schema 6 共21表；新增 execution_runs/results 和七张 simulated audit projections。同实验 FK、原子提交、不可变 trigger、first-created 幂等、完整 replay/逐表 hash-count 比对，不改既有快照。运行/未来归档 ID 与稳定业务事件 ID 分离，不把不同 cutoff/policy 的重复 ledger 前缀合并成一个资金账户。

M5 新增86项测试；完整 legacy + M1–M5 最终本地结果为 **498 passed, 2 skipped**（本地 Windows 符号链接权限条件）。最终提交前运行完整回归并执行 staged/history secrets scan、V2 hashes/tag/main 复核。CI 在 Windows/Linux 上运行完整 pytest、六个 synthetic demos 和历史凭证扫描，不使用真实 API Key。最终 commit、测试计数、CI 状态和 clean working tree 以对应 Actions 与交付回复为准，不提前宣称未运行的 CI 成功。

## Unverified assumptions and stop

真实 venue settlement semantics、费率、tick/rounding、queue priority、隐藏深度及跨快照持久订单身份未验证。每份记录的显示深度不是成交保证；来自不同快照的 lot IDs 不能证明外部订单真正补充过。Zero latency 仍用独立后续记录，不代表即时成交。没有 portfolio cash permission、杠杆、Kelly、止损、drawdown 或 M6 risk engine。

当前证据全部 synthetic-only；不宣称实盘盈利或 H1 已在真实市场验证。M5 完成后 STOP。
