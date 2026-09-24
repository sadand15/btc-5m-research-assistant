# ADR 0001: isolate V3 and account for executable edge

日期：2026-09-25。状态：M0 接受为后续实现约束，不代表功能已交付。

## Decisions

1. 保留 V2 运行目录和 main，以独立 `v3-dev` worktree 开发。新包 `src/btc5_v3`、新数据库和 runtime namespace，不在冻结包里添加模块。
2. 模块化单体 + SQLite 单 writer，先做可测纯函数和事件契约，不采用微服务/Kubernetes。
3. mid 是比较概率；ask/depth VWAP 才是买入模拟价格。从 ask 算 EV 时不重复扣 spread。所有 edge/cost 必须统一 per-share 单位。
4. Prediction 不等于 Trade。输入缺失、估值失败、流动性失败、风险失败都有持久化 NO_TRADE 原因。模型和市场目标不同不能仅靠价格接近解除保护。
5. 实验时间以事件可获得时间为准；决策不能看到未来报价，执行可以在延迟到达后消费新报价。保存这两条时间边界而非混成一个 timestamp。
6. 当前 V2 blind observation 不作为 V3 设计、调参或模型筛选证据。默认阈值及成本假设在相应 milestone 前记录，完整报告敏感性，不自动选最赚钱点部署。
7. M0 不训练、不迁移数据库、不启动新 collector、不部署云端。每阶段先交付报告，得到继续指令才进入下一阶段。

## Consequences

独立目录和数据增加少量管理成本，但减少活跃研究被导入路径、schema 变动或重启影响的风险。新包不意味着重写已有研究模型；有价值的数学实现可以在审查和测试后复用，运行时绝不把 V2 存储路径当默认值。

paper execution 仍无法证明真实成交、真实费用和排队可得性。未知资料保持显式未验证状态，不用复杂模型掩盖。对流动性与规则无法验证的数据，系统可能长期 NO_TRADE，这是正常结果。
