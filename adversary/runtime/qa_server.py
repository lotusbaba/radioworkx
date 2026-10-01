"""Test-only app wiring. Never imported by the production application."""
import argparse
import json
import os
from pathlib import Path
import socket
import wave

from .qa import FIXTURE_VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ready', required=True)
    args = parser.parse_args()
    from app.testing import database
    with database():
        import fakeredis
        import uvicorn
        from app import db, events, api
        from fastapi import Request
        from fastapi.responses import FileResponse, JSONResponse, Response
        db.init()
        events.r = api.r = fakeredis.FakeRedis(decode_responses=True)
        audio = Path(os.environ['DATA_DIR']) / 'qa.wav'
        with wave.open(str(audio), 'wb') as recording:
            recording.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            recording.writeframes(bytes(60 * 22050 * 2))
        metadata = dict(id='qa-track', title='QA Track', artists=['QA Artist'], demo=True,
                        genre='jazz', album='QA Album', album_id='qa-album',
                        compilation_id=None, bandcamp_url='https://example.invalid/qa')
        with db.transaction() as c:
            c.execute('INSERT INTO tracks(id,metadata,status,source,rights,path,duration) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                      ('qa-track', json.dumps(metadata), 'ready', 'https://example.invalid/qa',
                       'synthetic fixture', str(audio), 60))
        snapshot = api.status()

        @api.app.middleware('http')
        async def synthetic_services(request: Request, call_next):
            path = request.url.path
            if path == '/__qa/manifest':
                return JSONResponse({'fixture': FIXTURE_VERSION})
            if path == '/api/status':
                return JSONResponse(snapshot)
            if path == '/api/events':
                return Response('event: status\ndata: ' + json.dumps(snapshot) + '\n\n', media_type='text/event-stream')
            if path.startswith('/api/live'):
                return FileResponse(audio, media_type='audio/wav')
            # The API can enqueue requests in its disposable DB, but no workers,
            # cloud providers, discovery, production admin or announcers run.
            if path.startswith(('/admin', '/api/admin')):
                return Response(status_code=403)
            return await call_next(request)

        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen(128)
            url = f'http://127.0.0.1:{sock.getsockname()[1]}'
            Path(args.ready).write_text(json.dumps({'url': url}))
            uvicorn.Server(uvicorn.Config(api.app, log_level='error', lifespan='off')).run(sockets=[sock])


if __name__ == '__main__':
    main()
