"""Install OpenSearch retention, mappings and a native activity overview dashboard."""
import argparse
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
VIEW = 'rwx-opensearch-events'
DASHBOARD = 'rwx-activity-overview'


def build_objects():
    source = {'indexRefName': 'kibanaSavedObjectMeta.searchSourceJSON.index',
              'query': {'query': '', 'language': 'kuery'}, 'filter': []}
    refs = [{'name': source['indexRefName'], 'type': 'index-pattern', 'id': VIEW}]
    objects = [{'type': 'index-pattern', 'id': VIEW, 'attributes': {
        'title': 'radioworkx-events-*', 'timeFieldName': '@timestamp',
        'fields': json.dumps([{'name': name, 'type': 'date' if name == '@timestamp' else 'string',
            'searchable': True, 'aggregatable': True, 'readFromDocValues': True}
            for name in ['@timestamp', 'event.action', 'event.outcome', 'service.name',
                         'user.id', 'session.id', 'radioworkx.category', 'radioworkx.track_title',
                         'radioworkx.track_id', 'radioworkx.mode', 'radioworkx.artists',
                         'radioworkx.album', 'radioworkx.genre']])}}]

    def visual(key, title, kind, params, aggs):
        objects.append({'type': 'visualization', 'id': key, 'attributes': {
            'title': title, 'description': 'RadioWorkx activity', 'uiStateJSON': '{}',
            'visState': json.dumps({'title': title, 'type': kind, 'params': params, 'aggs': aggs}),
            'kibanaSavedObjectMeta': {'searchSourceJSON': json.dumps(source)}}, 'references': refs})

    count = {'id': '1', 'enabled': True, 'type': 'count', 'schema': 'metric', 'params': {}}
    visual('rwx-os-actions', 'Event actions over time', 'area', {
        'type': 'area', 'addLegend': True, 'legendPosition': 'left', 'addTimeMarker': False,
        'addTooltip': True, 'interpolate': 'linear', 'scale': 'linear', 'mode': 'stacked',
        'times': [], 'grid': {'categoryLines': False},
        'categoryAxes': [{'id': 'CategoryAxis-1', 'type': 'category', 'position': 'bottom',
                          'show': True, 'style': {}, 'scale': {'type': 'linear'},
                          'labels': {'show': True, 'truncate': 100}, 'title': {}}],
        'valueAxes': [{'id': 'ValueAxis-1', 'name': 'LeftAxis-1', 'type': 'value',
                       'position': 'left', 'show': True, 'style': {}, 'scale': {'type': 'linear', 'mode': 'normal'},
                       'labels': {'show': True}, 'title': {'text': 'Events'}}],
        'seriesParams': [{'show': True, 'type': 'area', 'mode': 'stacked', 'data': {'label': 'Count', 'id': '1'},
                          'valueAxis': 'ValueAxis-1', 'drawLinesBetweenPoints': True,
                          'lineWidth': 1, 'showCircles': False}]}, [count,
        {'id': '2', 'enabled': True, 'type': 'date_histogram', 'schema': 'segment',
         'params': {'field': '@timestamp', 'interval': 'auto', 'min_doc_count': 1,
                    'extended_bounds': {}}},
        {'id': '3', 'enabled': True, 'type': 'terms', 'schema': 'group',
         'params': {'field': 'event.action', 'size': 10, 'order': 'desc', 'orderBy': '1'}}])
    visual('rwx-os-categories', 'Event categories and actions', 'pie', {
        'type': 'pie', 'addTooltip': True, 'addLegend': True, 'legendPosition': 'right',
        'isDonut': True, 'labels': {'show': False, 'values': True, 'last_level': True}}, [count,
        {'id': '2', 'enabled': True, 'type': 'terms', 'schema': 'segment',
         'params': {'field': 'radioworkx.category', 'size': 10, 'order': 'desc', 'orderBy': '1'}},
        {'id': '3', 'enabled': True, 'type': 'terms', 'schema': 'segment',
         'params': {'field': 'event.action', 'size': 5, 'order': 'desc', 'orderBy': '1'}}])
    objects.append({'type': 'search', 'id': 'rwx-os-audit', 'attributes': {
        'title': 'Activity audit table', 'columns': ['event.action', 'radioworkx.category',
            'service.name', 'user.id', 'radioworkx.track_title', 'radioworkx.mode', 'event.outcome'],
        'sort': [['@timestamp', 'desc']],
        'kibanaSavedObjectMeta': {'searchSourceJSON': json.dumps(source)}}, 'references': refs})
    layout = []
    panel_refs = []
    for i, (kind, key, x, y, width, height) in enumerate([
        ('visualization', 'rwx-os-actions', 0, 0, 28, 16),
        ('visualization', 'rwx-os-categories', 28, 0, 20, 16),
        ('search', 'rwx-os-audit', 0, 16, 48, 25),
    ]):
        name = 'panel_' + str(i)
        panel_refs.append({'name': name, 'type': kind, 'id': key})
        layout.append({'panelIndex': str(i), 'type': kind, 'panelRefName': name, 'version': '3.8.0',
                       'gridData': {'x': x, 'y': y, 'w': width, 'h': height, 'i': str(i)},
                       'embeddableConfig': {}})
    objects.append({'type': 'dashboard', 'id': DASHBOARD, 'attributes': {
        'title': 'RadioWorkx · Activity overview',
        'description': 'Search and filter user actions, playback, requests, downloads and admin audit. '
                       'Listener IDs are pseudonymous; client listening is estimated. '
                       'Chart shows the top actions; the table includes all matching events.',
        'panelsJSON': json.dumps(layout), 'optionsJSON': json.dumps({'useMargins': True, 'hidePanelTitles': False}),
        'timeRestore': True, 'timeFrom': 'now-24h', 'timeTo': 'now',
        'refreshInterval': {'pause': False, 'value': 30000},
        'kibanaSavedObjectMeta': {'searchSourceJSON': json.dumps({'query': {'query': '', 'language': 'kuery'}, 'filter': []})}},
        'references': panel_refs})
    return objects


