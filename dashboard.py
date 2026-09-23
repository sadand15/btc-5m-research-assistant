import argparse
import json
import sqlite3
import time
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from btc5.config import load_config

parser = argparse.ArgumentParser()
parser.add_argument('--config', default=str(Path(__file__).parent / 'config.yaml'))
args, _ = parser.parse_known_args()
cfg = load_config(args.config)
st.set_page_config(page_title='BTC 5M Research', page_icon='₿', layout='wide')
st.title('BTC 5M · 实时交易研究助手')
st.caption('PAPER TRADING ONLY · UTC 对齐周期 · 实际模型输出 · 本机 SQLite')
st.caption('手机白屏可改用相同电脑 IP 的 8502 端口：轻量 HTML 页，不依赖 WebSocket。')


@st.fragment(run_every='2s')
def render():
    path = Path(cfg['storage']['database'])
    if not path.exists():
        st.info('请先运行 python app.py，下载历史数据并训练模型。')
        return
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=10) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'state' not in tables:
            st.info('数据库初始化中。')
            return
        state = {k: json.loads(v) for k, v in conn.execute('SELECT key,value FROM state')}
        predictions = pd.read_sql_query('SELECT * FROM predictions ORDER BY timestamp DESC LIMIT 120', conn)
        trades = pd.read_sql_query('SELECT * FROM trades ORDER BY timestamp DESC LIMIT 100', conn)
        candles = pd.read_sql_query("SELECT timestamp,close FROM candles WHERE timeframe='1m' ORDER BY timestamp DESC LIMIT 90", conn)
    now = time.time() * 1000 + state.get('clock_offset_ms', 0)
    age = (now - state.get('event_time', 0)) / 1000
    stale = age > cfg['data']['stale_seconds'] or state.get('connection') != 'CONNECTED'
    st.caption(f'连接：{state.get("connection", "STARTING")} | 模型：{state.get("model_version", "训练中")} | 行情延迟：{age:.1f}s' if state.get('event_time') else '等待首个实时快照 / 首次训练中')
    if stale:
        st.warning('WAIT · 行情尚未就绪或已过期，下方已有数据仅作历史快照展示。')
    if 'price' not in state:
        st.info('训练和行情日志见终端；首次启动需要下载、构建特征及校准。')
        return
    f, price, opening = state['features'], state['price'], state['cycle_open']
    quote_live=state.get('venue_status')=='CONNECTED' and now-state.get('venue_quote',{}).get('received_at',0)<=cfg['predictfun']['max_quote_age_ms']
    st.warning('报价模式：'+('LIVE DATA（只读盘口 / 模拟成交）' if quote_live else 'DISABLED（无可用实时预测市场报价）'))
    st.caption('BTC 数据：'+('STALE DATA' if stale else 'LIVE DATA')+' · 离线研究：REPLAY DATA · Mock 成交：SIMULATED DATA')
    st.info('predict.fun: '+state.get('venue_status','等待接口初始化')+' · '+state.get('venue_decision','WAIT'))
    elapsed = max(0, min(300, (now - state['cycle_id']) / 1000))
    remaining = 300 - elapsed
    columns = st.columns(6)
    for col, label, value in zip(columns, ['BTC PRICE', 'Cycle Open', 'Distance', 'Elapsed', 'Remaining', 'Z / 5m'],
                                [f'${price:,.2f}', f'${opening:,.2f}', f'{price-opening:+.2f}',
                                 f'{int(elapsed)//60:02}:{int(elapsed)%60:02}',
                                 f'{int(remaining)//60:02}:{int(remaining)%60:02}', f'{f["distance_standardized"]:.2f}']):
        col.metric(label, value)
    left, right = st.columns([2, 1])
    with left:
        fig = go.Figure()
        if not candles.empty:
            ordered = candles.sort_values('timestamp')
            fig.add_scatter(x=pd.to_datetime(ordered.timestamp, unit='ms', utc=True), y=ordered.close, name='1m close', mode='lines')
        if not predictions.empty:
            recent = predictions[predictions.cycle_id == state['cycle_id']].sort_values('timestamp')
            fig.add_scatter(x=pd.to_datetime(recent.timestamp, unit='ms', utc=True), y=recent.price, name='Live snapshots')
        fig.add_hline(y=opening, line_dash='dash', annotation_text='Current cycle open')
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0), yaxis_title='BTC / USDT', xaxis_title='UTC')
        st.plotly_chart(fig, width='stretch')
    with right:
        p = state['up_probability']
        st.metric('UP probability', f'{p:.1%}')
        st.metric('DOWN / non-UP probability', f'{1-p:.1%}')
        st.caption('DOWN 为 UP 的补事件（包含持平）；模拟交易持平作废。')
        st.subheader('WAIT' if stale else state.get('decision', 'WAIT'))
        st.write('STALE_DATA' if stale else state.get('reason', ''))
        st.caption('当前位于模型训练采样点附近' if state.get('supported') else '当前秒位不在模型时间支持范围；概率仅供观察')
    tabs = st.tabs(['趋势与特征', '预测与模拟交易', '校准与回测'])
    with tabs[0]:
        st.dataframe(pd.DataFrame([{'周期': t, 'trend return': f[f'trend_{t}'],
                                  'momentum': f.get(f'momentum_{t}')} for t in ['1m', '5m', '15m']]), hide_index=True)
        a, b = st.columns(2)
        a.dataframe(pd.DataFrame({'feature': list(f), 'value': list(f.values())}), hide_index=True, height=400)
        if state.get('orderbook'):
            b.dataframe(pd.DataFrame({'book': list(state['orderbook']), 'value': list(state['orderbook'].values())}), hide_index=True)
        else:
            b.info('订单簿缺失或过期。')
    with tabs[1]:
        if state.get('model_outputs'):
            st.subheader('模型对照')
            st.dataframe(pd.DataFrame([{'model':k,'UP probability':v.get('probability'),
                'DOWN probability':1-v['probability'] if v.get('probability') is not None else None,
                'direction / reason':v.get('direction',v.get('reason',''))} for k,v in state['model_outputs'].items()]),hide_index=True)
        st.subheader('Recent Predictions')
        st.dataframe(predictions.drop(columns=['features'], errors='ignore'), hide_index=True)
        st.subheader('Recent Simulated Trades')
        st.dataframe(trades.drop(columns=['features'], errors='ignore'), hide_index=True)
        st.download_button('导出可见交易 CSV', trades.to_csv(index=False).encode('utf-8-sig'), 'recent_trades.csv', 'text/csv')
    with tabs[2]:
        from btc5.research_ui import render_report
        render_report()
        report_path = Path(cfg['storage']['report'])
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if report.get('schema')=='v2-review-1':return
            st.caption('时间顺序独立测试集；'+report.get('data_source','')+'。行情回放不等于真实合约成交，高胜率须与 distance_time 基线比较。')
            st.dataframe(pd.DataFrame([{'model': name, **{k: m[k] for k in ['samples', 'accuracy', 'precision', 'recall', 'f1', 'brier_score', 'uncalibrated_brier']}}
                                      for name, m in report['models'].items()]), hide_index=True)
            selected = st.selectbox('查看模型', list(report['models']), index=list(report['models']).index(cfg['model']['type']))
            result = report['models'][selected]
            bins = pd.DataFrame(result['calibration']).dropna()
            fig = go.Figure()
            fig.add_scatter(x=[0, 1], y=[0, 1], mode='lines', name='Perfect calibration', line_dash='dash')
            fig.add_scatter(x=bins.predicted, y=bins.actual_up_rate, mode='lines+markers', name=selected,
                            text=bins['count'], hovertemplate='pred=%{x:.3f}<br>actual=%{y:.3f}<br>n=%{text}')
            fig.update_layout(xaxis_title='Predicted P(UP)', yaxis_title='Actual UP rate', height=350)
            st.plotly_chart(fig, width='stretch')
            st.dataframe(bins, hide_index=True)
            st.write('按剩余时间', pd.DataFrame(result['by_remaining']))
            bt = result['backtest']
            st.json({k: v for k, v in bt.items() if k not in ['trades', 'by_confidence', 'by_remaining']})
            st.write('入场置信度分组', pd.DataFrame(bt['by_confidence']))
            st.write('特征置换重要性（探索性）', pd.DataFrame(report.get('feature_importance', [])).head(15))
        else:
            st.info('尚无回测报告。')


render()
