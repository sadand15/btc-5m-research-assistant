# Milestone 0 report — 2026-09-25

范围：保护 V2、创建 V3 分支、架构/迁移/schema/研究路线设计。没有实现 V3 策略模块、数据库迁移、模型训练或云部署。下一阶段 M1 尚未开始。

## Completed

- 初始 Git 工作区干净，main / v2.0.0 对应 `11c7d06b988b9177f84cf0f34920ad38c4021add`。
- 新增 annotated `v2.0.0-frozen`，最终解析到原 V2 commit；原发布 tag 未修改。
- 创建独立 `v3-dev` worktree，原 V2 目录仍在 main。
- 对照原 manifest 和公开冻结记录校验 22 个源文件、config、部署模型、备份模型及已有 release 登记。
- 在 V3 worktree 运行完整 `python -m pytest -q`：**52 passed**。本阶段只有文档，不为文档添加重复行为测试。
- 未查询当前 V2 blind observation 的表现、未根据其结果选择阈值、特征或模型；未打开生产数据库写连接。

## Files

| 文件 | 用途 |
|---|---|
| `README.md` | 增加 V3 M0 状态及文档入口，保留原 V2 说明 |
| `docs/architecture/V3_ARCHITECTURE.md` | 模块依赖、时间/概率/费用契约、执行与风险边界 |
| `docs/architecture/V3_DATABASE.md` | 事件表、关联、版本、幂等、账本和事务设计提案 |
| `docs/architecture/V3_MIGRATION.md` | 冻结身份、独立目录/数据库、分阶段迁移与回滚 |
| `docs/decisions/0001-v3-isolation-and-edge.md` | 重大设计决定及取舍 |
| `docs/research/V3_ROADMAP.md` | M0–M9 验收门槛、统计与敏感性方案 |
| `docs/research/V3_MILESTONE_0.md` | 本报告 |

## Operational finding and limits

检查时本机 8501 和 8502 均无法通过 HTTP 访问，监听查询也未返回这两个端口。因此不能确认 V2 采集仍在运行；端口不可达本身也不能证明后台 collector 已停止。此任务未停止、启动或重启任何服务，没有补写缺失观测。运行健康恢复需单独核实进程、联网与本机凭证可用性，不能把缺失期间伪装成连续采集。

模型和数据的本地保存不等于异地备份。活跃 SQLite/WAL 不能随意复制作为一致快照；未来备份使用 SQLite backup 机制和单独备份位置，不能覆盖原数据库。

真实费用、深度可成交性、延迟、split 支付编码、模型针对平台结算目标的校准都未验证；没有可交易 edge 的结论。数据库 proposal 不是已安装 schema。保护 V2 的实际可执行路径检查和新模块财务逻辑测试将在各里程碑落地。

## Author reading path

先读 V3_ARCHITECTURE 的成本公式和时间契约，再读 V3_DATABASE 的事件链及事务。理解“为什么一个概率预测可能产生 NO_TRADE”是后续代码审查重点。

现有核心代码（仍是 V2）：`btc5/forward.py` 的 freeze/verify 负责冻结；`btc5/predictfun.py` 的 bind_market/normalize_book 负责市场与盘口绑定；`btc5/market.py` 的 provider 区分 live/replay/mock；`btc5/execution.py` 和 `btc5/venue.py` 展示既有模拟及审计流程。阅读并不代表 V3 会直接照搬其费用和结算假设。

阶段结论：M0 结束后停止。下一次经作者指令进入 M1，只实现 snapshot、validation、独立 storage 和关键测试。
