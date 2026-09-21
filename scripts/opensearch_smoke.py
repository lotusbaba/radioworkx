"""Verify real activity ingestion and the native OpenSearch dashboard in Chrome."""
import json
from pathlib import Path
import time

import httpx
from playwright.sync_api import sync_playwright

OUT = Path('/tmp/rwx-opensearch-check')
OUT.mkdir(exist_ok=True)
with sync_playwright() as p, httpx.Client(timeout=15) as client:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    started = time.time()
    page.goto('https://radioworkx.tail060b33.ts.net/artists', wait_until='domcontentloaded')
    with page.expect_response(lambda r: '/api/activity' in r.url and r.request.method == 'POST', timeout=20000) as sent:
        page.get_by_role('heading', name='Meet the artists.', exact=True).wait_for()
    assert sent.value.status == 202
    session_id = sent.value.request.post_data_json['session_id']
    query = {'query': {'bool': {'filter': [{'term': {'event.action': 'page.view'}},
             {'term': {'session.id': session_id}},
             {'range': {'@timestamp': {'gte': int(started * 1000), 'format': 'epoch_millis'}}}]}}, 'size': 1}
    for _ in range(30):
        result = client.post('http://127.0.0.1:9201/radioworkx-events-*/_search', json=query)
        result.raise_for_status()
        hits = result.json()['hits']['hits']
        if hits:
            break
        time.sleep(2)
    assert hits, 'New browser page view did not reach OpenSearch'
    event = hits[0]['_source']
    assert hits[0]['_id'] == event['event']['id']
    assert event['radioworkx']['category'] == 'page'
    # Both independently tailed destinations should receive the same real event.
    result = client.post('http://127.0.0.1:9200/radioworkx-events-*/_search',
                         json={'query': {'ids': {'values': [hits[0]['_id']]}}})
    result.raise_for_status()
    assert result.json()['hits']['total']['value'] == 1
    page.goto('http://127.0.0.1:5602/app/dashboards#/view/rwx-activity-overview', wait_until='domcontentloaded')
    page.get_by_text('Event actions over time', exact=True).first.wait_for(timeout=90000)
    page.get_by_text('Activity audit table', exact=True).first.wait_for(timeout=60000)
    page.wait_for_timeout(10000)
    body = page.locator('body').inner_text()
    (OUT / 'overview.txt').write_text(body)
    page.screenshot(path=str(OUT / 'overview.png'), full_page=True)
    for error in ['Error loading', 'Unable to load', 'Could not locate', 'No results found', 'Saved object is missing']:
        assert error not in body, body
    assert 'Event categories and actions' in body
    assert 'page.view' in body or 'api.request' in body
    print(json.dumps({'ingestion': 'real browser event in both OpenSearch and Elasticsearch',
                      'dashboard': 'rendered', 'screenshot': str(OUT / 'overview.png'), 'body': body[:7000]}))
    browser.close()
