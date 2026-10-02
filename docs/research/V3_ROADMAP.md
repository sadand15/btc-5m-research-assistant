# V3 milestones and research protocol

当前：**Milestone 8 已实现，等待审查；停止，不开始 M9**。用户批准的 M8 范围为 Data Quality + Validation/Replay + Research Robustness，替代此前的部署提案。只做合成验收及只读源数据研究，不部署、不优化、不读取 blind performance。见 [M8 契约](../architecture/V3_M8_RESEARCH_VALIDATION_CONTRACT.md) 与 [M8 报告](V3_MILESTONE_8.md)。

| 阶段 | 交付与验收重点 |
|---|---|
| M0 | V2 哈希核验、frozen tag、独立 v3-dev、架构/迁移/schema 提案、全套回归、一次文档提交 |
| M1 | RawMarketEvent → validation → valid MarketSnapshot 或 ValidationFailure；独立 raw/validation/snapshot 三层表；YES/NO 映射、深度与时间 invariant；每类坏输入落原始事件及拒绝且零 snapshot；秘密过滤、重试/故障恢复、FK/路径隔离及因果测试 |
| M2 | 双侧 raw/net EV、费用单位及扣除方式、避免重复 spread、NO_TRADE；固定配置假设、YES/NO/成本/阈值边界测试 |
| M3 | Decision + liquidity/source gates；所有拒绝可审计，输入缺失仍有记录；foreign key、幂等、来源/规则/深度/TTE gate 测试 |
| M4 | Calibration、edge buckets、TTE、阈值和成本全曲线；分组时间隔离、统计单位和缺失结果测试，不选历史最优阈值 |
| M4.5 | 周期内价格路径、mid/bid 分离、missing/stale、固定 rebound/TTE 分层、temporary rebound 与 settlement；synthetic-only 因果与重放回归，无执行或优化 |
| M5 | 已实现延迟后 book、depth walk、partial fills/early exit、IOC余量取消、费用/舍入、stale execution、physical lot budget、settlement/ledger；完整政策/latency/size grids，因果/守恒/幂等验证 |
| M6 | 单笔 stake/敞口预留、UTC daily loss、drawdown、连续亏损、kill switch；重启幂等、断线、日界线、暂停恢复测试 |
| M7 | 已实现独立只读 Overview / Health / Risk / Permissions / Reservations / Positions / Executions / Ledger / Timeline / Diagnostics / Provenance；因果/只读/脱敏/损坏诊断/刷新与 UI 测试 |
| M8 | 已实现明确 dataset roles、quality Gate、冻结因果 replay、regime 分层、固定 sensitivity/ablation、市场簇 bootstrap/CI、集中度与 M4 校准漂移；12 个 synthetic cases，独立报告及只读隔离 |
| M9 | 只有严格 OOS/forward 证据支持稳定 edge 后才讨论 meta-model；不是默认待实现功能 |

M4 交付描述性 edge/calibration、候选覆盖率和明确 hypothetical 的 decision-time realized value；没有 M5 延迟成交证据时 actual execution PnL 不存在，profit factor/Sharpe 保持 null。M5 后补齐同一预注册分析，不提前用旧 mock PnL 假装新执行结果。M3 之前/期间未完成风险与执行链时，不启动自动模拟开仓循环。

## Analysis definitions to preregister

- Calibration：Brier、Log Loss（记录 clipping）、ECE、固定概率 bucket 的 n/mean prediction/observed frequency、reliability diagram。Platt/Isotonic 只拟合于训练后的独立 calibration 区间，validation 选方法，最终 test 只评分。按 market/cycle 分组划分并防止跨边界标签重叠。
- 预测快照和每周期决策是不同分析单位，分别报告；不能把同一周期多次高置信度记录当作独立交易。置信区间按 market/cycle 聚类，跨日敏感性另报。
- Edge buckets：预置绝对 raw edge 的 [0,2%)、[2,5%)、[5,10%)、[10,15%)、[15%,∞)；同时拆 YES/NO、正负符号及 net edge，避免绝对值掩盖负 EV。给出 observations、trades、coverage、已结算胜率、predicted EV、ROI、PnL 均值/中位数/标准差/置信区间、profit factor。
- coverage 明确分母为预注册 eligible opportunities；同时公开全部收到事件及每类拒绝数量，不能删除 NO_TRADE 制造漂亮覆盖率。realized return = 净已实现 PnL / 实际支出 collateral；零支出、未结算为 null。
- TTE 固定区间，报告 Accuracy（诊断）、calibration、raw/net edge、交易频率与已实现 PnL；不假设高 Accuracy 等于高价值。
- Threshold sensitivity 固定 2%、3%、5%、7%、10%、15%，保留完整曲线；所有方案共享同一输入时间流，但独立重放资金/风险路径。不重新拟合模型，不从曲线选最高点宣传有效。
- Cost sensitivity 固定 1×、1.5×、2×、3×，区分显式费用与 spread/depth/latency 执行成本。额外压力成本应单独标注；不可既变换执行价又重复扣同一成本。真实费率仍待核实。
- Win rate 分母仅二元已结算 trades；split、pending、missing 独立计数。profit factor 无亏损分母时为 null 并注明，不能静默显示无限收益；样本不足时置信区间也明确缺失。
- Equity 区分 cash、reserved、open-position valuation 与 settled equity。Sharpe 用等间隔日收益及披露的年化因子，不对不规则逐笔回报直接年化；短样本不作稳定性证据。Drawdown 说明使用哪种 equity。

## Causal microstructure features

后续优先实现 spread/normalized spread、bid/ask depth、OBI、quote frequency、recent probability change/velocity、underlying return/realized volatility、TTE、distance-to-threshold、reference divergence。窗口只能包含 received_at/available_at 不晚于决策的事件，按市场和 feed 分组，缺失保持缺失。未来事件扰动不得改变过去特征或决策。

## Per-milestone delivery gate

每阶段：实现最小范围 → 全套 pytest（旧测试继续通过）→ 财务/因果回归 → V2 哈希保护核验 → README/docs → secrets scan → 一个清晰 commit → 阶段报告并停止。报告列新增文件、设计决定、风险、未验证假设、作者应读代码和实际检查结果。

研究结果需保存 experiment_id、Git SHA、模型/数据/特征/配置哈希、日期范围、seed、依赖环境、数据可用时间及全部费用/延迟/成交假设。同一输入重放应产生相同业务事件与结果（wall-clock recorded_at 单独处理），失败也记录，不悄悄删掉实验。
