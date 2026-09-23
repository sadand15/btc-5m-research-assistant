"""CLI launcher. `python app.py` bootstraps research and starts live paper + UI."""
import argparse
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
from btc5.config import load_config, ROOT
from btc5.data import Historical, MINUTE, CYCLE
from btc5.database import Database
from btc5.research import dataset, train, Predictor, classification, backtest
from btc5.live import LiveEngine


def download(cfg, db, days):
    source = Historical(cfg)
    end = source.server_time() // MINUTE * MINUTE
    rows = source.download(end - int(days * 86400_000), end)
    if not rows:
        raise RuntimeError('No historical data received')
    db.import_minutes(rows)
    expected = int(days * 1440)
    print(json.dumps({'downloaded_minutes': len(rows), 'requested_minutes': expected,
                      'missing_minutes': max(0, expected - len(rows)), 'last_close_utc_ms': rows[-1].timestamp + MINUTE}))


async def run_live(cfg, db, seconds):
    engine = LiveEngine(cfg, db, Predictor(cfg['storage']['model']))
    try:
        if seconds:
            await asyncio.wait_for(engine.run(), timeout=seconds)
        else:
            await engine.run()
    except asyncio.TimeoutError:
        logging.info('Bounded live run completed')
    finally:
        db.state(connection='STOPPED')


def main():
    parser = argparse.ArgumentParser(description='BTC 5M public-data research / PAPER ONLY')
    parser.add_argument('command', nargs='?', choices=['run', 'download', 'train', 'backtest'], default='run')
    parser.add_argument('--config', default=str(ROOT / 'config.yaml'))
    parser.add_argument('--days', type=float)
    parser.add_argument('--seconds', type=float, help='Stop live engine after a bounded integration test')
    parser.add_argument('--no-dashboard', action='store_true')
    args = parser.parse_args()
    cfg = load_config(args.config)
    logpath = Path(cfg['storage']['database']).with_suffix('.log')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), RotatingFileHandler(logpath, maxBytes=5_000_000, backupCount=3, encoding='utf-8')])
    db = Database(cfg['storage']['database'])
    child = None
    try:
        if args.command == 'download':
            download(cfg, db, args.days or cfg['data']['bootstrap_days'])
        elif args.command == 'train':
            result = train(dataset(db.read_minutes()), cfg)
            print(json.dumps({'model_version': result['model_version'], 'split': result['split'],
                              'report': cfg['storage']['report']}, indent=2))
        elif args.command == 'backtest':
            predictor = Predictor(cfg['storage']['model'])
            cutoff = predictor.artifact['fit_end']
            frame = dataset(db.read_minutes(max(0, cutoff - 120 * MINUTE)))
            frame = frame[frame.cycle_id >= cutoff].reset_index(drop=True)
            if frame.empty:
                raise ValueError('No out-of-sample cycles after the model calibration cutoff')
            probs = predictor.artifact['model'].predict_proba(frame[predictor.artifact['columns']])[:, 1]
            result = {'model_version': predictor.version, 'fit_end': cutoff,
                      'metrics': classification(frame.label, probs), 'backtest': backtest(frame, probs, cfg)}
            path = Path(cfg['storage']['report']).with_name('backtest.json')
            path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
            print(json.dumps({**result['metrics'], 'trades': result['backtest']['total_trades'], 'report': str(path)}, indent=2))
        else:
            if not Path(cfg['storage']['model']).exists():
                logging.info('[MODEL] first start: download, chronological train/calibrate/test')
                download(cfg, db, args.days or cfg['data']['bootstrap_days'])
                train(dataset(db.read_minutes()), cfg)
            if not args.no_dashboard:
                child = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'dashboard.py'),
                    '--server.address=127.0.0.1', f'--server.port={cfg["dashboard"]["port"]}',
                    '--server.headless=true', '--browser.gatherUsageStats=false', '--', '--config', str(Path(args.config).resolve())],
                    cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                print(f'Dashboard: http://localhost:{cfg["dashboard"]["port"]}')
            asyncio.run(run_live(cfg, db, args.seconds))
    except KeyboardInterrupt:
        logging.info('Stopped by user')
        db.state(connection='STOPPED')
    finally:
        if child:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        db.close()


if __name__ == '__main__':
    main()
