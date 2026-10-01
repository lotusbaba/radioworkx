"""Reject incomplete/corrupt journals before opening a browser or QA fixture."""
import json
from pathlib import Path

from adversary.models.action import NavigateAction, browser_action_adapter
from .browser import ActionPolicy
from .qa import FIXTURE_VERSION


def load_session(directory):
    events = [json.loads(line) for line in (Path(directory) / 'actions.jsonl').read_text().splitlines()]
    if not events or any(event.get('schema_version') != 1 for event in events):
        raise ValueError('Unsupported journal version')
    runs = [event for event in events if event.get('kind') == 'run']
    if len(runs) != 1 or runs[0]['fixture'] != FIXTURE_VERSION:
        raise ValueError('Recording uses an incompatible fixture version')
    first = runs[0]
    policy = ActionPolicy(first['origin'])
    step = 0
    pending = None
    for event in events:
        if event['kind'] == 'intent':
            if pending is not None or event['step'] != step:
                raise ValueError('Incomplete or out-of-order action journal')
            action = browser_action_adapter.validate_python(event['action'])
            if isinstance(action, NavigateAction):
                policy.resolve(action.url)
            pending = step
        elif event['kind'] == 'result':
            if pending is None or event['step'] != pending or event['status'] not in ('ok', 'error'):
                raise ValueError('Unmatched action result')
            step += 1
            pending = None
    if pending is not None:
        raise ValueError('Recording has an interrupted action with unknown outcome')
    if not step:
        raise ValueError('Recording has no actions')
    return events, first
