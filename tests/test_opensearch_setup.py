import json
import httpx
from scripts.setup_opensearch import build_objects, configure


def test_dashboard_references_resolve_and_audit_spans_full_width():
    objects = build_objects()
    identities = {(obj['type'], obj['id']) for obj in objects}
    fields = json.loads(objects[0]['attributes']['fields'])
    assert {'@timestamp', 'event.action', 'radioworkx.category'} <= {f['name'] for f in fields}
    for obj in objects:
        for ref in obj.get('references', []):
            assert (ref['type'], ref['id']) in identities
    dashboard = next(obj for obj in objects if obj['type'] == 'dashboard')
    panels = json.loads(dashboard['attributes']['panelsJSON'])
    assert all(panel['version'] == '3.8.0' for panel in panels)
    table = next(panel for panel in panels if panel['type'] == 'search')
    assert table['gridData']['w'] == 48
    assert dashboard['attributes']['timeFrom'] == 'now-24h'
    assert {json.loads(obj['attributes']['visState'])['type']
            for obj in objects if obj['type'] == 'visualization'} == {'area', 'pie'}


def test_retention_installed_before_ingestion_and_mapping_supports_filters():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(404 if request.method == 'GET' else 200, json={})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        configure(client, 'http://opensearch:9200')
    policy = json.loads(requests[1].content)['policy']
    assert policy['states'][0]['transitions'][0]['conditions']['min_index_age'] == '30d'
    assert policy['states'][1]['actions'] == [{'delete': {}}]
    template = json.loads(requests[2].content)['template']
    assert template['settings']['number_of_replicas'] == 0
    assert template['mappings']['properties']['radioworkx']['properties']['category']['type'] == 'keyword'


def test_rerun_preserves_existing_retention_policy():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        configure(client, 'http://opensearch:9200')
    assert len(requests) == 2
    assert requests[0].method == 'GET'
    assert '/_index_template/' in str(requests[1].url)
