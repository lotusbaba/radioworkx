"""Fresh app subprocess per session; never inherit live service configuration."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import asynccontextmanager

import httpx

FIXTURE_VERSION = 'radioworkx-synthetic-v2'
TEST_DB = 'postgresql://radioworkx_test:local-test-only@127.0.0.1:55432/radioworkx_test'


@asynccontextmanager
async def qa_target():
    with tempfile.TemporaryDirectory(prefix='rwx-adversary-') as directory:
        ready = Path(directory) / 'ready.json'
        # Deliberately no .env, API keys, cloud credentials, live DB or Redis.
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'LANG') if k in os.environ}
        env.update(TEST_DATABASE_URL=os.environ.get('TEST_DATABASE_URL', TEST_DB),
                   DATA_DIR=directory, TELEMETRY_ENABLED='0', COOKIE_SECURE='0',
                   SESSION_SECRET='synthetic-qa-only', AWS_EC2_METADATA_DISABLED='true',
                   AWS_ACCESS_KEY_ID='qa', AWS_SECRET_ACCESS_KEY='qa',
                   AWS_ENDPOINT_URL='http://127.0.0.1:1', REDIS_URL='redis://127.0.0.1:1/0',
                   ANNOUNCER_ENABLED='0', DEMO_MODE='1')
        with (Path(directory) / 'server.log').open('w') as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'adversary.runtime.qa_server', '--ready', str(ready),
                env=env, stdout=log, stderr=log)
            try:
                for _ in range(200):
                    if ready.exists():
                        url = json.loads(ready.read_text())['url']
                        async with httpx.AsyncClient(trust_env=False) as client:
                            try:
                                response = await client.get(url + '/__qa/manifest')
                                if response.status_code == 200 and response.json()['fixture'] == FIXTURE_VERSION:
                                    catalog = await client.get(url + '/api/library/artists')
                                    if catalog.status_code != 200 or catalog.json()['total'] != 1:
                                        raise RuntimeError('Synthetic catalog readiness check failed')
                                    break
                            except httpx.HTTPError:
                                pass
                    if process.returncode is not None:
                        raise RuntimeError('QA app failed to start. Start compose.test.yaml and check TEST_DATABASE_URL.')
                    await asyncio.sleep(.1)
                else:
                    raise TimeoutError('QA app startup timed out')
                yield url
            finally:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 10)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
