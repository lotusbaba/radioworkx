#!/usr/bin/env python3
"""Single-host API rolling replacement. Never rebuilds/stops station or queue workers."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.deploy'


def run(*args, capture=False, env=None):
    return subprocess.check_output(args, cwd=ROOT, env=env, text=True, stderr=subprocess.PIPE).strip() if capture else subprocess.check_call(args, cwd=ROOT, env=env)


def compose(state, *args, capture=False):
    env = dict(os.environ)
    env.update(RADIO_API_IMAGE=state['images'].get('api', 'radioworkx-api:local'),
               RADIO_NEXT_IMAGE=state['images'].get('api-next', 'radioworkx-api:local'))
    return run('docker', 'compose', '--profile', 'deployment', *args, capture=capture, env=env)


def save(state):
    path = STATE / 'state.tmp'
    path.write_text(json.dumps(state, indent=2) + '\n')
    path.replace(STATE / 'state.json')


def configuration(service, seconds):
    return f'''worker_processes auto;
worker_shutdown_timeout {seconds}s;
error_log /dev/stderr warn;
pid /var/run/nginx.pid;
events {{ worker_connections 4096; }}
http {{
  access_log off;
  resolver 127.0.0.11 valid=5s ipv6=off;
  map $http_x_forwarded_proto $radio_scheme {{ default $scheme; https https; }}
  server {{
    listen 8080;
    add_header X-Radio-Upstream {service} always;
    location / {{
      set $radio_backend {service}:8000;
      proxy_pass http://$radio_backend;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto $radio_scheme;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 1h;
      proxy_send_timeout 1h;
      proxy_next_upstream off;
    }}
  }}
}}
'''


def write_config(service, seconds):
    directory = STATE / 'nginx'
    directory.mkdir(exist_ok=True)
    temporary = directory / 'nginx.conf.tmp'
    temporary.write_text(configuration(service, seconds))
    temporary.replace(directory / 'nginx.conf')


def ready(state, service):
    code = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3); assert r.status==200"
    for _ in range(60):
        try:
            compose(state, 'exec', '-T', service, 'python', '-c', code, capture=True)
            return
        except subprocess.CalledProcessError:
            time.sleep(2)
    raise RuntimeError(f'{service} failed readiness; current API remains active')


def upstream(state):
    # Fresh HTTP connection; existing streams intentionally retain their old upstream.
    env = dict(os.environ, RADIO_API_IMAGE=state['images'].get('api', 'radioworkx-api:local'),
               RADIO_NEXT_IMAGE=state['images'].get('api-next', 'radioworkx-api:local'))
    result = subprocess.run(['docker', 'compose', '--profile', 'deployment', 'exec', '-T',
                             'proxy', 'wget', '-S', '-O', '/dev/null', 'http://127.0.0.1:8080/health'],
                            cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError('Proxy health check failed')
    for line in result.stderr.splitlines():
        if line.strip().lower().startswith('x-radio-upstream:'):
            return line.split(':', 1)[1].strip()
    raise RuntimeError('Proxy did not identify its upstream')


def finish_drain(state):
    pending = state.get('draining')
    if not pending:
        return
    while time.time() < pending['until']:
        remaining = max(0, int(pending['until'] - time.time()))
        print(f"Draining {pending['service']}: {remaining}s remaining", flush=True)
        time.sleep(min(10, max(0, pending['until'] - time.time())))
    compose(state, 'stop', pending['service'])
    state.pop('draining')
    save(state)


def recover(state):
    intent = state.get('switching')
    if intent:
        active = upstream(state)
        if active == intent['new']:
            if state['images'][intent['old']] != state['images'][intent['new']]:
                state['previous'] = state['images'][intent['old']]
            state['active'] = active
            state['draining'] = {'service': intent['old'], 'until': time.time() + state['drain_seconds'] + 5}
        elif active == intent['old']:
            write_config(active, state['drain_seconds'])
        else:
            raise RuntimeError('Unknown proxy upstream; refusing to stop either container')
        state.pop('switching')
        save(state)
    finish_drain(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'deploy', 'rollback', 'status', 'resume'])
    parser.add_argument('--image', help='Existing immutable image/tag; omit to build current source')
    parser.add_argument('--drain-seconds', type=int, default=60)
    args = parser.parse_args()
    if not 5 <= args.drain_seconds <= 3600:
        parser.error('--drain-seconds must be between 5 and 3600')
    STATE.mkdir(exist_ok=True)
    with (STATE / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another deployment is running')
        path = STATE / 'state.json'
        if args.action == 'init' and not path.exists():
            container = run('docker', 'compose', 'ps', '-q', 'api', capture=True)
            if not container:
                raise SystemExit('Start the existing api service before initializing the proxy')
            image = run('docker', 'inspect', '--format', '{{.Image}}', container, capture=True)
            state = {'active': 'api', 'images': {'api': image}, 'drain_seconds': args.drain_seconds}
            ready(state, 'api')
            write_config('api', args.drain_seconds)
            compose(state, 'up', '-d', '--no-deps', 'proxy')
            for attempt in range(15):
                try:
                    if upstream(state) == 'api':
                        break
                except (RuntimeError, subprocess.SubprocessError):
                    if attempt == 14:
                        raise
                    time.sleep(1)
            save(state)
            print('Proxy ready on loopback port 8001 (or RADIO_PROXY_PORT). Existing API was not restarted.')
            return
        if not path.exists():
            raise SystemExit('Run scripts/deploy.py init first')
        state = json.loads(path.read_text())
        if args.action in {'status', 'init'}:
            print(json.dumps(state, indent=2))
            print('Proxy upstream:', upstream(state))
            return
        recover(state)
        if args.action == 'resume':
            return
        image = state.get('previous') if args.action == 'rollback' else args.image
        if args.action == 'rollback' and not image:
            raise SystemExit('No previous deployment image is recorded')
        if not image:
            image = 'radioworkx-api:release-' + str(time.time_ns())
            run('docker', 'build', '-t', image, '.')
        image = run('docker', 'image', 'inspect', '--format', '{{.Id}}', image, capture=True)
        old = state['active']
        new = 'api-next' if old == 'api' else 'api'
        state['images'][new] = image
        save(state)
        compose(state, 'up', '-d', '--no-deps', '--no-build', new)
        ready(state, new)
        state['switching'] = {'old': old, 'new': new}
        save(state)
        write_config(new, state['drain_seconds'])
        try:
            compose(state, 'exec', '-T', 'proxy', 'nginx', '-t')
            compose(state, 'exec', '-T', 'proxy', 'nginx', '-s', 'reload')
            for _ in range(20):
                if upstream(state) == new:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Proxy did not switch')
        except Exception:
            write_config(old, state['drain_seconds'])
            compose(state, 'exec', '-T', 'proxy', 'nginx', '-s', 'reload')
            raise
        print(f'Traffic switched from {old} to {new}. Existing streams drain for {state["drain_seconds"]}s.', flush=True)
        recover(state)
        print('Deployment complete. Previous immutable image retained for rollback.')


if __name__ == '__main__':
    main()
