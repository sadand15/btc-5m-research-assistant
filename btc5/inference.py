"""A timed-out worker stays in-flight until it really exits: zero queued jobs."""
import asyncio
from concurrent.futures import ThreadPoolExecutor


class SingleFlight:
    def __init__(self,timeout_seconds=2):
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='btc-inference')
        self.timeout=timeout_seconds;self.busy=False;self.skipped=0;self.closed=False

    def submit(self,work,complete,failed):
        if self.busy or self.closed:
            self.skipped+=1;return False
        loop=asyncio.get_running_loop();self.busy=True
        state={'expired':False}
        future=loop.run_in_executor(self.executor,work)
        def expire():
            state['expired']=True
            if not self.closed:failed('INFERENCE_TIMEOUT')
        timer=loop.call_later(self.timeout,expire)
        def done(f):
            timer.cancel();self.busy=False
            try:result=f.result()
            except Exception as exc:
                if not state['expired'] and not self.closed:failed(type(exc).__name__)
            else:
                if not state['expired'] and not self.closed:complete(result)
        future.add_done_callback(done)
        return True

    def close(self):
        self.closed=True;self.executor.shutdown(wait=False,cancel_futures=True)


def recheck(cycle,feature_at,now,timestamps,cfg):
    if not cycle<=now<cycle+300000:return 'CYCLE_CHANGED_DURING_INFERENCE'
    limits=cfg.get('freshness',{})
    if not 0<=now-feature_at<=limits.get('model_input_max_age_ms',10000):return 'STALE_MODEL_INPUT'
    for name,key in [('btc','btc_price_max_age_ms'),('orderbook','orderbook_max_age_ms'),('trade_flow','trade_flow_max_age_ms')]:
        required=name=='btc' or (name=='orderbook' and cfg['entry']['require_book']) or (name=='trade_flow' and limits.get('require_trade_flow',False))
        if required and (not timestamps.get(name) or not 0<=now-timestamps[name]<=limits.get(key,5000)):
            return 'STALE_'+name.upper()
    remaining=(cycle+300000-now)/1000
    if not cfg['entry']['min_remaining_seconds']<=remaining<=cfg['entry']['max_remaining_seconds']:
        return 'TIME_FILTER_AFTER_INFERENCE'
    return None
