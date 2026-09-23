import io
import zipfile
import numpy as np
import pandas as pd
import pytest
from btc5.archives import read_archive,seconds_dataset
from btc5.research import META


def seconds(minutes=100):
    n=minutes*60
    t=np.arange(n)*1000
    price=60000+np.sin(np.arange(n)/70)*25+np.arange(n)/100
    return pd.DataFrame(dict(timestamp=t,open=price,high=price+1,low=price-1,
                             close=price+.2,volume=np.ones(n),buy_volume=np.ones(n)*.5))


def test_second_replay_causality_and_partial_volume():
    s=seconds()
    first=seconds_dataset(s,5)
    observation=90*60000+29999
    row=first[first.timestamp==observation].iloc[0]
    assert row.elapsed_seconds==30
    assert row.remaining_seconds==270
    assert row.volume_ratio==pytest.approx(.5)  # Only 30 seconds of volume.
    changed=s.copy()
    changed.loc[changed.timestamp>observation,['open','high','low','close']]+=1000
    later=seconds_dataset(changed,5)
    cols=sorted(set(first.columns)-{'label','outcome'})
    np.testing.assert_allclose(first.loc[first.timestamp<=observation,cols],later.loc[later.timestamp<=observation,cols])
    assert 30 in set(first.remaining_seconds)
    assert 0 not in set(first.remaining_seconds)


def test_one_second_mode_and_missing_second():
    s=seconds(95)
    frame=seconds_dataset(s,1)
    assert set(frame.elapsed_seconds)==set(range(1,300))
    damaged=s[s.timestamp!=92*60000+17000]
    with pytest.raises(ValueError,match='No valid'):
        seconds_dataset(damaged,5)  # Incomplete label cycle is discarded in entirety.
    with pytest.raises(ValueError,match='Duplicate'):
        seconds_dataset(pd.concat([s,s.tail(1)]),5)


@pytest.mark.parametrize('scale',[1,1000])
def test_archive_microseconds_normalized(scale):
    t=1767225600000
    csv=f'{t*scale},100,101,99,100,10,{(t+1000)*scale-1},1000,10,5,500,0\n'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('bars.csv',csv)
    result=read_archive(out.getvalue(),'1s')
    assert result.iloc[0].timestamp==t
    assert result.iloc[0].close_time==t+999
