"""Compare hosted Jev on the seven existing Laya search-goal probes (no browser).

Run: .venv-adversary/bin/python scripts/jev_goal_probe.py
Reads JEV_AI_API_KEY (or legacy JEV_API_KEY). At most seven requests, no retries.
"""
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adversary.inference.jev import ENDPOINT, INSTRUCTIONS, JevClient, JevError, credentials
from scripts.laya_goal_probe import CHOICES, cases


def run_probe(client, output, baseline=None):
    output.mkdir(parents=True, exist_ok=False)
    previous = {r['name']: r for r in (baseline or {}).get('results', [])}
    results = []
    stopped = False
    with (output / 'results.jsonl').open('x') as journal:
        for case in cases():
            row = {**case, 'choices': CHOICES, 'instructions': INSTRUCTIONS}
            prior = previous.get(case['name'])
            if prior and prior['state'] == case['state'] and prior['choices'] == CHOICES:
                row['laya_comparison'] = {k: prior[k] for k in ('selected', 'probabilities', 'matches_expected')}
            if stopped:
                row.update(status='not_run', error='Stopped after previous API failure')
            else:
                started = time.monotonic()
                try:
                    row.update(client.predict(case['state'], CHOICES))
                    row.update(status='completed', matches_expected=row['selected'] == case['expected'])
                except JevError as error:
                    row.update(status='error', error=str(error))
                    stopped = True
                row['inference_ms'] = (time.monotonic() - started) * 1000
            results.append(row)
            journal.write(json.dumps(row) + '\n')
            journal.flush()
            print(f'{case["name"]}: {row["status"]}, selected={row.get("selected", "—")}, expected={case["expected"]}', flush=True)
    summary = {'created_at': datetime.now(timezone.utc).isoformat(), 'endpoint': ENDPOINT,
               'requested_model': client.model, 'browser_executed': False,
               'planned_cases': len(results), 'requests_attempted': sum(r['status'] != 'not_run' for r in results),
               'completed_cases': sum(r['status'] == 'completed' for r in results),
               'matches_expected': sum(r.get('matches_expected', False) for r in results), 'results': results}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    write_report(output, summary)
    return summary


def write_report(output, summary):
    esc = lambda value: html.escape(str(value))
    rows = []
    for r in summary['results']:
        cells = [r['name'], r['expected'], r.get('selected', r['status']),
                 r.get('laya_comparison', {}).get('selected', 'unavailable')]
        cells += [f'{r["probabilities"][c]:.2%}' if 'probabilities' in r else '—' for c in CHOICES]
        rows.append('<tr>' + ''.join('<td>' + esc(c) + '</td>' for c in cells) + '</tr>')
    details = ''.join('<details><summary>' + esc(r['name']) + '</summary><pre>'
                      + esc(json.dumps(r, indent=2)) + '</pre></details>' for r in summary['results'])
    (output / 'review.html').write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Jev search-goal comparison</title>'
        '<style>body{font:16px system-ui;margin:2rem;color:#172536}table{border-collapse:collapse}'
        'td,th{padding:.6rem;border-bottom:1px solid #ccd;text-align:left}pre{white-space:pre-wrap}'
        'details{margin:1rem 0}.note{background:#fff3cd;padding:1rem}.table{overflow-x:auto}</style>'
        '<h1>Jev: search-goal comparison</h1><p>' + esc(summary['created_at']) + '</p><h2>'
        + str(summary['matches_expected']) + '/' + str(summary['planned_cases']) + ' expected actions selected</h2><p>'
        + str(summary['completed_cases']) + ' completed responses; ' + str(summary['requests_attempted'])
        + ' requests attempted.</p><p class="note">Text-only diagnostic: no browser ran. One prediction per case; '
        'this does not establish search completion or model reliability. Empty field expects Fill; filled field '
        'expects Click Search. Enter could also submit, but is not the prescribed button-click expectation. '
        'Evaluation labels are never sent to the model.</p><p>Same states, choices and question instructions as '
        'the Laya probe. Historical Laya results are included only when state and choices match exactly. '
        'Percentages below are choice probabilities; provider confidence is recorded separately in details.</p>'
        '<div class="table"><table><tr>' + ''.join('<th>' + esc(c) + '</th>' for c in
        ['Case', 'Expected', 'Jev selected', 'Earlier Laya selected', *CHOICES]) + '</tr>'
        + ''.join(rows) + '</table></div><h2>Exact inputs and outputs</h2>' + details
        + '<p><a href="summary.json">JSON report</a> · <a href="results.jsonl">Results journal</a> · '
        '<a href="https://jev-ai.pro/docs">Provider API documentation</a></p></html>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('runs/jev-goal-wording'))
    parser.add_argument('--baseline', type=Path, default=Path('runs/laya-goal-wording/summary.json'))
    args = parser.parse_args()
    client = JevClient(credentials())
    baseline = json.loads(args.baseline.read_text()) if args.baseline.is_file() else None
    summary = run_probe(client, args.output, baseline)
    print('Report:', (args.output / 'review.html').resolve())
    return 0 if summary['completed_cases'] == summary['planned_cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
