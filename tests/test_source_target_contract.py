"""Synthetic semantic checks against the unchanged V2 training dataset builder."""
import numpy as np
import pandas as pd
import pytest

from btc5.archives import seconds_dataset


@pytest.mark.parametrize('final,outcome,label', [(101., 'UP', 1), (99., 'DOWN', 0), (100., 'TIE', 0)])
def test_frozen_target_uses_cycle_open_and_final_close(final, outcome, label):
    n = 95 * 60
    prices = np.full(n, 100.)
    bars = pd.DataFrame(dict(timestamp=np.arange(n) * 1000, open=prices,
                             high=np.full(n, 110.), low=np.full(n, 90.),
                             close=prices.copy(), volume=np.ones(n), buy_volume=np.full(n, .5)))
    cycle = 90 * 60000
    # Interior price is higher than every final price: target is NOT final vs observation.
    bars.loc[bars.timestamp == cycle + 4000, 'close'] = 105.
    bars.loc[bars.timestamp == cycle + 299000, 'close'] = final
    frame = seconds_dataset(bars, 5)
    assert len(frame) == 59
    assert set(frame.outcome) == {outcome}
    assert set(frame.label) == {label}
    assert frame.timestamp.iloc[0] == cycle + 4999
    assert frame.timestamp.iloc[-1] == cycle + 294999
    assert frame.iloc[0].elapsed_seconds == 5.
    assert frame.iloc[0].remaining_seconds == 295.
    assert cycle + 300000 - frame.timestamp.iloc[0] == 295001
    assert frame.iloc[0].price == 105.
