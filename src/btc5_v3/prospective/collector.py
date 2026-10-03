"""Foreground collector with independent heartbeat while one bounded GET poll runs."""
from concurrent.futures import ThreadPoolExecutor
import signal
import time
from .store import Writer
from .sources import Binance, PredictFun, RuleChanged


def utc_ms():
    return time.time_ns() // 1000000


def collect(study, proof, *, clock=utc_ms, sleep=time.sleep, source=None, max_steps=None):
    spec = study.manifest['source_specs'][0]
    if source is None:
        source = Binance(clock) if spec['name']=='binance' else PredictFun(clock, spec['rule_profile'])
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    old = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        old[sig] = signal.signal(sig, stop)
    try:
        with Writer(study, proof, clock) as writer, ThreadPoolExecutor(max_workers=1) as pool:
            pending = None
            next_poll = next_heartbeat = 0
            steps = 0
            previous_clock=clock()
            while not stopped:
                now = clock()
                if now<previous_clock:
                    writer.stop('LOCAL_CLOCK_REVERSED')
                    break
                previous_clock=now
                if now >= writer.m['collection_end']:
                    writer.end()
                    break
                if now >= next_heartbeat:
                    writer.heartbeat()
                    next_heartbeat = now + 30000
                if pending is not None and pending.done():
                    event = None
                    try:
                        event = pending.result()
                    except RuleChanged:
                        writer.stop('RULE_CHANGED')
                        break
                    except PermissionError:
                        writer.source_failure('AUTH_MISSING_OR_FAILED')
                    except Exception:
                        # Never serialize exception text, response bodies or request headers.
                        writer.source_failure('CONNECTION_FAILURE')
                    if event is not None:
                        # Persistence/integrity failures must fail the collector, not masquerade as feed errors.
                        writer.observation(**event)
                    pending = None
                    next_poll = now + spec['poll_ms']
                if pending is None and writer.m['collection_start'] <= now and now >= next_poll:
                    pending = pool.submit(source.poll)
                steps += 1
                if max_steps is not None and steps >= max_steps:
                    stopped = True
                if not stopped:
                    sleep(0.2)
            if stopped:
                writer.stop()
    finally:
        for sig, previous in old.items():
            signal.signal(sig, previous)
