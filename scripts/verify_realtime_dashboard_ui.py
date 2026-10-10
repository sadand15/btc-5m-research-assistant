"""Offline browser acceptance: only local server + explicitly synthetic responses."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from btc5_v3.realtime_dashboard.feed import SyntheticFeed
from btc5_v3.realtime_dashboard.server import make_server
from btc5_v3.realtime_dashboard.service import DashboardService


def run(channel=None):
    from playwright.sync_api import sync_playwright, expect
    output = ROOT/'runtime/dashboard-ui-tests'
    output.mkdir(parents=True, exist_ok=True)
    service = DashboardService(SyntheticFeed())
    service.poll_history()
    service.poll_reference()
    server = make_server(service, ROOT, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    results, errors = [], []
    mode, requests, cached = ['healthy'], [], []

    def response(route):
        requests.append(time.monotonic())
        if mode[0] == 'offline':
            return route.abort('internetdisconnected')
        if mode[0] == 'http503':
            return route.fulfill(status=503, body='Unavailable')
        service.poll_quote()
        state = service.snapshot()
        if mode[0] == 'cached':
            if not cached:
                cached.append(state)
            state = cached[0]
        if mode[0] == 'stale':
            state['quote']['source_age_ms'] = 20000
            state['quote']['source_at'] -= 20000
            state['health']['status'] = 'DELAYED'
            state['health']['reason'] = 'STALE_SOURCE'
            state['live_price'] = None
        if mode[0] == 'recovering':
            state['health']['status'] = 'RECOVERING'
            state['health']['reason'] = 'FEED_RECOVERED'
        if mode[0] == 'upstream_failure':
            state['health']['status'] = 'DISCONNECTED'
            state['health']['reason'] = 'CONNECTION_FAILURE'
            state['quote']['source_age_ms'] = 60000
            state['quote']['source_at'] -= 60000
            state['live_price'] = None
        if mode[0] == 'malformed':
            state['health']['status'] = 'UNKNOWN'
        if mode[0] == 'missing':
            del state['history']['points'][20:30]
            state['history'].update(status='PARTIAL', observed=1430, missing=10, coverage=1430/1440)
        if mode[0] == 'rollover':
            # Move to just before a boundary without using a future prediction.
            delta = state['cycle']['end_at']-100-state['server_at']
            state['server_at'] += delta
            for key in ('source_at', 'received_at'):
                state['quote'][key] += delta
        return route.fulfill(json=state)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**({'channel': channel} if channel else {}))
            context = browser.new_context(viewport={'width': 1440, 'height': 1100})
            context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(url+'/') else r.abort())
            context.route('**/api/state', response)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url)
            expect(page.locator('#live-price')).not_to_have_text('—')
            expect(page.locator('#demo-banner')).to_be_visible()
            expect(page.locator('#decision-signal')).to_have_text('WAIT')
            expect(page.locator('#decision-state')).to_have_text('未评估')
            expect(page.locator('#decision-validity')).to_have_text('有效期：等待真实市场绑定')
            expect(page.locator('#decision-reasons')).to_contain_text('真实市场身份')
            results.append('explicit_current_decision_wait_and_reasons')
            before = page.locator('#source-time').inner_text()
            expect(page.locator('#source-time')).not_to_have_text(before, timeout=6000)
            assert len(requests) >= 2 and min(b-a for a, b in zip(requests, requests[1:])) >= 1.8
            results.append('automatic_refresh_rate_limit')
            page.get_by_role('button', name='24 小时').click()
            expect(page.locator('#chart-range')).to_contain_text('1440')
            page.get_by_role('button', name='1 小时').click()
            expect(page.locator('#chart-range')).to_contain_text('60 个')
            assert page.locator('#chart-svg path').get_attribute('d')
            results.append('one_hour_and_24_hour_history')
            page.screenshot(path=str(output/'synthetic-healthy.png'), full_page=True)
            for name in ('m92', 'm102'):
                with page.expect_popup() as popup:
                    page.locator('#'+name+'-link').click()
                popup.value.wait_for_load_state()
                expect(popup.value.locator('body')).to_contain_text('REAL_DATA_NOT_READY')
                popup.value.close()
            results.append('offline_reports')
            mode[0] = 'offline'
            expect(page.locator('#health-badge')).to_have_text('连接中断', timeout=6000)
            expect(page.locator('#live-price')).to_have_text('—')
            expect(page.locator('#last-known')).to_contain_text('最近有效报价')
            page.screenshot(path=str(output/'synthetic-disconnected.png'), full_page=True)
            results.append('network_failure_hides_live')
            mode[0] = 'recovering'
            expect(page.locator('#health-badge')).to_have_text('连接恢复中', timeout=12000)
            expect(page.locator('#live-price')).not_to_have_text('—')
            results.append('recovery')
            mode[0] = 'stale'
            expect(page.locator('#health-badge')).to_have_text('数据延迟', timeout=6000)
            expect(page.locator('#live-price')).to_have_text('—')
            results.append('stale_quote')
            mode[0] = 'upstream_failure'
            expect(page.locator('#health-badge')).to_have_text('连接中断', timeout=6000)
            expect(page.locator('#live-price')).to_have_text('—')
            results.append('upstream_disconnection_takes_priority_over_age')
            mode[0] = 'http503'
            with page.expect_response(lambda r: r.url.endswith('/api/state') and r.status == 503):
                pass
            expect(page.locator('#health-badge')).to_have_text('连接中断', timeout=6000)
            results.append('api_503')
            mode[0] = 'healthy'
            expect(page.locator('#live-price')).not_to_have_text('—', timeout=12000)
            mode[0] = 'malformed'
            expect(page.locator('#health-badge')).to_have_text('连接中断', timeout=6000)
            expect(page.locator('#live-price')).to_have_text('—')
            results.append('malformed_state_fails_closed')
            mode[0] = 'cached'
            page.reload()
            expect(page.locator('#live-price')).not_to_have_text('—')
            expect(page.locator('#health-badge')).to_have_text('连接中断', timeout=7000)
            expect(page.locator('#live-price')).to_have_text('—')
            results.append('replayed_state_cannot_renew_freshness')
            mode[0] = 'missing'
            page.reload()
            page.get_by_role('button', name='24 小时').click()
            expect(page.locator('#missing')).to_have_text('10')
            assert page.locator('#chart-svg path').get_attribute('d').count('M') == 2
            results.append('missing_chart_intervals')
            mode[0] = 'rollover'
            page.reload()
            expect(page.locator('#reference-price')).to_have_text('—', timeout=1500)
            results.append('cycle_rollover_no_old_reference')
            mode[0] = 'healthy'
            page.reload()
            expect(page.locator('#live-price')).not_to_have_text('—')
            # Timer advances even when no new state arrives; abort after four seconds.
            context.unroute('**/api/state', response)
            held = []
            context.route('**/api/state', lambda route: held.append(route))
            expect(page.locator('#live-price')).to_have_text('—', timeout=8000)
            results.append('hung_request_timeout')
            page.set_viewport_size({'width': 1024, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            results.append('desktop_layout_no_horizontal_overflow')
            assert not errors, errors
            results.append('no_browser_script_errors')
            context.unroute('**/api/state')
            for route in held:
                route.abort()
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    report = dict(passed=len(results), origin='SYNTHETIC_TEST', real_status='REAL_DATA_NOT_READY', checks=results)
    (output/'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', choices=['msedge', 'chrome'])
    run(parser.parse_args().channel)
