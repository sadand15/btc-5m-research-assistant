"""Launch the isolated public BTC display without installing research dependencies."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

if __name__ == '__main__':
    from btc5_v3.realtime_dashboard.server import main
    main(ROOT)
