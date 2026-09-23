"""Read-only, server-rendered mobile dashboard. No JavaScript, CDN or WebSocket."""
import argparse
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import time
from btc5.config import load_config,ROOT


def snapshot(cfg):
    path=Path(cfg['storage']['database'])
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True,timeout=10) as conn:
        conn.row_factory=sqlite3.Row
        state={k:json.loads(v) for k,v in conn.execute('SELECT key,value FROM state')}
        points=[dict(r) for r in conn.execute('SELECT timestamp,price FROM predictions ORDER BY timestamp DESC LIMIT 180')][::-1]
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        orders=[dict(r) for r in conn.execute('SELECT cycle_id,status,fill,settlement FROM venue_orders ORDER BY id DESC LIMIT 10')] if 'venue_orders' in tables else []
    report={}
    for name in ('seconds','regimes'):
        report_path=ROOT/'runtime/v2'/name/'report.json'
        if not report_path.exists():report_path=ROOT/'runtime'/name/'report.json'
        if report_path.exists():
            r=json.loads(report_path.read_text(encoding='utf-8'))
            report[name]={'source':r.get('data_source','V2 four-way chronological replay'),'window':r.get('archive_window',r.get('dataset')),
                          'models':{k:{key:v.get('metrics',v)[key] for key in ('accuracy','brier_score')} for k,v in r['models'].items()}}
    from btc5.forward import MANIFEST
    forward=json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    # Expose only schedule/version, not local paths or configuration snapshots.
    forward={k:forward[k] for k in ('run_id','start','end','model_version','planned_cycles')} if forward else None
    return {'state':state,'points':points,'orders':orders,'research':report,'forward':forward,'server_time':int(time.time()*1000)}