def configure(client, base):
    policy_id = 'radioworkx-30d'
    url = base + '/_plugins/_ism/policies/' + policy_id
    current = client.get(url)
    if current.status_code == 404:
        response = client.put(url, json={'policy': {
            'description': 'Delete RadioWorkx activity indices after 30 days', 'default_state': 'hot',
            'states': [{'name': 'hot', 'actions': [], 'transitions': [
                {'state_name': 'delete', 'conditions': {'min_index_age': '30d'}}]},
                {'name': 'delete', 'actions': [{'delete': {}}], 'transitions': []}],
            'ism_template': [{'index_patterns': ['radioworkx-events-*'], 'priority': 200}]}})
        response.raise_for_status()
    else:
        current.raise_for_status()
    mapping = {'dynamic_templates': [{'strings': {'match_mapping_type': 'string',
        'mapping': {'type': 'keyword', 'ignore_above': 1024}}}], 'properties': {
        '@timestamp': {'type': 'date'}, 'event': {'properties': {
            'id': {'type': 'keyword'}, 'action': {'type': 'keyword'},
            'outcome': {'type': 'keyword'}, 'duration': {'type': 'long'}}},
        'service': {'properties': {'name': {'type': 'keyword'}}},
        'user': {'properties': {'id': {'type': 'keyword'}}},
        'session': {'properties': {'id': {'type': 'keyword'}}},
        'radioworkx': {'properties': {**{key: {'type': 'keyword'} for key in [
            'category', 'track_title', 'track_id', 'mode', 'artists', 'album', 'genre']},
            **{key: {'type': 'double'} for key in ['latency_ms', 'queue_delay_ms', 'position_seconds', 'seek_from', 'seek_to']},
            'listened_ms': {'type': 'long'}}}}}
    response = client.put(base + '/_index_template/radioworkx-events', json={
        'index_patterns': ['radioworkx-events-*'], 'priority': 200, 'template': {
            'settings': {'number_of_shards': 1, 'number_of_replicas': 0}, 'mappings': mapping}})
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opensearch', default='http://127.0.0.1:9201')
    parser.add_argument('--dashboards', default='http://127.0.0.1:5602')
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'infra/opensearch/dashboards.ndjson'
    path.write_text('\n'.join(json.dumps(obj) for obj in build_objects()) + '\n')
    if args.build_only:
        print(path)
        return
    with httpx.Client(timeout=30) as client:
        for base, endpoint in [(args.opensearch, '/_cluster/health'), (args.dashboards, '/api/status')]:
            for _ in range(120):
                try:
                    response = client.get(base + endpoint)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Service readiness timed out: ' + base)
        configure(client, args.opensearch)
        fields = client.get(args.dashboards + '/api/index_patterns/_fields_for_wildcard',
                            params={'pattern': 'radioworkx-events-*'}, headers={'osd-xsrf': 'true'})
        if fields.status_code == 200 and fields.json().get('fields'):
            objects = build_objects()
            objects[0]['attributes']['fields'] = json.dumps(fields.json()['fields'])
            path.write_text('\n'.join(json.dumps(obj) for obj in objects) + '\n')
        elif fields.status_code not in (200, 404):
            fields.raise_for_status()
        with path.open('rb') as file:
            response = client.post(args.dashboards + '/api/saved_objects/_import?overwrite=true',
                headers={'osd-xsrf': 'true'}, files={'file': (path.name, file, 'application/ndjson')})
        response.raise_for_status()
        result = response.json()
        if not result.get('success'):
            raise RuntimeError(json.dumps(result))
        response = client.post(args.dashboards + '/api/opensearch-dashboards/settings',
            headers={'osd-xsrf': 'true'}, json={'changes': {'defaultIndex': VIEW, 'theme:darkMode': False,
                'defaultRoute': '/app/dashboards#/view/' + DASHBOARD}})
        response.raise_for_status()
        print(json.dumps({'imported': result.get('successCount'),
                          'dashboard': args.dashboards + '/app/dashboards#/view/' + DASHBOARD}))


if __name__ == '__main__':
    main()
