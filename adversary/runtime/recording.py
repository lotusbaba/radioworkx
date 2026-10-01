"""Append-only, flushed intent/result journal and portable summaries."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time


def fingerprint(kind, message):
    normalized = re.sub(r'https?://[^/\s]+', '<origin>', message)
    return hashlib.sha256((kind + ':' + normalized).encode()).hexdigest()[:20]


def choice_tables(events):
    sections = []
    for event in events:
        if event['kind'] not in ('decision', 'decision_error'):
            continue
        route = event.get('inference', {}).get('route')
        if route:
            sections.append('<p>Route: ' + html.escape(route['path']) + ' — ' +
                html.escape(route['reason']) + '</p>')
        for index, stage in enumerate(event.get('inference', {}).get('stages', []), 1):
            heading = html.escape(f"{event.get('request_id', '')} — stage {index}")
            if stage.get('selection') == 'deterministic':
                sections.append(f'<h3>{heading}</h3><p>Direct selection: '
                    + html.escape(stage['selected']) + ' (sole candidate). No model call or probability.</p>')
                continue
            probabilities = stage.get('probabilities')
            if probabilities is None:
                if stage.get('provider'):
                    sections.append(f'<h3>{heading}</h3><p>Generative selection: ' +
                        html.escape(stage['choices'].get(stage['selected'], stage['selected'])) + '. Provider does not supply choice probabilities.</p>')
                continue  # Do not invent probabilities.
            rows = ''.join('<tr><td>' + html.escape(label) + '</td><td>'
                + html.escape(stage['choices'][label]) + f'</td><td>{probability:.2%}</td><td>'
                + ('Selected' if label == stage['selected'] else '') + '</td></tr>'
                for label, probability in sorted(probabilities.items(), key=lambda item: -item[1]))
            sections.append(f'<h3>{heading}</h3><table><thead><tr><th>Choice</th><th>Description</th>'
                            '<th>Model probability</th><th>Selection</th></tr></thead><tbody>' + rows + '</tbody></table>')
    if not sections:
        return ''
    return ('<h2>Decision probabilities</h2><p>Probabilities apply within each stage and sum to approximately '
            '100% (rounding). They do not measure test success or application correctness.</p>' + ''.join(sections))


class Recorder:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.file = (self.directory / 'actions.jsonl').open('x')
        self.events = []

    def write(self, kind, **data):
        event = dict(schema_version=1, kind=kind, timestamp=time.time(), **data)
        self.file.write(json.dumps(event, ensure_ascii=False) + '\n')
        self.file.flush()
        os.fsync(self.file.fileno())
        self.events.append(event)
        return event

    def finish(self, summary):
        self.write('summary', **summary)
        (self.directory / 'summary.json').write_text(json.dumps(summary, indent=2))
        rows = ''.join('<tr><td>' + html.escape(e['kind']) + '</td><td><pre>' +
                       html.escape(json.dumps(e, indent=2)) + '</pre></td></tr>' for e in self.events)
        (self.directory / 'report.html').write_text(
            '<!doctype html><meta charset="utf-8"><title>Adversary run</title>'
            '<style>body{font:15px system-ui;margin:2rem}td{vertical-align:top;border-bottom:1px solid #ccc}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere}a{margin-right:1rem}</style>'
            '<h1>' + html.escape(summary['status']) + '</h1>'
            '<a href="summary.json">Summary</a><a href="actions.jsonl">Actions</a>'
            + ''.join(f'<a href="{html.escape(p.name)}">{html.escape(p.name)}</a>'
                      for p in sorted(self.directory.glob('*')) if p.suffix in ('.zip', '.png'))
            + choice_tables(self.events) + '<h2>Raw event records</h2><table>' + rows + '</table>')
        self.file.close()
