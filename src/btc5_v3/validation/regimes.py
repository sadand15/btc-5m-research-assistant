"""Contemporaneous, fixed diagnostic bins; no outcome input."""
from decimal import Decimal as D
from datetime import datetime,timezone
from btc5_v3.analytics.statistics import tte_bucket,probability_bin
from btc5_v3.analytics.models import AnalyticsConfig


def classify(prediction,snapshot,at):
    if max(prediction.available_at,snapshot.available_at,snapshot.source_at)>at:raise ValueError('future regime input')
    spread=snapshot.yes_asks[0].price-snapshot.yes_bids[0].price
    depth=sum((x.quantity for x in snapshot.yes_asks),D(0))
    return dict(spread='LOW_SPREAD' if spread<D('.03') else 'HIGH_SPREAD',
                liquidity='LOW_LIQUIDITY' if depth<100 else 'HIGH_LIQUIDITY',
                tte=tte_bucket(snapshot.expiry-at),probability=str(probability_bin(prediction.p_yes,AnalyticsConfig().calibration_bin_edges)),
                market=snapshot.market_id,day=datetime.fromtimestamp(at/1000,timezone.utc).date().isoformat(),
                btc_shock='UNAVAILABLE',volatility='UNAVAILABLE',trend='UNAVAILABLE')
