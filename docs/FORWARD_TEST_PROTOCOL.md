# predict.fun 规则核对与 7 天前瞻观察

本轮已正式冻结：**2026-09-23 12:15 至 2026-09-30 12:15（北京时间）**，研究 ID `forward-1790136900000`，模型 `v2-9e452c59ebf7`。后台真实行情与结算查询均已连接。新增验证后共 **52 项测试通过**；Streamlit 实际渲染通过（8 metrics / 3 tabs / 19 tables）。

## 已核实的规则

来源是实际只读 API 返回的市场 description、category 时间和 variantData，原文及抓取时间保存在 `runtime/forward/rules-evidence.json`。不是根据第三方机器人推测规则。

- 当前 BTC 5 分钟市场使用 **Chainlink BTC/USDT Top-of-Book** 数据流。流 ID 为 `0x0003ef42b4d20a19409a187c39670a6f5be7ce17fc78c290d25eb45bbf769d37`。
- 规则描述该流取 Binance 买一、卖一的中间价，并换算为报价币种；不等于 Binance 最新成交价。不能把现有成交价模型直接当作该合约已校准的胜率。
- 周期以 API `startsAt` / `endsAt` 的 UTC 时间为准，必须恰好 300 秒；开盘参考使用平台 `startPrice`。尚未发布开盘参考价时等待，不用其他价格补造。
- 结束价高于开盘价为 Up，低于为 Down；**完全相等为 50/50 支付**，不是 Down，也不是旧模拟器的退款规则。
- 官方要求用结束时刻之前那根五分钟柱的 close 核验最终价。API 原文没有给出更细的采样时间、时间戳取整或延迟发布保证，因此不自行假设精确到某个毫秒的替代价格。
- Chainlink 不可用或不适合结算时，官方可使用可靠来源共识。程序只接受平台公布的明确结果，不自行启动替代预言机。

官方价格流：[BTC/USDT Top-of-Book](https://data.chain.link/streams/btc-usdt-topofbook-datalink)。API 说明：[Predict API](https://dev.predict.fun/)。该价格流网页本次直接访问受限，规则证据来自已认证的官方市场 API；没有将其他平台的 BTC/USD/TWAP 规则混入。

## 结算实现边界

已实际收到正常 Up/Down 的官方 `RESOLVED` 和 `resolution.indexSet`，能够记录结算。官方 schema 的 outcome status 目前只列 WON/LOST，尚无实际 50/50 样本来验证其 API 编码。因此遇到无法明确解析的结算时保留待结算，并保存原始响应；即使 startPrice=endPrice，也不凭此猜测最终分配。模拟引擎已支持明确给定的 0.5 支付，前瞻二分类指标会单独列出 split，不算赢或输。

## 冻结的观察方案

运行 `python forward.py start` 后，从下一个完整五分钟周期开始，固定 **7×24 小时、2,016 个计划周期**。准确起止时间写入 `runtime/forward/manifest.json`，不可覆盖重置。不是把之前已经看过的历史结果重新算作前瞻。

冻结内容包含模型副本与 SHA256、当前参数、研究代码哈希。启动服务会校验；同数据库修改这些内容会拒绝继续运行这个冻结研究，训练入口在窗口内拒绝重训部署模型。需要修复影响研究的代码时应明确记录中断并新建研究，不能悄悄拼接结果。

主分析预先固定：每周期 **剩余 115–120 秒内第一次有效联合快照**。要求同一周期、模型已实际计算完成、输入和报价在有效期内、在模型支持的时间范围内，且市场规则及 feed ID 与冻结证据一致。

对同一批已结算周期比较：冻结模型、Binance 当前价相对开盘价的 Naive 方向、真实 UP 盘口中间价。前两者明确标为 Binance proxy；盘口中间价也是比较基线，不是可成交价。一个周期只贡献一次主分析结果。

保存所有盘口与对应预测 ID、实际完成时间、输入时间、费用、两种开盘参考、等待理由；拒绝入场也记录。缺失周期、过期报价、未知结算和 50/50 单独统计，不删掉后只展示好样本。

价格源保护保持开启，**不产生跨源模拟仓位来凑收益**。未有成交/结算证据时 PnL 为 null；这轮先验证记录完整性与预测目标差异。7 天不能证明稳定盈利。

## 运行与查看

```powershell
# 查询冻结窗口、覆盖率和已结算的配对比较
.\.venv\Scripts\python.exe forward.py report
# 核对已录制的官方规则证据
.\.venv\Scripts\python.exe scripts\check_venue_rules.py
```

Streamlit 的研究页新增“7 天冻结前瞻观察”；手机轻量页显示冻结时间和模型版本。服务继续后台录制，不需要手动每轮启动。

电脑需保持开机、联网、未休眠；系统无法补回关机期间从未收到的真实盘口。到期后保留原始录制，但研究报告只纳入固定窗口。尚未安排自动消息提醒；到期可运行上述报告命令。

当前 API Key 仅在后台进程环境中。重启电脑或从新终端重启服务时，应先在本机设置 `PREDICTFUN_API_KEY`；不要将它写入项目配置或发送到聊天。

## Release provenance

发布整理不更改研究窗口、模型或预测代码。标记提交后执行 `python scripts/register_release.py --version v2.0.0`，校验 Git 中的源文件、模型和配置后，在现有数据库新增 `forward_release_provenance` 表，并写入忽略的 `runtime/forward/release.json`。通过 `run_id` 关联所有 `forward_observations`；不会覆盖原始 manifest 或修改观测行。

字段为 `git_commit`、`version`、`model_hash`、`config_hash`、`policy_hash`。config_hash 为 config.yaml 原始字节 SHA256；policy_hash 为排序、紧凑 JSON 格式的冻结策略 SHA256。哈希以 Git 仓库原始字节为准。
