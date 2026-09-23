"""Read-only V2 experiment views; no model selection from displayed test results."""
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from btc5.config import ROOT


def table(rows):
    return pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in rows])


def render_report():
    from btc5.forward import MANIFEST,report as forward_report
    from btc5.config import load_config
    if MANIFEST.exists():
        manifest=json.loads(MANIFEST.read_text())
        import sqlite3
        from types import SimpleNamespace
        with sqlite3.connect(load_config()['storage']['database']) as conn:
            conn.row_factory=sqlite3.Row
            status=forward_report(SimpleNamespace(conn=conn),manifest)
        with st.expander('7 天冻结前瞻观察',expanded=True):
            st.write(status['status']+' · '+status['start_utc']+' → '+status['end_utc'])
            st.write({'盘口记录':status['quotes_joined'],'主分析周期':status['primary_cycles'],
                '已结算周期':status['binary_settled_cycles'],'缺失主分析周期':status['missing_primary_completed_cycles']})
            st.caption('每周期剩余 115–120 秒窗口首次有效联合快照；模型为 Binance proxy，不宣称已对 Chainlink 校准。')
            st.dataframe(pd.DataFrame(status['paired_metrics']).T)
    mode=st.selectbox('研究数据集',['seconds','regimes'],format_func=lambda k:'14 天 / 5 秒快照' if k=='seconds' else '90 天 / 分钟快照')
    path=ROOT/'runtime/v2'/mode/'report.json'
    if not path.exists():st.info('运行 python v2.py research 生成 V2 研究报告。');return
    r=json.loads(path.read_text(encoding='utf-8'))
    st.caption('REPLAY DATA · 独立测试集 · Naive 为方向规则，没有已校准概率 · 所有增量用相同测试样本比较')
    st.write(r['leakage_audit']);st.dataframe(pd.DataFrame(r['split']).T)
    st.dataframe(table([{'model':name,**m['metrics']} for name,m in r['models'].items()]),hide_index=True)
    name=st.selectbox('分析模型',list(r['models']),index=list(r['models']).index(r['selected_model']))
    m=r['models'][name]
    for title,key,x,y in [('Remaining Time vs Accuracy','remaining','range','accuracy'),
            ('Confidence vs Actual Accuracy','confidence','range','accuracy'),
            ('Distance vs Accuracy','distance','range','accuracy'),
            ('Coverage vs Threshold','thresholds','threshold','coverage')]:
        st.subheader(title);f=table(m[key]);st.dataframe(f,hide_index=True)
        fig=go.Figure(go.Scatter(x=f[x],y=f[y],mode='lines+markers',name=title));fig.update_layout(height=240)
        st.plotly_chart(fig,width='stretch')
    h=table(m['distance_time']).pivot(index='distance',columns='remaining',values='accuracy')
    st.subheader('Distance × Remaining Time');st.dataframe(h)
    fig=go.Figure(go.Heatmap(z=h.to_numpy(),x=list(h.columns),y=list(h.index),zmin=.5,zmax=1))
    fig.update_layout(height=280);st.plotly_chart(fig,width='stretch')
    st.subheader('Calibration')
    if name!='naive':
        c=r['calibration'][name]
        st.write('验证集选择：'+c['chosen_calibration'])
        st.dataframe(table([{'method':k,**v} for k,v in c['test'].items()]),hide_index=True)
        fig=go.Figure();fig.add_scatter(x=[0,1],y=[0,1],name='理想校准',mode='lines')
        for method,metrics in c['test'].items():
            bins=pd.DataFrame(metrics['calibration']).dropna()
            fig.add_scatter(x=bins.predicted,y=bins.actual_up_rate,name=method,mode='lines+markers')
        st.plotly_chart(fig,width='stretch')
    else:st.info('Naive 的确定性 0/1 不是校准概率；不作置信度交易依据。')
    st.subheader('Walk Forward / Worst Fold')
    st.dataframe(table([{'fold':fold['fold'],**fold['models'][name]} for fold in r['folds']]),hide_index=True)
    st.json(r['fold_summary'][name])
    st.subheader('Regime Performance')
    for category in ('trend_24h','volatility_24h'):
        st.dataframe(table([{'regime':group,'cycles':v['cycles'],**v[name]} for group,v in r['regimes']['groups'][category].items()]),hide_index=True)
    scenarios=ROOT/'runtime/v2/paper_scenarios.json'
    st.subheader('Latency / Spread / Fee / Slippage')
    st.warning('SIMULATED EXECUTION RESULT · Mock 报价只验证成交逻辑；不是 predict.fun 真实收益。')
    if scenarios.exists():st.dataframe(table(json.loads(scenarios.read_text(encoding='utf-8'))),hide_index=True)
    st.download_button('导出完整 V2 研究 JSON',path.read_bytes(),f'v2-{mode}.json','application/json')
