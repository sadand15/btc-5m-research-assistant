"""M10.2 reproducible synthetic integration and self-contained HTML report."""
import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from html import escape
import json
from pathlib import Path

from btc5_v3.target_semantics.demo import P, points, bound
from btc5_v3.target_semantics.lab import Contract, causal_inputs, digest
from .target_semantics import adapt_offline, seal_offline


def fixtures():
    records = []
    # Reuse M9.2 sources, authority fixture and fixed probability vector.
    for i, (feed, side) in enumerate([('trade',s) for s in ['UP']*6+['DOWN']*3+['TIE']]
                                    + [('mid','DOWN'),('reference','TIE')]):
        market = f'synthetic-m102-{i}'
        c = Contract(market, 0, 300000, feed)
        pp = points(market)
        if feed == 'trade':
            pp = (*pp[:2],replace(pp[2],trade={'UP':'101','DOWN':'99','TIE':'100'}[side]),pp[3])
        inputs = causal_inputs(pp, market, 150010)
        record = dict(id=f'valid-{i:02}', contract=asdict(c), points=[asdict(p) for p in pp],
                      prediction=dict(generated_at=150010, probabilities=dict(P),
                          input_hash=digest([asdict(p) for p in inputs])),
                      outcome=asdict(bound(c,side)), analysis_at=600000,
                      max_delay_ms=1000, end_offset_ms=-1, quality='VALID')
        records.append(record)
    for name in ('identity','authority','time','quality','future_input','missing_price','crossed_book','missing_time'):
        r = deepcopy(records[0]); r['id']='rejected-'+name
        if name=='identity': r['contract']['market_id']=''
        if name=='authority': r['outcome']=None
        if name=='time': r['outcome']['available_at']=100000
        if name=='quality': r['quality']='INVALID'
        if name=='future_input': r['prediction']['input_hash']='0'*64
        if name=='missing_price': r['points'][2]['trade']=None
        if name=='crossed_book': r['points'][0]['bid']='102'
        if name=='missing_time': del r['prediction']['generated_at']
        records.append(r)
    return records


def render(report):
    def e(value): return escape(str(value), quote=True)
    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+\
            '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in rows)+\
            '</tbody></table></div>'
    records = []
    for r in report['rows']:
        p = r.get('probabilities',{})
        records.append([r['id'],r.get('feed','—'),r['status'],*(p.get(s,'—') for s in ('UP','DOWN','TIE')),
            r.get('confidence',{}).get('value','—'),r.get('input_age_ms','—'),r.get('posthoc_label','—'),
            r.get('quality','UNKNOWN'),', '.join(r['reasons']) or '—'])
    metrics=[]; bins=[]
    for group, m in report['calibration'].items():
        metrics.append([group,m['n'],m['multiclass_brier'],m['log_loss'],m['classwise_ece']])
        bins += [[group,t['side'],t['bin'],t['n'],t['mean_probability'],t['frequency']] for t in m['reliability']]
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+\
        '<title>M10.2 离线研究报告</title><style>body{font:16px system-ui;background:#f4f6fa;color:#182638;max-width:1400px;margin:32px auto;padding:20px}h1{font-size:30px}.card{background:white;border:1px solid #d8dfeb;border-radius:10px;padding:20px;margin:16px 0}.badge{font-weight:bold;color:#075a52}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #ddd;padding:9px;text-align:left;white-space:nowrap}th{background:#e8eef7}.scroll{overflow:auto}code{overflow-wrap:anywhere}small{color:#42546c}</style>'+\
        '<h1>M10.2 · 离线端到端研究</h1><div class="card"><p class="badge">'+e(report['status'])+' · '+e(report['real_status'])+\
        '</p><p>全部为固定合成数据。真实目标仍为 TARGET_MISMATCH；不代表真实市场验证通过，不启用采集或交易。</p>'+\
        '<p>已评分 '+e(report.get('accepted',0))+' 条；明确拒绝 '+e(report.get('rejected',0))+' 条。</p>'+\
        '<p>输入 → 时间／标签校验 → 三分类 Adapter → 概率评分 → 本报告</p></div>'+\
        '<div class="card"><h2>概率、数据质量与拒绝原因</h2><p>置信度仅展示最大类别概率，不是统计置信区间。输入年龄为预测时已可用输入的最大 source age（毫秒）。三分类保留显式 TIE；DOWN 概率不包含平局。</p>'+\
        table(['记录','价格定义','状态','P(UP)','P(DOWN)','P(TIE)','最大类别概率','输入年龄 ms','事后标签','质量','拒绝原因'],records)+'</div>'+\
        '<div class="card"><h2>分组校准统计</h2><p>不同价格定义不混合评分。仅计入合格样本；小型人为构造样本不能证明实际校准能力。</p>'+\
        table(['价格／规则／边界','N','三分类 Brier','Log Loss','Classwise ECE'],metrics)+\
        '<h3>固定分箱明细</h3>'+table(['组','类别','箱编号','N','平均概率','实际频率'],bins)+'</div>'+\
        '<div class="card"><h2>复现与限制</h2><p>无模型拟合、阈值选择、账户、订单、执行或收益模拟。SYNTHETIC_READY 仅表示被接受的合成子集可评分；拒绝行保持可见。</p>'+\
        '<p>输入 root：<code>'+e(report.get('root_hash'))+'</code></p><p>报告 hash：<code>'+e(report.get('report_hash'))+'</code></p></div></html>'


def run(root):
    envelope=seal_offline(fixtures())
    report=adapt_offline(envelope,expected_root=envelope['root_hash'])
    parent=Path(root).resolve()
    for name in ('runtime','m102-offline-integration',report['report_hash']):
        parent=parent/name
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):
            raise ValueError('output alias rejected')
        parent.mkdir(exist_ok=True)
    for name, text in (('input.json',json.dumps(envelope,sort_keys=True,indent=2)),
                       ('report.json',json.dumps(report,sort_keys=True,indent=2)),('report.html',render(report))):
        path=parent/name; data=(text+'\n').encode('utf-8')
        if path.exists():
            if path.is_symlink() or path.read_bytes()!=data: raise ValueError('output conflict')
        else:
            with path.open('xb') as stream: stream.write(data)
    return report,parent/'report.html'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    report,path=run(args.project_root)
    print(json.dumps(dict(status=report['status'],real_status=report['real_status'],
                         accepted=report['accepted'],rejected=report['rejected'],html=str(path))))


if __name__=='__main__': main()
