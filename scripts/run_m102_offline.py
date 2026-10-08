"""One-command local demo, with no installation or external service required."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from btc5_v3.research_adapter.offline_demo import run

if __name__=='__main__':
    report,path=run(ROOT)
    print(report['status']+' / '+report['real_status'])
    print(path)
