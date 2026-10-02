"""Streamlit read-only V3 research dashboard; import has no database side effects."""
import argparse
from pathlib import Path
from datetime import datetime,timezone

from btc5_v3.encoding import canonical
from btc5_v3.monitoring.models import PAGES,ViewFilter
from btc5_v3.monitoring.service import MonitoringService


def display(value): return 'UNKNOWN / UNAVAILABLE' if value is None else str(value)


def utc(at):
    if at is None:return 'UNKNOWN'
    try:return datetime.fromtimestamp(at/1000,timezone.utc).isoformat()
    except (ValueError,OverflowError,OSError):return 'UNKNOWN'


def main(project_root=None,database=None):
    import streamlit as st
    if project_root is None:
        p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path.cwd())
        p.add_argument('--database',default='runtime/v3/m7-dashboard/demo.sqlite');args,_=p.parse_known_args()
        project_root=args.project_root;database=args.database
    database=database or 'runtime/v3/m7-dashboard/demo.sqlite'
    st.set_page_config(page_title='BTC 5M · Research Observability',page_icon='₿',layout='wide')
    st.title('BTC 5M · Research Observability')
    st.caption('RESEARCH MODE · READ ONLY · M7 monitoring/observability')
    service=MonitoringService(project_root,database);catalog=service.catalog()
    if not catalog:
        st.warning('EVIDENCE MODE: UNKNOWN · 没有可读取的 schema-7 synthetic archive。')
        st.info('先在独立 V3 工作树运行 M7 synthetic demo。Dashboard 不创建或修复研究数据库。')
        return
    names={x['id']:x['experiment_id'] for x in catalog}
    run_id=st.sidebar.selectbox('Research run',list(names),format_func=lambda x:names[x])
    latest=service.latest_at(run_id)
    if latest is None:
        st.warning('EVIDENCE MODE: UNKNOWN · 此 run 尚无可读取的事件。');return
    text=st.sidebar.text_input('As-of UTC epoch milliseconds',value=str(latest),key='asof-'+run_id)
    st.sidebar.caption('历史时点：只显示当时已归档的证据。')
    page=st.sidebar.radio('Page',PAGES)
    st.sidebar.button('Refresh · 只读刷新')
    fields={}
    with st.sidebar.expander('Read-only filters'):
        start=st.text_input('From UTC epoch ms (optional)')
        end=st.text_input('Until UTC epoch ms (optional)')
        for key,label in (('market_id','Market'),('candidate_id','Candidate ID'),('reason','Permission reason'),
                          ('reservation_id','Reservation ID'),('execution_id','Execution ID')):
            fields[key]=st.text_input(label)
        fields['permission']=st.selectbox('Permission',['','APPROVE','REDUCE','REJECT'])
        fields['position_status']=st.selectbox('Position status',['','PENDING','OPEN','PARTIAL','EXITED','SETTLED'])
        fields['health_state']=st.selectbox('Health state',['','HEALTHY','DEGRADED','STALE','PAUSED','UNKNOWN'])
        fields['risk_guard']=st.selectbox('Risk guard',['','PAUSED_DAILY_LOSS','PAUSED_DRAWDOWN','PAUSED_LOSS_STREAK','PAUSED_DATA','PAUSED_PROVIDER','MANUALLY_PAUSED'])
        fields['category']=st.selectbox('Timeline category',['','prediction','candidate','permission','reservation','execution','position','settlement','health','risk','ledger','reconciliation'])
        page_number=st.number_input('Detail page (zero based)',min_value=0,max_value=100000,value=0,step=1)
        page_size=st.selectbox('Rows per page',[25,50,100,200],index=1)
    try:
        filters=ViewFilter(int(text),start_at=int(start) if start else None,end_at=int(end) if end else None,
                           page=int(page_number),page_size=page_size,**fields)
    except ValueError:
        st.error('时间或过滤参数无效。使用非负 UTC 毫秒整数和合法时间范围。');return
    view=service.view(run_id,filters);data=view.data();overview=data['overview']
    st.info('EVIDENCE MODE: '+data['evidence_mode']+' · AS-OF REPLAY · '+utc(filters.as_of))
    st.caption('SELECTED RUN TOTALS · 表格过滤不改变组合总额。无 live health probe；MTM unavailable / not part of M6 contract。')
    if data['diagnostics']:st.warning('DIAGNOSTIC · 部分证据不完整或校验失败，请查看 Diagnostics；未修复任何记录。')
    st.subheader(page)
    capital=overview.get('capital') or {}
    def table(name,hidden=()):
        rows=data.get(name,[]);pagination=data.get('pagination',{}).get(name,{})
        st.caption(f"Recorded: {pagination.get('total','UNKNOWN')} · Matched: {pagination.get('matched','UNKNOWN')} · Page: {filters.page}")
        if not rows:st.info('NOT RECORDED / NO MATCHING ROWS');return
        flat=[{k:canonical(v) if isinstance(v,(dict,list)) else v for k,v in r.items() if k not in hidden} for r in rows]
        st.dataframe(flat,hide_index=True,width='stretch')
        with st.expander('Inspect exact visible evidence · 只读'):
            index=st.selectbox('Record index',range(len(rows)),key='record-'+name)
            st.json(rows[index])
    if page=='Overview':
        items=[('SYSTEM',overview.get('overall_health')),('AVAILABLE',capital.get('available_cash')),
               ('RESERVED',capital.get('reserved_cash')),('DEPLOYED COST',capital.get('open_exposure')),
               ('DAILY MAX LOSS',capital.get('daily_maximum_loss')),('DRAWDOWN',capital.get('drawdown')),
               ('LOSS STREAK',capital.get('consecutive_losses')),('RECONCILIATION',overview.get('reconciliation'))]
        for offset in (0,4):
            for col,(label,value) in zip(st.columns(4),items[offset:offset+4]):col.metric(label,display(value))
        st.write('Last recorded event (UTC): '+utc(overview.get('last_known_event_at')))
        st.write('Active pause / latch: '+display(capital.get('control_states')))
        st.json(overview)
    elif page=='System Health':table('health')
    elif page=='Risk':
        st.caption('Recorded M6 guards only. Daily reset, persistent latch and transient/manual pause are distinct.')
        table('risk');st.json(capital or {'state':'UNKNOWN'})
    elif page=='Permissions':table('permissions',('m3_evidence','source_prediction','source_snapshot','source_edge','state_before','execution_config','policy'))
    elif page=='Reservations':
        table('reservations');st.subheader('Immutable revision history');table('reservation_history')
    elif page=='Positions':
        st.caption('YES / NO 保留 gross exposure；pending permission 不是已成交仓位。')
        table('positions');st.json({k:capital.get(k) for k in ('open_by_market','pending_by_market','open_by_side','pending_by_side')})
    elif page=='Executions':table('executions',('evidence',))
    elif page=='Ledger':
        st.write('Reconciliation: '+overview.get('reconciliation','UNKNOWN'));table('ledger')
    elif page=='Timeline':table('timeline',('details',))
    elif page=='Diagnostics':
        if data['diagnostics']:st.dataframe(data['diagnostics'],hide_index=True,width='stretch')
        else:st.success('No archive diagnostic in the selected prefix; upstream completeness remains UNKNOWN.')
    elif page=='Provenance':st.json(data['provenance'])
    st.download_button('Export visible read-only view',view.payload_json,'m7-visible-view.json','application/json')
    st.caption('M7 provides monitoring and observability only. Synthetic/replay evidence is not real market execution evidence.')


if __name__=='__main__':main()
