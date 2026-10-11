"""Start isolated Binance direction research; original V2 collector is not used."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]

if __name__=='__main__':
    if '--binance-model' not in sys.argv:
        sys.argv.extend(['--binance-model',str(ROOT/'runtime/binance-model.joblib')])
    if '--port' not in sys.argv:
        sys.argv.extend(['--port','8767'])
    from btc5_v3.realtime_dashboard.server import main
    main(ROOT)
