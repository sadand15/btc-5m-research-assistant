"""Run after bootstrap/live sampling; checks actual rendered Streamlit app elements."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
app = AppTest.from_file(str(root / 'dashboard.py'), default_timeout=30).run()
if app.exception:
    raise AssertionError([e.message for e in app.exception])
assert len(app.metric) >= 8, 'Expected live price/cycle/probability metrics'
assert len(app.tabs) == 3, 'Expected feature, history, and research tabs'
assert len(app.dataframe) >= 6, 'Expected data and calibration tables'
print(f'Dashboard OK: {len(app.metric)} metrics, {len(app.tabs)} tabs, {len(app.dataframe)} tables')
