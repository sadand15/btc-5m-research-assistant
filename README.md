# BTC 5M Research Assistant

> **V3 development branch — Milestone 4.5 intracycle path evidence.** 在 M1–M4 基础上增加周期内 YES/NO、mid/bid 路径研究，保持 missing/stale 与 post-hoc 时间边界。无 execution simulation、订单、策略推荐或阈值优化。见 [M4.5 报告](docs/research/V3_MILESTONE_4_5.md) 与 [路径契约](docs/architecture/V3_M4_5_PATH_CONTRACT.md)。下方 V2 文档仍描述冻结发布。

## V3 M4.5 quick start

仅在独立 v3-dev worktree 或新 clone 中执行，不切换部署 V2 的原目录。V3 包只用标准库，完整 legacy tests 仍需原 requirements。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m btc5_v3.demo --project-root .
.\.venv\Scripts\python.exe -m btc5_v3.edge.demo --project-root .
.\.venv\Scripts\python.exe -m btc5_v3.decision.demo --project-root .
.\.venv\Scripts\python.exe -m btc5_v3.analytics.demo --project-root .
.\.venv\Scripts\python.exe -m btc5_v3.path.demo --project-root .
```

M4.5 path demo 使用 8 个 synthetic markets，覆盖 reversal、continuation、whipsaw、temporary rebound、split、宽 spread 和 stale peak。仅写 `runtime/v3/m4-5-demo.sqlite`、`m4-5-report.json`、`m4-5-report.md`。报告同时提供 mid/bid 全部固定 rebound grids 和 TTE/质量分层，观测缺口不插值。Bid 只是可观察价格，不保证成交；这些合成结果不能证明真实市场有可重复规律。没有合法 BTC series 时 shock conditioning 为 unavailable。

各 CLI 要求 clean commit，以实际 Git SHA 标识研究。M4 demo 使用 64 个独立 synthetic markets，包含校准/过度自信概率、YES/NO、不同 TTE、stale 拒绝和 split；只写本 worktree 的 runtime/v3/m4-demo.sqlite、m4-report.json、m4-report.md。同版本重跑幂等，不访问 V2 数据或真实平台。

报告包含 coverage、Brier payout/binary、binary Log Loss、ECE/MCE/reliability bins、signed edge buckets、YES/NO/combined、Spearman、TTE/UTC day/model groups、完整 threshold/cost grids。原始概率保留；split 单独计数，不进入 binary Log Loss/ECE。收益全部是 **decision-time hypothetical realized value**，不是 execution PnL。Profit factor/Sharpe 保持 unavailable。

**sensitivity analysis ≠ optimization**：固定 thresholds 2/3/5/7/10/15%，cost multipliers 1/1.5/2/3。成本压力固定使用 strict edge > 1% 的研究条件；只放大费用和 latency/extra 假设，不再扣 spread/depth。M3 拒绝永不被敏感性分析复活，不重选 side。报告不推荐参数。

Analytics 只分析调用方明确提供的同一 experiment 归档，不静默扫描数据库或跨 experiment 合并。覆盖率分母限于该归档，不宣称覆盖所有实际采集；输入完整性须由外部采样证据支持。归档保存原 Prediction/Snapshot/Edge/Decision JSON 与 hash，结果可重放。

层次为 **M1 trustworthy data → M2 economic edge → M3 admissibility → M4 probability/edge evidence → M4.5 intracycle path evidence → M5 execution realism**。M5 与 Risk/portfolio 尚未实现。无训练、拟合、参数优化、真实成交或 live trading claim。

## Overview

**RESEARCH / PAPER TRADING ONLY.** BTC 五分钟方向概率研究助手，支持实时市场监控、historical replay、walk-forward validation、probability calibration 和 paper execution。不包含真实资金自动交易、钱包签名或真实订单提交。

## Current Version

**V2** — `main` 对应 `v2.0.0`；`v1.0.0` 保留第一版可恢复源码。模型、特征、calibration 和 threshold 在本次发布整理中保持不变。

## Version History

### V1.0.0

- distance_time、Logistic Regression、LightGBM。
- 基础 BTC 5m prediction、概率 calibration、初步 paper trading。
- Binance 历史与实时数据、SQLite 记录、Streamlit。

首轮 LightGBM 测试 Accuracy 约 74.78%，测试集 3,212 个快照、803 个周期；后续审计同样本 Naive 约 74.63%。这是方向分类结果，不能解释为交易收益或独立交易胜率。见 [V1 Review](docs/V1_REVIEW.md)。

### V2.0.0

- cycle leakage audit、naive baseline、真实秒级数据的 5-second replay。
- walk-forward validation、regime analysis、confidence / coverage analysis。
- probability calibration、short-term micro features。
- single-flight inference、stale-data protection、post-inference market re-check。
- MarketDataProvider、live read-only quote recording、replay/mock quotes。
- fee/spread/slippage/latency simulation、audit trail。
- Streamlit dashboard、轻量手机网页、forward blind observation。

详见 [CHANGELOG](CHANGELOG.md)、[V2 Review](docs/V2_REVIEW.md) 和 [架构](docs/ARCHITECTURE.md)。

## Important Research Result

目前复杂 ML 模型的方向 Accuracy **没有明显超过 simple current-side / naive baseline**。14 天秒级研究中 Naive 73.7362%，LightGBM 73.7782%；90 天研究中 Naive 74.4985%，LightGBM 74.3827%。不同研究样本粒度不同，不能直接横向解释成提升。

模型目前更值得研究的是 **probability estimation**，而非声称存在稳定交易 alpha。历史日期此前已经被查看，不属于新的前瞻盲测；置信度快照不能当作独立交易胜率。模型目标为 Binance proxy，Predict.fun 的 Chainlink BTC/USDT Top-of-Book 结算目标不同。保持跨价格源保护，未验证真实成交的收益不作盈利证据。

## Installation

Windows，Python 3.12（项目要求 3.11+），PowerShell：

```powershell
git clone https://github.com/sadand15/btc-5m-research-assistant.git
cd btc-5m-research-assistant
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Private 仓库需要已有 GitHub 访问权限。`requirements.lock.txt` 保存原运行环境的完整版本快照；一般安装和 CI 使用 `requirements.txt`。模型与大数据不随 Git 下载；首次启动会下载数据并训练，耗时取决于网络与电脑。

