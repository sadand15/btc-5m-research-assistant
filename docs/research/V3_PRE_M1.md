# Pre-M1 operational health and schema correction

2026-09-25。此报告仅涉及运行健康、采集缺口、恢复边界及数据契约，不包含当前 blind-test 表现。未运行 forward.py report，未查询 outcomes、fills、settlements 或观测 payload。M1 未开始。

## V2 operational health

以下时间均为 Asia/Shanghai（UTC+08:00）。

| 项目 | 核实结果 |
|---|---|
| 停止被确认时间 | 2026-09-25 01:28:32；本次首次取得系统级进程与端口证据 |
| 进程 | 系统查询未发现 Python 进程；原 launcher PID 70132 未运行，app / collector / venue / dashboard 均未运行 |
| 端口 | 8501、8502 无监听；不只是 dashboard 停止 |
| 最后真实 observation | 2026-09-23 23:06:42.076 |
| 最后 venue quote received_at | 2026-09-23 23:06:42.076 |
| 最后 prediction timestamp | 2026-09-23 23:06:42.016 |
| 最后 heartbeat | 2026-09-23 23:06:42.427 |
| 主库文件最后写入 | 2026-09-23 23:05:52.606；WAL 最后写入 23:06:42.501，不能只看主库文件 |
| 第二次采样时间 | 2026-09-25 01:29:28.064 |
| 追加情况 | 两次采样间隔约 45 秒；observations、venue quotes、predictions 的行数与 MAX timestamp 均不增长 |
| 最后 observation 距第二次采样 | 94,965.988 秒，约 26 小时 22 分 46 秒 |
| 已有 state | connection / venue_status 虽为 CONNECTED，但时间停在上述旧时刻，不能视为当前连接 |

SQLite 使用 URI mode=ro 及 query_only；仅 SELECT 三张允许表的 MAX(timestamp/received_at)、COUNT(*)，和 state 中明确列名的 heartbeat/event_time/forward_last_quote/connection/venue_status。没有实例化会执行 DDL 的 V2 Database 类。没有读取预测值或观测 payload。

Binance 公共时钟探测 HTTP 200，单次往返约 1.9 秒，服务时间相对本机请求中点约 +468 ms；该精度不足以证明毫秒级时钟正常，只能确认基本连通。Predict API 无凭证探测 HTTP 401，说明端点可达但没有验证认证后的 feed。Process/User/Machine 三种环境范围均无 PREDICTFUN_API_KEY 或旧变量，检查仅输出存在性，不输出值。

历史运行日志仅按健康类别提取时间和出现标记，未展示原始行：存在断线、stale、异常及重新连接记录；最后运行日志写入为 2026-09-23 23:06:42。所查日志未命中 database locked、API key missing 或认证失败标记；当前缺少环境凭证不能反推此前凭证无效。background 日志没有最后停机对应的显式停止标记，因此不能断言停机原因。全局旧日志中早于本轮的停止记录不作为本次停机原因。

## Gap and recovery

确定没有新 observation 的区间为 **(2026-09-23 23:06:42.076, 2026-09-25 01:29:28.064]**，截至该次采样仍未结束。真实进程退出时刻未知；最后 observation 时刻不等于已确认的退出时刻。缺口不回填，不把历史行情重放成真实观测。

**没有恢复，也没有重启。恢复时间为 null。** 两项阻塞：

1. 当前服务启动环境没有 Predict.fun Key，无法恢复认证盘口采集；没有从聊天记录、日志或其他进程提取旧凭证。
2. 原冻结代码 `btc5/live.py:LiveEngine.repair` 在启动和重连时会下载缺失历史 K 线，`Database.import_minutes` 执行 upsert，可能更新已有 candles；启动也含 pending-position 恢复逻辑。原入口无法保证本次要求的“无 backfill、无历史行修改”。即使 observation 本身不回填，也不能据此忽略其余数据库写入。

不能同时通过原启动入口满足上述限制，因此保持停止状态。未来恢复需要明确允许的写入范围及安全启动方案，并在本机安全提供有效凭证；本任务不改冻结代码或绕过保护，不将恢复条件当作已经满足。

核验的原冻结身份（不是一次已发生的恢复）：

- commit SHA：`11c7d06b988b9177f84cf0f34920ad38c4021add`，原目录仍为 main。
- `v2.0.0-frozen` annotated tag object：`fa9757a2e3fd132121a7c7e85307553b1f008a29`，preflight 前后保持不变。
- model SHA256：`5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f`。
- config SHA256：`f45916edcb228df5837596e2e02ea912a1d96c30e96aacbfd36986b49b37a142`。
- 按 M0 基线核对 27 个受保护文件，包括 manifest、release 登记及模型备份；无变更。

## M1 schema correction

新增 raw_market_events → market_validation_events → 合法 market_snapshots / ValidationFailure 三层契约。无效数据必须保留安全原始事件与拒绝原因，不生成半合法 snapshot。严格 invariant 在创建时成立，下游无需检查 validation_status 才能判断对象是否合法；后来变 stale 仍由当前时间门槛拒绝。认证信息不进入 payload 或 artifact，无法安全留存时明确记录脱敏和可复现性损失。

修改文件：README、V3_DATABASE、V3_ARCHITECTURE、V3_ROADMAP；新增 ADR 0002 和本报告。仅文档，没有运行 schema migration，也没有实现 M1。

## Preflight and remaining assumptions

完整旧测试已在独立 V3 worktree 运行：**52 passed**。该目录无 V2 生产数据库或模型，因此测试未读取当前 blind observations。暂存及历史凭证扫描、Git 状态和受保护哈希检查作为独立 pre-M1 提交前的门槛。CI 状态以此提交对应 Actions 为准，不能沿用上一提交的成功状态。

尚未验证：实际退出原因、当前认证凭证可用性、重启后 feed、满足禁止历史写入的恢复方法、schema proposal 的实现级约束和故障恢复。此阶段交付不代表 V2 已恢复健康或 M1 已获准开始。
