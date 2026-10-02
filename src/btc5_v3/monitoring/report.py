"""Exports of already-built, redacted monitoring views."""
from btc5_v3.encoding import canonical


def markdown(report):
    lines=['# M7 synthetic monitoring evidence','','RESEARCH MODE · READ ONLY · SYNTHETIC',
           '', 'No real profitability, execution-quality, optimal-risk or live-trading-safety claim.','']
    for case in report['cases']:
        view=case['view'];o=view['overview']
        lines += ['## '+case['case'],'', 'As-of: '+str(view['as_of']),
                  'Reconciliation: '+o['reconciliation'],'',
                  '```json',canonical(dict(capital=o['capital'],permissions=view['permissions'],
                     reservations=view['reservations'],positions=view['positions'],provenance=view['provenance'])),
                  '```','']
    return '\n'.join(lines)
