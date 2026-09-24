# V2 protection and V3 migration

## Frozen baseline

- V2 commit: `11c7d06b988b9177f84cf0f34920ad38c4021add`。
- 原 tag `v2.0.0` 保持不变；新增 annotated tag `v2.0.0-frozen` 引用该发布，最终解析为同一 commit；永不 force 移动两者。
- 模型 `v2-9e452c59ebf7`，SHA256 `5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f`。
- config.yaml SHA256 `f45916edcb228df5837596e2e02ea912a1d96c30e96aacbfd36986b49b37a142`。
- 研究 ID `forward-1790136900000`，固定窗口 2026-09-23 12:15 至 2026-09-30 12:15 Asia/Shanghai。
- 启动 M0 时核验 22 个冻结源文件、配置、部署及备份模型、原 release 登记。未读取盲测 Accuracy、PnL 或其他表现来设计 V3。

代码与无凭证配置在 Git，部署及备份模型在原本地 runtime（已保存但没有上传）；原 manifest 和 release sidecar 保留。Git tag 本身不包含被忽略的模型或数据库，也不能保护磁盘免于损坏。

## Worktree isolation

原工作目录继续在 main，供 V2 进程使用；V3 位于原目录下被忽略的 `runtime/worktrees/v3-dev`，独立 Git worktree，分支名严格为 `v3-dev`。worktree 共享对象仓库，但拥有独立索引和源文件。不要把整个工作目录复制提交进 Git。

M0 仅修改 V3 worktree 的 README 和 docs。V2 的 `btc5/`、app.py、config.yaml、model、manifest、release sidecar 和数据库不修改，不重新注册 V2 Git SHA，不重启服务，不重训。运行中的 V2 可以继续正常追加自己的观测；“保护历史”不是停止数据采集。

后续 V3 数据存储仅在 V3 worktree 的 `runtime/v3/`；模型存 `runtime/v3/models/`，实验存 `runtime/v3/experiments/<experiment_id>/`，独立配置 `config/v3.yaml`（未来创建）。不允许路径指向原 V2 数据库、junction、symlink 或共享同一文件；启动前需解析路径并拒绝别名碰撞。

不要在 V3 worktree 用原 app.py 启动另一个 V2 服务。未来 V3 使用独立入口及端口，dashboard 计划 8503；若被占用则失败而非结束已有服务。新 collector 使用独立限流预算，避免挤占 V2 配额。

## Migration sequence

1. M1 独立实现 snapshot 契约、校验、最小实验与存储表，不运行 V2 schema 迁移。使用合成输入测试，不读取当前盲测数据库。
2. M2–M3 以纯函数实现 edge 与 gates。现有预测只作为 baseline adapter 的设计参考，不能直接继承“适用于真实结算”的假设。
3. M4 使用独立预先选定历史数据和实验 ID，完整记录日期、来源及是否曾用于研究。当前 V2 blind window 数据禁止用于开发、阈值/特征选择或校准；结束后若要分析须先记录研究用途和暴露状态。
4. M5–M7 独立 replay、风险与 dashboard。任何真实报价录制另行启动，不把 V2 数据回填成 V3 新观测。
5. M8 打包仅 V3 服务的 Docker 镜像与独立持久卷，secret 通过环境/secret manager 注入；完成健康检查、断线重启、时钟及备份恢复验证后再部署。M0 没有云主机变更。

默认不读 V2 模型 pickle 中的本机 config 来决定 V3 路径；如以后复用模型，先核验受信任 artifact、复制到 V3 私有目录并重新绑定无凭证 V3 配置，记录原模型哈希及 adapter 版本。

## Regression and rollback

每阶段运行完整测试、凭证扫描、V2 哈希校验，再提交单一 milestone commit；不合并到 main，不改冻结 tag。V3 出错时停止 V3 服务，切回上一个 V3 commit，仅处理 V3 数据迁移；绝不恢复或覆盖正在增长的 V2 数据库。

未来落地路径碰撞、V2 只读、重启幂等与负面 fixture 测试。当前没有数据库迁移或新运行服务，因此 M0 无需数据回滚。
