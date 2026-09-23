from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path = ROOT / 'config.yaml') -> dict:
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text(encoding='utf-8'))
    for key, value in cfg['storage'].items():
        target = (path.parent / value).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        cfg['storage'][key] = str(target)
    e, m, p = cfg['entry'], cfg['model'], cfg['paper_trading']
    if m['type'] not in ('lightgbm', 'logistic', 'distance_time'):
        raise ValueError('Unsupported model type')
    if cfg['data']['warmup_minutes'] < 100 or cfg['data']['prediction_interval_seconds'] <= 0:
        raise ValueError('Need at least 100 warmup minutes and a positive sampling interval')
    if cfg['symbol'] != 'BTCUSDT':
        raise ValueError('V1 database/model scope is BTCUSDT; use a separate project for other symbols')
    if not 0 < m['train_fraction'] < 1 or not 0 < m['calibration_fraction'] < 1 - m['train_fraction']:
        raise ValueError('Invalid chronological split fractions')
    if not 0 <= e['min_remaining_seconds'] < e['max_remaining_seconds'] < 300:
        raise ValueError('Invalid entry time range')
    if any(not 0.5 <= e[k] <= 1 for k in ('up_threshold', 'down_threshold')):
        raise ValueError('Thresholds must be in [0.5, 1]')
    if p['stake'] <= 0 or p['net_win_payout'] < 0 or p['fee_per_trade'] < 0 or p['initial_equity'] <= 0:
        raise ValueError('Invalid hypothetical payoff')
    v=cfg.get('predictfun')
    if cfg.get('freshness'):
        import math
        for key,value in cfg['freshness'].items():
            if key!='require_trade_flow' and (not math.isfinite(value) or value<=0):
                raise ValueError('Invalid freshness limit: '+key)
        if v:v['max_quote_age_ms']=cfg['freshness']['quote_max_age_ms']
    if cfg.get('inference',{}).get('timeout_seconds',2)<=0:
        raise ValueError('Inference timeout must be positive')
    if v:
        import math
        for key in ('budget_usdt','min_fill_usdt','min_expected_edge_usdt','latency_ms','max_quote_age_ms',
                    'max_slippage_bps','fee_discount_multiplier','poll_seconds'):
            if not math.isfinite(float(v[key])) or float(v[key])<0:
                raise ValueError('Invalid predict.fun simulation parameter: '+key)
        if v['budget_usdt']<=0 or v['min_fill_usdt']>v['budget_usdt'] or v['poll_seconds']<1:
            raise ValueError('Invalid quote polling interval or simulated budget')
        if v['fee_discount_multiplier']>1 or v['fee_deduction'] not in ('shares','collateral'):
            raise ValueError('Invalid simulated fee policy')
    return cfg
