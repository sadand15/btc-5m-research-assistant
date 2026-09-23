from mobile import render


def test_mobile_first_response_contains_content_without_js():
    html=render({'state':{'price':90001.2,'cycle_open':90000,'up_probability':.7,'connection':'CONNECTED',
                         'event_time':180000,'cycle_id':0,'venue_status':'<script>bad</script>'},
                 'server_time':180001,'points':[],'orders':[],'research':{}})
    assert '90,001.20' in html and '70.0%' in html
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'http-equiv="refresh"' in html
