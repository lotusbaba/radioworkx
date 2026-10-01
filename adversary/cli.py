"""Bounded dual-engine exploration and model-free replay on synthetic RadioWorkx."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys
import uuid

from adversary.runtime.coordinator import coordinate
from adversary.runtime.qa import FIXTURE_VERSION
from adversary.scenarios import SCENARIOS


def bounded(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}..{high}')
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--engine', choices=['custom', 'browser-use', 'scripted'], default='custom')
    run.add_argument('--scenario', choices=list(SCENARIOS), default='library-search')
    run.add_argument('--agents', type=bounded(1, 4), default=1)
    run.add_argument('--max-steps', type=bounded(3, 100), default=12)
    run.add_argument('--max-model-calls', type=bounded(1, 400), default=12)
    run.add_argument('--timeout', type=bounded(10, 1800), default=180)
    run.add_argument('--model')
    run.add_argument('--generative-fallback', action='store_true', help='Custom engine: enable bounded OpenAI reasoning')
    run.add_argument('--max-fallback-calls', type=bounded(1, 100), default=4)
    run.add_argument('--decision-provider', choices=['laya', 'jev'], default='laya')
    run.add_argument('--laya-model', type=Path, help='Local pinned Laya checkpoint directory')
    run.add_argument('--device', choices=['cpu', 'mps'], default='cpu')
    run.add_argument('--env-file', default='.env')
    run.add_argument('--headed', action='store_true')
    run.add_argument('--channel', choices=['chrome', 'chromium'], default='chrome')
    run.add_argument('--output', type=Path)
    social = sub.add_parser('social-sessions', help='Coordinated owner/follower/guest checks on one disposable fixture')
    social.add_argument('--output', type=Path, required=True)
    social.add_argument('--channel', choices=['chrome', 'chromium'], default='chrome')
    replay = sub.add_parser('replay')
    replay.add_argument('session', type=Path, help='Directory containing actions.jsonl')
    replay.add_argument('--output', type=Path)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('directory', type=Path)
    sub.add_parser('list-runs')
    sub.add_parser('list-scenarios')
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    if args.command == 'list-scenarios':
        for name, scenario in SCENARIOS.items():
            print(f'{name}: {scenario.goal}')
        return
    if args.command == 'list-runs':
        for path in sorted(Path('runs').glob('*/summary.json')):
            print(path.parent)
        return
    if args.command == 'inspect':
        print((args.directory / 'summary.json').read_text())
        return
    if args.command == 'social-sessions':
        from adversary.runtime.social_sessions import coordinate_social
        result = asyncio.run(coordinate_social(args.output, args.channel))
        print(json.dumps(result, indent=2))
        print(f'Results: {args.output.resolve() / "report.html"}')
        sys.exit(0 if result['status'] == 'passed' else 1)
    service = None
    events = None
    if args.command == 'run':
        if args.generative_fallback and args.engine != 'custom':
            parser.error('--generative-fallback requires --engine custom')
        config = {key: getattr(args, key) for key in ('engine', 'scenario', 'agents', 'max_steps', 'timeout', 'headed', 'channel')}
        if args.engine == 'scripted' and not SCENARIOS[args.scenario].search_kind:
            parser.error('scripted supports search scenarios; use a model engine for other goals')
        if args.engine == 'custom' and args.decision_provider == 'jev':
            from adversary.inference.jev import credentials
            from adversary.inference.jev_service import JevDecisionService
            service = JevDecisionService(credentials(args.env_file), args.model or 'jev-latest', args.max_model_calls)
            config.update(model=service.model, decision_provider='jev', device='hosted', max_model_calls=args.max_model_calls)
        elif args.engine == 'custom':
            if args.model:
                parser.error('--model configures Browser Use; custom uses --laya-model')
            from adversary.inference.laya import LayaDecisionService
            from adversary.inference.download_laya import DEFAULT_PATH
            checkpoint = args.laya_model or DEFAULT_PATH
            if not (checkpoint / 'manifest.json').is_file():
                parser.error('Download Laya first: python -m adversary.inference.download_laya')
            service = LayaDecisionService(checkpoint, args.device, args.max_model_calls)
            config.update(model=service.model, device=args.device, max_model_calls=args.max_model_calls)
        elif args.engine == 'browser-use':
            from adversary.inference.openai import DecisionService, credentials
            key, model = credentials(args.env_file)
            service = DecisionService(key, args.model or model, args.max_model_calls)
            config['model'] = service.model
            config['max_model_calls'] = args.max_model_calls
        if args.generative_fallback:
            from adversary.inference.openai import DecisionService, credentials
            from adversary.inference.hybrid import HybridDecisionService
            key, model = credentials(args.env_file)
            service = HybridDecisionService(service, DecisionService(key, model, args.max_fallback_calls))
            config.update(generative_fallback=True, fallback_model=model, max_fallback_calls=args.max_fallback_calls)
    else:
        from adversary.runtime.replay import load_session
        try:
            events, first = load_session(args.session)
        except (ValueError, KeyError) as error:
            parser.error(str(error))
        config = {**first['config'], 'agents': 1, 'engine': 'scripted', 'headed': False}
    output = args.output or Path('runs') / (args.command + '-' + uuid.uuid4().hex[:12])
    async def execute():
        try:
            return await coordinate(output, config, service, events)
        finally:
            if hasattr(service, 'aclose'):
                await service.aclose()
    result = asyncio.run(execute())
    if events is not None:
        expected = {event['fingerprint'] for event in events if event['kind'] == 'finding'}
        actual = {f['fingerprint'] for s in result['sessions'] for f in s['findings']}
        failed = any(s['status'] == 'harness_error' for s in result['sessions'])
        result['replay'] = 'ERROR' if failed else ('REPRODUCED' if expected and expected <= actual else
                           'NOT_REPRODUCED' if expected else 'COMPLETED_NO_ORIGINAL_FINDING')
        (output / 'summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f'Results: {output.resolve()}')
    if any(s['status'] == 'harness_error' for s in result['sessions']):
        sys.exit(2)
    if any(s['findings'] for s in result['sessions']):
        sys.exit(1)
    if any(s['status'] == 'incomplete' for s in result['sessions']) or result.get('replay') == 'NOT_REPRODUCED':
        sys.exit(3)


if __name__ == '__main__':
    main()
