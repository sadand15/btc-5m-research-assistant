"""Regenerate the human review solely from persisted out-of-sample results."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from btc5.config import ROOT
from btc5.v2research import audit,stats


def enrich(mode):
    d=ROOT/'runtime/v2'/mode;r=json.loads((d/'report.json').read_text());f=pd.read_parquet(d/'samples.parquet');te=pd.read_parquet(d/'heldout.parquet')
    cycle=f.groupby('cycle_id').price.first()
    regular=cycle.index.to_series().diff().rolling(288).max().eq(300000)
    ret=cycle.pct_change(288,fill_method=None).where(regular)
    vol=cycle.pct_change(fill_method=None).rolling(288).std().where(regular)
    q1,q2=r['regimes']['volatility_thresholds']
    rt=te.cycle_id.map(ret).to_numpy();v=te.cycle_id.map(vol).to_numpy()
    groups={'trend_24h':{'rising':rt>.01,'falling':rt<-.01,'sideways':abs(rt)<=.01},
        'volatility_24h':{'low':v<q1,'medium':(v>=q1)&(v<q2),'high':v>=q2},
        'activity':{'fast_trend':abs(rt)>.02,'quiet_market':(abs(rt)<=.005)&(v<q1)}}
    for category,masks in groups.items():
        r['regimes']['groups'][category]={}
        for group,mask in masks.items():
            scores={}
            for name in r['models']:
                p=te['p_'+name].to_numpy();conf=np.maximum(p,1-p);hm=mask&(conf>=.8)
                scores[name]={**stats(te.loc[mask],p[mask],len(te)),
                    'high_confidence':stats(te.loc[hm],p[hm],int(mask.sum()) or 1)}
            r['regimes']['groups'][category][group]={'cycles':int(te.loc[mask].cycle_id.nunique()),**scores}
    te['cycle_start']=te.cycle_id;te['cycle_end']=te.cycle_id+300000
    te['cycle_open']=te.price/(1+te.distance_percentage);te['current_price']=te.price
    te['distance']=te.price-te.cycle_open
    te.to_parquet(d/'observations.parquet',index=False)
    (d/'report.json').write_text(json.dumps(r,indent=2,allow_nan=False),encoding='utf-8')
    return r


def mdtable(rows,columns):
    def fmt(x):
        if x is None:return 'N/A'
        if isinstance(x,float):return f'{x:.6f}'
        return str(x)
    return '\n'.join(['| '+' | '.join(columns)+' |','|'+'|'.join(['---']*len(columns))+'|']+
        ['| '+' | '.join(fmt(r.get(c)) for c in columns)+' |' for r in rows])


def pct(x):return f'{x:.2%}' if x is not None else 'N/A'
def utc(ms):return pd.to_datetime(ms,unit='ms',utc=True).isoformat()


def main():
    reports={k:enrich(k) for k in ('seconds','regimes')};a=reports['seconds'];b=reports['regimes'];name=a['selected_model'];m=a['models'][name]
    audits={}
    for mode in ('seconds','regimes'):
        old=json.loads((ROOT/'runtime'/mode/'report.json').read_text());f=pd.read_parquet(ROOT/'runtime'/mode/'samples.parquet')
        parts={k:f[(f.cycle_id>=v['first_cycle'])&(f.cycle_id<=v['last_cycle'])] for k,v in old['split'].items()}
        audits[mode]=audit(parts)
    (ROOT/'runtime/v2/v1_audit.json').write_text(json.dumps(audits,indent=2),encoding='utf-8')
    lines=['# BTC 5M V2 Review','',
        '基于现有 V1 迭代。研究、模拟执行与只读实时监控可运行；predict.fun 真实盘口尚缺开发者 Key，因此不报告真实报价盈利。',
        '', '## 数据与无泄漏审计','',
        '当前 V1 代码与保存的两套样本分区未发现 cycle 跨 train/calibration/test 的泄漏。分钟特征只读之前的完整分钟与当前部分柱；秒级未来价格扰动测试通过。原 current_side_baseline 的 .75/.25 是人为概率，本版改成硬方向 Naive，并明确其 0/1 仅用于评分。',
        '', 'V2 新增独立 validation：train 50%、calibration 15%、validation 15%、test 20%，按完整 cycle 分配。只用 validation Brier 选校准方式和基础主模型；测试不参与选择。没有为了保住原 75% 而挑日期或删坏结果。注意：这些测试日期在前一轮研究中已被查看，本轮属于固定规则下的历史样本外复核，不是全新盲测；下一步需要冻结模型后的前瞻留出。',
        '', '硬 Naive 的 Brier / Log Loss 反映确定性错误（Log Loss 按 sklearn 浮点精度裁剪），不能将它的“100% confidence”解释为真实胜率。', '']
    for mode,r in reports.items():
        lines+=['### '+mode,'',f"周期 {utc(r['dataset']['first_timestamp'])} 至 {utc(r['dataset']['last_timestamp'])}；{r['dataset']['samples']:,} observations，{r['dataset']['cycles']:,} cycles。",'',
            mdtable([{'partition':k,**v,'start_UTC':utc(v['first_cycle']),'end_exclusive_UTC':utc(v['last_cycle']+300000)} for k,v in r['split'].items()],['partition','samples','cycles','start_UTC','end_exclusive_UTC']),'',
            mdtable([{'model':k,**v['metrics']} for k,v in r['models'].items()],['model','samples','cycles','accuracy','precision','recall','f1','brier_score','log_loss','accuracy_delta_vs_naive_pp']),'']
    lines+=['## 25 项研究结论','']
    qs=[]
    original_path=ROOT/'runtime/v2/original_v1_audit.json'
    if original_path.exists():
        original=json.loads(original_path.read_text())
        lines += [f"原始 V1 已从 SQLite 完整分钟重建：SHA256 与第一版保存值匹配 = {original['hash_matches']}；原 3,212 测试样本 LightGBM accuracy {pct(original['metrics']['accuracy'])}，Naive {pct(original['naive']['accuracy'])}。原模型未重新拟合。具体见 runtime/v2/original_v1_audit.json。",'']
    qs.append(('V1 是否存在数据泄漏？','已审计范围未发现 cycle 分区泄漏或当前特征读取未来柱；不是对所有未知数据问题的绝对证明。V2 另加验证集，修正 Naive 的概率展示。'))
    qs.append(('严格验证后的 Accuracy？',f"5 秒测试集主模型 {name}：{pct(m['metrics']['accuracy'])}；这里是重新划分校准/验证后的结果，不是声称发现泄漏后的修复幅度。"))
    qs.append(('Naive baseline？',f"5 秒 {pct(a['models']['naive']['metrics']['accuracy'])}；90 天 {pct(b['models']['naive']['metrics']['accuracy'])}。"))
    for key in ('distance_time','logistic','lightgbm'):
        qs.append((key+' 的准确率增量？',f"相对 Naive：5 秒 {a['models'][key]['metrics']['accuracy_delta_vs_naive_pp']:+.4f} 个百分点；90 天 {b['models'][key]['metrics']['accuracy_delta_vs_naive_pp']:+.4f} 个百分点。"))
    stable=min(('distance_time','logistic','lightgbm'),key=lambda k:b['fold_summary'][k]['brier_score']['std'])
    qs.append(('哪个模型最稳定？',f"按 90 天三个滚动窗口 Brier 标准差，{stable} 最小；只有三个窗口，不能据此证明普遍稳定。详见滚动统计。"))
    early=m['remaining'][-1];late=m['remaining'][0]
    qs.append(('75% 是否主要来自临近结算？',f"剩余 240–300 秒 {pct(early['accuracy'])}，0–30 秒 {pct(late['accuracy'])}，明显受时间影响。总体是所有采样点的平均，不能把临近结算胜率推广到开盘。"))
    best=max(m['remaining'],key=lambda r:r.get('accuracy') or 0)
    qs.append(('哪个 remaining-time 区间最强？',f"当前主模型：{best['range']} 秒，准确率 {pct(best['accuracy'])}，覆盖 {pct(best['coverage'])}。"))
    best=max(m['distance'],key=lambda r:r.get('accuracy') or 0)
    qs.append(('哪个 distance 区间最强？',f"当前主模型 |z_distance|：{best['range']}，准确率 {pct(best['accuracy'])}，样本 {best['samples']}。z 使用过去 30 个已完成分钟的波动率换算五分钟价格标准差。"))
    cal=a['calibration'][name]
    qs.append(('Calibration 是否有效？',f"验证集选择 {cal['chosen_calibration']}。测试 Brier："+'；'.join(f"{k}={v['brier_score']:.6f}" for k,v in cal['test'].items())+'。测试最优方法不反向更换部署模型。'))
    thresholds={r['threshold']:r for r in m['thresholds']}
    for t in (.7,.8):
        v=thresholds[t];qs.append((f'≥{t:.0%} confidence 实际命中？',f"snapshot 准确率 {pct(v['accuracy'])}；每周期首次越过阈值的准确率 {pct(v['event_accuracy'])}，{v['trades']} 个候选周期。它们不是实际成交笔数。"))
    qs.append(('对应 Coverage？',f"≥70% snapshot 覆盖 {pct(thresholds[.7]['coverage'])} / cycle 覆盖 {pct(thresholds[.7]['cycle_coverage'])}；≥80% 为 {pct(thresholds[.8]['coverage'])} / {pct(thresholds[.8]['cycle_coverage'])}。"))
    for title,cat,key in [('Bull','trend_24h','rising'),('Bear','trend_24h','falling'),('Sideways','trend_24h','sideways'),('High Vol','volatility_24h','high'),('Low Vol','volatility_24h','low')]:
        v=b['regimes']['groups'][cat][key][name]
        qs.append((title+' regime 表现？',f"90 天 {name}：accuracy {pct(v['accuracy'])}，Brier {v['brier_score']:.6f}，{v['cycles']} cycles，coverage {pct(v['coverage'])}。"))
    qs.append(('Worst walk-forward fold？',f"90 天 {name} 最差 accuracy {pct(b['fold_summary'][name]['accuracy']['worst'])}，最差 Brier {b['fold_summary'][name]['brier_score']['worst']:.6f}；两个指标的最差窗口不一定相同。"))
    qs.append(('Microstructure 真正增量？','只有 1 秒 K 线派生的收益、加速度、波动和 taker 流量；没有历史真实 L2 盘口。'+ '；'.join(f"{k}+micro 测试准确率变化 {100*(a['models'][k+'_micro']['metrics']['accuracy']-a['models'][k]['metrics']['accuracy']):+.4f} 个百分点" for k in ('logistic','lightgbm'))+'。两类模型结论不一致，不足以确认稳定增量，未据测试结果推广 micro 主模型。'))
    qs.append(('Latency 影响？','0/100/250/500/1000ms 均已运行；下表全部是 SIMULATED QUOTE。亚秒变化来自明确的合成报价过程，不是真实盘口时序，不能估计 predict.fun 的实际毫秒延迟成本。'))
    qs.append(('Spread / slippage / fee 影响？','已跑费用归零、固定滑点、波动相关滑点和 spread 加倍对照。参数会改变可入场集合，净收益之差同时包含费用及选择效应，不是控制其他因素的单笔因果成本。'))
    qs.append(('最大的三个弱点？','缺真实 predict.fun 报价/结算与费用回执；秒级数据仅 14 天且历史测试已被查看；跨窗口增量很小，订单簿微结构未历史验证。'))
    qs.append(('V3 三个值得研究的方向？','冻结本轮模型后前瞻收集真实 quote/结算；扩大秒级连续历史与块级不确定性；在同一留出集上比较盘口隐含概率和微结构增量。本次不开始 V3。'))
    assert len(qs)==25
    for i,(q,answer) in enumerate(qs,1):lines += [f'{i}. **{q}** {answer}','']
    lines+=['## 时间、距离、置信度','']
    for title,key,cols in [('Remaining Time','remaining',['range','samples','cycles','accuracy','precision','recall','f1','brier_score','mean_confidence','coverage']),
        ('Z Distance','distance',['range','samples','cycles','accuracy','actual_up_frequency','brier_score','coverage']),
        ('Confidence','confidence',['range','mean_confidence','accuracy','samples','cycles','coverage']),
        ('Threshold / Event','thresholds',['threshold','accuracy','coverage','trades','event_accuracy','cycle_coverage'])]:
        lines += ['### '+title,'',mdtable(m[key],cols),'']
    lines+=['## Walk-forward 汇总','']
    for mode,r in reports.items():
        lines+=['### '+mode,'',mdtable([{'model':k,'metric':metric,**v} for k,s in r['fold_summary'].items() for metric,v in s.items()],['model','metric','mean','median','std','worst','best']),'']
    scenarios=json.loads((ROOT/'runtime/v2/paper_scenarios.json').read_text())
    lines+=['## SIMULATED EXECUTION RESULT','',mdtable(scenarios,['scenario','latency_ms','total_trades','win_rate','coverage','average_quote','average_fill','fees','spread_cost','slippage_cost','gross_pnl','net_pnl','max_drawdown']),
        '', '注意：股份扣费时，手续费的 USDT 等值不必等于到期 gross_pnl − net_pnl，后者随该股份的最终支付比例变化。滑点为信号时 ask 至成交 VWAP 的有符号变化，负值表示价格改善；不是单纯固定滑点参数。模拟默认持有至结算；Bid 退出辅助函数已测试，未添加自动提前退出策略。真实报价无平台 outcome 时 PnL 为 null。分桶统一左闭右开，最后一个桶包含上界。',
        '', '## 运行与复现','', '在项目 PowerShell 中执行：','', '```powershell',
        '# 使用缓存重跑完整研究',r'.\.venv\Scripts\python.exe v2.py research',
        '# 无 Key 模拟执行',r'.\.venv\Scripts\python.exe v2.py paper',
        '# 导入真实录制报价（缺平台 settlement 时不计算已结算收益）',r'.\.venv\Scripts\python.exe v2.py paper --quotes quotes.csv',
        '# 重新生成本报告',r'.\.venv\Scripts\python.exe scripts\v2_review.py',
        '# 自动测试',r'.\.venv\Scripts\python.exe -m pytest -q',
        '# 后台启动/重启',r'powershell -ExecutionPolicy Bypass -File .\start-background.ps1','```','',
        '重新下载相同窗口：`research.py seconds --days 14 --step 5 --end 2026-09-22` 与 `research.py regimes --days 90 --end 2026-09-22`，随后运行 `v2.py research`。官方 ZIP 的 SHA256 清单位于 runtime/archives；已有缓存逐次校验。',
        '', 'CSV 必须包含 timestamp（UTC 毫秒）、bid、ask、depth（JSON bids/asks）、fee_bps；建议附 cycle_id、market_id、cycle_open、feed、received_at。没有深度/费率时拒绝伪造。JSON 也可直接读取 normalize_book 结构。',
        '', '## 代码与数据库','',
        '`btc5/v2research.py`：分区、模型、校准与诊断；`micro.py`：共享因果秒级特征；`inference.py`：single-flight 与状态复核；`market.py`：统一 provider；`paper_v2.py`：模拟场景；`execution.py` / `fees.py`：买卖侧深度与费用；`research_ui.py`：V2 研究页。',
        '', '实时审计在 runtime/research.sqlite 的 predictions / audit_v2 / venue_*；模拟执行单独写 runtime/v2/paper.sqlite；历史 observations.parquet 含当前价格、周期开盘、时间、特征、所有模型输出与最终 outcome。不同场景独立，每场景每 cycle 最多一笔；同场景重跑拒绝重复写入。',
        '', 'V2 模型与报告在 runtime/v2/seconds、runtime/v2/regimes。每个目录含 samples.parquet、heldout.parquet、observations.parquet、walkforward.parquet、model.joblib、report.json。原 V1 文件保留，可比较与回退。',
        '', '## Dashboard 与 Known Issues','',
        '电脑研究页 http://localhost:8501；手机同 Wi-Fi 打开 http://PC-LAN-IP:8502/。轻量手机页首个响应包含完整 HTML，无外部脚本；尚需用户设备确认无线互通。Streamlit 的“校准与回测”页可切换 14 天和 90 天，查看热图、校准曲线、覆盖率与模拟延迟表。',
        '', 'predict.fun 只读接口从环境变量 PREDICTFUN_API_KEY 读取（兼容旧 PREDICT_API_KEY）。.env.example 仅是模板，不自动加载；Key 不写 config、数据库、日志或 Python。主网 Key 尚未取得，实际只读调用仍待验证。',
        '', '本次会话没有已登录 Chrome 的控制工具，无法代为完成开发者控制台登录和生成 Key。官方入口：[Developer Console](https://developers.predict.fun/)，依据：[官方 API FAQ](https://dev.predict.fun/)。此限制不影响无 Key 的训练、回放、监控和模拟成交。',
        '', '滚动窗口时间范围、各模型 calibration 及完整分类指标保存在 JSON；日期块自助法只有少量测试日期，不能把每个 snapshot 当成独立样本。Regime 由过去 24h 价格变化与训练期波动率三分位定义；fast trend 为 |24h return|>2%，quiet 为 |return|≤0.5% 且低波动，不按收益挑日期。',
        '', '实时 micro 需要至少 61 个连续 1 秒柱，缺失时对应模型显示 unavailable；基础主模型仍可运行。超时 Python 线程不能强制终止，single-flight 会保持占用直到它退出，期间不积压请求；若底层库永久卡住，需要重启服务。',
        '', '当前部署主模型由验证集选择，尚未用更长的全新秒级留出确认；任何模型和模拟金额都不代表真实 predict.fun 概率已校准或真实资金收益。',
        '', '工程参考已阅读 [jev engine.ts](https://github.com/frankda/jev-poly-crypto-demo/blob/main/src/engine.ts) 与 [policy.ts](https://github.com/frankda/jev-poly-crypto-demo/blob/main/src/policy.ts)，独立实现并发、防旧数据与审计思路；未移植外部 AI 或真实 execution。[第一个参考项目](https://github.com/FrondEnt/PolymarketBTC15mAssistant) 仅用于了解实时 UI/数据流，未复用人工概率 score。',
        '', '验收测试与后台连通性的最后实跑记录见 V2_ACCEPTANCE.md。']
    (ROOT/'V2_REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('V2_REVIEW.md generated; 25 questions answered')


if __name__=='__main__':main()