## Running

以下 research 命令用于新克隆或独立实验目录，**不要覆盖当前冻结部署**。

```powershell
# Research: fixed historical windows, then V2 experiments
.\.venv\Scripts\python.exe research.py seconds --days 14 --step 5 --end 2026-09-22
.\.venv\Scripts\python.exe research.py regimes --days 90 --end 2026-09-22
.\.venv\Scripts\python.exe v2.py research

# Paper: mock execution scenarios; recorded CSV/JSON via --quotes
.\.venv\Scripts\python.exe v2.py paper

# Live read-only monitoring, paper engine and dashboards
.\.venv\Scripts\python.exe app.py

# Dashboard only, using existing local runtime data
.\.venv\Scripts\python.exe -m streamlit run dashboard.py --server.address=127.0.0.1

# Tests: no live key required
.\.venv\Scripts\python.exe -m pytest -q
```

完整页面：[localhost:8501](http://localhost:8501/)。`app.py` 同时提供手机轻量页面：[localhost:8502](http://localhost:8502/)。iPhone/iPad 与电脑连接同一 Wi-Fi 后，访问 `http://<电脑局域网IPv4>:8502/`；电脑须开机，防火墙允许私有网络访问。手机上的 localhost 指手机本身。当前默认绑定 `0.0.0.0` 供局域网使用，页面无身份认证，不应直接暴露到公网。

## Environment Variables

`PREDICTFUN_API_KEY`：Predict.fun 只读行情 Key，由运行进程环境提供。`.env.example` 只有空变量模板；程序**不自动加载 .env**。在本机安全设置环境变量后启动进程，不把值写入源码、配置、日志、数据库或提交。没有 Key 时行情服务等待，不伪造真实报价；离线测试不需要 Key。

## Project Structure

| 路径 | 用途 |
|---|---|
| `btc5/` | 行情、特征、研究、推理、模拟执行、前瞻观察 |
| `app.py`, `dashboard.py`, `mobile.py` | 启动入口与两种界面 |
| `research.py`, `v2.py`, `evaluate.py` | 历史研究、V2 实验、评估 |
| `venue.py`, `forward.py` | 行情录制/回放与前瞻报告 CLI |
| `config.yaml` | 无凭证的研究配置 |
| `tests/` | 离线自动化测试 |
| `scripts/` | 审计、报告、凭证扫描与发布元数据 |
| `docs/` | 历史 Review、冻结方案、模型身份、架构与版本来源 |
| `data/README.md` | 数据来源和重新生成方式 |
| `runtime/` | 本地数据、模型、日志、数据库，全部忽略 |

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/security_scan.py index
.\.venv\Scripts\python.exe scripts/security_scan.py history
```

V1 恢复版本有 16 项测试；V2 原有 52 项测试。测试使用本地样本、临时数据库和 mock，不调用真实行情接口。GitHub Actions 在 Python 3.12 的 Windows/Linux 上安装依赖并运行 pytest 和历史凭证扫描，不设置真实 API Key。

## Data

Git 不保存 `.env`、运行 SQLite、完整 observations、历史 parquet/CSV、行情 ZIP、日志、缓存、venv 或模型二进制。必要的小型 Markdown 报告与公开冻结哈希保留。未全局忽略 `.json` / `.csv` / `.parquet`；大型自动生成文件归于 `runtime/`。详见 [数据与复现](data/README.md)。

## Forward Blind Test

当前模型已冻结，正在进行前瞻 observation。预先固定窗口为 **2026-09-23 12:15 至 2026-09-30 12:15（北京时间）**，研究 ID `forward-1790136900000`，计划 2,016 个周期。此处记录启动时的方案，窗口结束或后续结果不会用于改写过去说明。

模型 `v2-9e452c59ebf7`，SHA256 `5b4a46e5394c095848cc3191b9f1f8cb4de7366fc1ed496c88baf0561ce6749f`。主分析取每周期剩余 115–120 秒内第一次有效联合快照；缺失、未结算、50/50 单列，不补造数据。见 [冻结方案](docs/FORWARD_TEST_PROTOCOL.md) 和 [公开哈希记录](docs/FROZEN_MODEL.json)。

```powershell
.\.venv\Scripts\python.exe forward.py report
# Release registration on the original frozen observation host, after tagging
.\.venv\Scripts\python.exe scripts/register_release.py --version v2.0.0
git rev-parse 'v2.0.0^{commit}'
```

`forward_release_provenance` 表和 `runtime/forward/release.json` 记录 Git SHA、版本、模型及配置哈希，并通过 `run_id` 关联观测。注册时校验提交中的源码与原冻结哈希完全一致，不改模型、原 manifest 或观测行。该元数据是发布时对既有冻结研究的核验归属。七天观察首先验证管线与目标差异，不证明稳定盈利。
