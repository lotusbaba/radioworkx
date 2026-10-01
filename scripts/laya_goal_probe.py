"""Offline diagnostic of search-goal wording; no browser or application mutations.

Run from the repository root with .venv-adversary/bin/python scripts/laya_goal_probe.py.
This measures action selection on supplied text, not completion of a browser test.
"""
import argparse
import html
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adversary.inference.laya import LayaBackend
from adversary.inference.download_laya import REPOSITORY, REVISION
from adversary.scenarios import SCENARIOS

CHOICES = {
    'click': 'Activate a link or button needed for the goal.',
    'fill': 'Enter text needed for the goal into a field.',
    'key_press': 'Submit the entered text with Enter.',
    'reload': 'Refresh the current page to check persistence.',
    'wait': 'Wait for an operation already in progress to finish.',
    'scroll': 'Reveal controls below the visible area.',
}
GOALS = {
    # Frozen historical input: keep model comparisons reproducible as live goals evolve.
    'current': 'Search for QA Artist using the search field and Search button. Then finish exploration.',
    'simple': 'Test search by searching for QA Artist. Which of these choices should I go with next?',
    'paragraph': (
        'Our goal is to test the search feature on the RadioWorkx artists page. '
        'We want to search for QA Artist and check that the results include QA Artist. '
        'Use the search field and the Search button to perform this test. '
        'Choose the next action based on the current state of the search field. '
        'We are testing search, not whether the page persists after refreshing. '
        'Which of the supplied choices should I go with next?'
    ),
}


def cases():
    for field, expected, history in [('empty', 'fill', []), ('QA Artist', 'click', ['Filled search field with QA Artist'])]:
        for variant, goal in GOALS.items():
            state = {'goal': goal, 'completed_actions': history,
                     'page': 'Music library — RadioWorkx', 'url': 'http://127.0.0.1:8011/artists',
                     'visible_text': f'The artists page is fully loaded. The search field is {"empty" if field == "empty" else "filled with QA Artist"}. '
                         'An enabled Search button is visible. No search has been submitted. No request is in progress.'}
            yield {'name': f'{variant} / field {field}', 'state': state, 'expected': expected,
                   'comparison': 'Goal wording only; page state and choices held fixed within each field condition.'}
    yield {'name': 'paragraph / plain text / empty field',
           'state': GOALS['paragraph'] + '\n\nCurrent page state: The artists page is fully loaded. '
                    'The search field is empty. An enabled Search button is visible. '
                    'No search has been submitted. No request is in progress. No actions have been completed.',
           'expected': 'fill', 'comparison': 'Separate plain-text probe; input format also changes.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('runs/laya-browser-goal-wording'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    # Fail any attempted network connection, in addition to backend offline flags.
    def blocked(*args, **kwargs):
        raise RuntimeError('Outbound network disabled for this local text probe')
    socket.socket.connect = blocked
    backend = LayaBackend(device='cpu')
    started = time.monotonic()
    backend.load()
    loaded = time.monotonic() - started
    results = []
    with (args.output / 'results.jsonl').open('x') as journal:
        for case in cases():
            started = time.monotonic()
            selected, confidence, probabilities = backend.predict(case['state'], CHOICES)
            result = {**case, 'choices': CHOICES, 'selected': selected, 'answer_confidence': confidence,
                      'probabilities': probabilities, 'matches_expected': selected == case['expected'],
                      'inference_ms': (time.monotonic() - started) * 1000}
            journal.write(json.dumps(result) + '\n'); journal.flush()
            results.append(result)
            print(f'{case["name"]}: selected={selected}, expected={case["expected"]}, probability={confidence}', flush=True)
    summary = {'repository': REPOSITORY, 'checkpoint_revision': REVISION, 'device': backend.device, 'load_seconds': loaded,
               'network': 'socket connections blocked', 'browser_executed': False,
               'model_calls': len(results), 'matches_expected': sum(r['matches_expected'] for r in results),
               'results': results}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    rows = ''.join('<tr><td>' + html.escape(r['name']) + '</td><td>' + r['expected'] + '</td><td>' + r['selected'] + '</td>'
                   + ''.join(f'<td>{r["probabilities"][c]:.2%}</td>' for c in CHOICES) + '</tr>' for r in results)
    details = ''.join('<details><summary>' + html.escape(r['name']) + '</summary><pre>'
                     + html.escape(json.dumps(r, indent=2)) + '</pre></details>' for r in results)
    (args.output / 'review.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>Laya search-goal wording probe</title>'
        '<style>body{font:16px system-ui;margin:2rem}td,th{padding:.6rem;border-bottom:1px solid #ccc;text-align:left}'
        'pre{white-space:pre-wrap}details{margin:1rem 0}.note{background:#fff3cd;padding:1rem}</style>'
        '<h1>Local Laya Browser: search-goal wording probe</h1><p>' + html.escape(REPOSITORY + '@' + REVISION)
        + '</p><p class="note">Checkpoint-only comparison using the existing generic prompt, not the model-specific browser adapter. Text-only diagnostic. No browser ran. '
        'One prediction per case; this is not a reliability benchmark or proof of goal understanding. '
        'The state explicitly describes the field contents, which the existing browser prompt does not.</p>'
        '<h2>Current goal</h2><p>' + html.escape(GOALS['current']) + '</p><h2>Paragraph goal tested</h2><p>'
        + html.escape(GOALS['paragraph']) + '</p><p>Expected next action: Fill when empty; Click the Search button when filled. '
        'These expectations are used for evaluation and are not sent as answer labels to Laya.</p>'
        '<table><thead><tr><th>Case</th><th>Expected</th><th>Selected</th>'
        + ''.join('<th>' + c + '</th>' for c in CHOICES) + '</tr></thead><tbody>' + rows + '</tbody></table>'
        '<h2>Exact inputs and outputs</h2>' + details + '<p><a href="summary.json">JSON results</a></p>')
    print('Report:', (args.output / 'review.html').resolve())


if __name__ == '__main__':
    main()
