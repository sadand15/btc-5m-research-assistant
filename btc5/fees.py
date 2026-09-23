"""Fee calculation shared by paper buys and sells; no account mutation."""
from decimal import Decimal
import math


def fee_amount(shares,price,bps,discount=1.0):
    if not (math.isfinite(shares+price+discount) and shares>=0 and 0<price<1 and 0<=bps<=10000 and 0<=discount<=1):
        raise ValueError('Invalid fee input')
    return float(Decimal(str(shares))*Decimal(int(bps))/10000*min(Decimal(str(price)),1-Decimal(str(price)))*Decimal(str(discount)))