def render(data):
    s=data['state']; f=s.get('features',{})
    now=data['server_time']+s.get('clock_offset_ms',0)
    stale=now-s.get('event_time',0)>10000 or s.get('connection')!='CONNECTED'
    remaining=max(0,min(300,(s.get('cycle_id',0)+300000-now)/1000))
    def metric(label,value):
        return '<div class="card"><small>'+escape(label)+'</small><strong>'+escape(str(value))+'</strong></div>'
    p=s.get('up_probability')
    cards=''.join([metric('BTC / USDT',f'{s.get("price",0):,.2f}'),metric('本轮开盘',f'{s.get("cycle_open",0):,.2f}'),
                   metric('UP 概率',f'{p:.1%}' if p is not None else '等待模型'),
                   metric('DOWN / non-UP',f'{1-p:.1%}' if p is not None else '等待模型'),
                   metric('剩余时间',f'{int(remaining)//60:02}:{int(remaining)%60:02}'),
                   metric('开盘距离 Z',f'{f.get("distance_standardized",0):.2f}')])
    points=data['points']
    chart=''
    if len(points)>1:
        prices=[r['price'] for r in points]+[s.get('cycle_open',points[-1]['price'])]
        low,high=min(prices),max(prices)
        scale=max(high-low,.01)
        coords=' '.join(f'{i*880/(len(points)-1)+10:.1f},{210-(r["price"]-low)/scale*180:.1f}' for i,r in enumerate(points))
        baseline=210-(prices[-1]-low)/scale*180
        chart=f'<svg viewBox="0 0 900 240" role="img" aria-label="BTC实时价格与本轮开盘线"><line x1="0" x2="900" y1="{baseline}" y2="{baseline}" stroke="#eebf55" stroke-dasharray="8 6"/><polyline points="{coords}" fill="none" stroke="#5ed8ca" stroke-width="3"/></svg><small>青色：BTC 价格 · 黄色虚线：本轮开盘</small>'
    research=''
    for name,r in data['research'].items():
        rows=''.join(f'<tr><td>{escape(k)}</td><td>{m["accuracy"]:.2%}</td><td>{m["brier_score"]:.4f}</td></tr>' for k,m in r['models'].items())
        research+=f'<h3>{"秒级回放" if name=="seconds" else "90天跨阶段验证"}</h3><table><tr><th>模型</th><th>准确率</th><th>Brier</th></tr>{rows}</table>'
    q=s.get('venue_quote',{})
    forward=data.get('forward');forward_html=''
    if forward:
        period=' → '.join(datetime.fromtimestamp(forward[k]/1000,timezone.utc).isoformat(timespec='minutes') for k in ('start','end'))
        forward_html='<section><h2>7 天冻结前瞻观察</h2><p>'+escape(period)+'</p><p>模型与参数已固定；保留价格源保护。每周期取剩余 115–120 秒内首次有效联合快照，结算后再评价。</p><small>'+escape(forward['model_version'])+'</small></section>'
    book=' · '.join(f'{k}: {v}' for k,v in q.items() if k!='received_at') or '暂无真实报价'
    orders=''.join('<tr><td>'+escape(str(o['cycle_id']))+'</td><td>'+escape(o['status'])+'</td><td>'+escape(str(json.loads(o['settlement']).get('pnl_usdt') if o['settlement'] else '待结算'))+'</td></tr>' for o in data['orders'])
    body=f'''<header><span class="tag">PAPER ONLY</span><h1>BTC 5M 研究助手</h1><p>轻量手机页 · 每 5 秒刷新 · 无需加载外部脚本</p></header>
    <p class="status">{'行情已过期 / WAIT' if stale else '实时行情已连接'} · {escape(s.get('connection','STARTING'))}</p>
    <div class="grid">{cards}</div><section>{chart}</section>{forward_html}
    <section><h2>模拟成交 · predict.fun</h2><p>{escape(s.get('venue_status','等待接口初始化'))}</p><p>{escape(s.get('venue_decision','WAIT'))}</p><small>{escape(book)}</small>
    <p>模型预测 Binance 周期方向。其他预言机的结果不能直接视为已校准；只按平台明确结果结算。</p>
    <table><tr><th>周期</th><th>状态</th><th>USDT 盈亏</th></tr>{orders}</table></section>
    <section><h2>研究结果</h2>{research or '<p>研究任务运行中。</p>'}<p>准确率不等于可成交收益；研究回放与真实报价模拟分别统计。</p></section>
    <footer>更新 {datetime.fromtimestamp(data['server_time']/1000,timezone.utc).isoformat(timespec='seconds')} · <a href="/health">连通性检查</a></footer>'''
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="5"><title>BTC 5M 手机研究页</title><style>
    *{box-sizing:border-box}body{margin:0 auto;max-width:980px;padding:22px 16px;background:#101722;color:#ebf2fa;font:16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}h1{font-size:28px;margin:12px 0}h2{font-size:21px}h3{font-size:17px}p,small,footer{color:#aab8cb;line-height:1.6}.tag{color:#5ed8ca;font-size:12px;letter-spacing:2px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.card,section{background:#1a2535;border:1px solid #304158;border-radius:14px;padding:18px;margin:0 0 12px}.card strong{display:block;font-size:26px;margin-top:12px;overflow-wrap:anywhere}.status{color:#f1c363}svg{width:100%;display:block}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px 4px;border-bottom:1px solid #304158;text-align:left}a{color:#5ed8ca}footer{font-size:12px}@media(min-width:720px){.grid{grid-template-columns:repeat(3,1fr)}}
    </style></head><body>'''+body+'</body></html>'


def serve(cfg):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path=='/health':
                    content=b'ok'; kind='text/plain'
                elif self.path in ('/','/api/state'):
                    data=snapshot(cfg)
                    content=(json.dumps(data,allow_nan=False) if self.path=='/api/state' else render(data)).encode('utf-8')
                    kind='application/json' if self.path=='/api/state' else 'text/html'
                else:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header('Content-Type',kind+'; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Length',str(len(content)))
                self.end_headers(); self.wfile.write(content)
            except (BrokenPipeError,ConnectionResetError):
                pass
            except Exception:
                self.send_error(503,'Data not ready; retry shortly')
    server=ThreadingHTTPServer((cfg['dashboard'].get('host','127.0.0.1'),cfg['dashboard'].get('mobile_port',8502)),Handler)
    print('Mobile dashboard listening',server.server_address,flush=True)
    server.serve_forever()


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--config',default=str(ROOT/'config.yaml'))
    serve(load_config(p.parse_args().config))
