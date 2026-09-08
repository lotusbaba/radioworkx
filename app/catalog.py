"""Operator-supplied catalog: Bandcamp metadata and authorized download sources."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from app import db


def import_catalog(path, *, overwrite=True):
    tracks = json.loads(Path(path).read_text())
    ids = set()
    for t in tracks:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}', t['id']) or t['id'] in ids:
            raise ValueError('Track IDs must be unique, safe lowercase identifiers')
        ids.add(t['id'])
        for field in ('title', 'artists', 'album', 'album_id', 'genre', 'bandcamp_url'):
            if not t.get(field):
                raise ValueError(f'{t["id"]}: missing {field}')
        if not isinstance(t['artists'], list) or any(not isinstance(a,str) or not a for a in t['artists']):
            raise ValueError('artists must be a nonempty list of canonical artist IDs/names')
        parsed = urlparse(t['bandcamp_url'])
        from app.hosts import valid_url
        valid_url(t['bandcamp_url'],'archive' if t.get('source_kind')=='archive_cc' else 'bandcamp')
        if t.get('source_url') and not t.get('rights'):
            raise ValueError('An audio source requires a rights/permission reference')
    with db.transaction() as c:
        for t in tracks:
            source, rights = t.pop('source_url', None), t.pop('rights', None)
            # Playing/downloaded identity must not change, or history could be bypassed.
            existing = c.execute('SELECT * FROM tracks WHERE id=?', (t['id'],)).fetchone()
            if existing and not overwrite:
                continue
            if existing and existing['status'] != 'available':
                if json.loads(existing['metadata']) != t:
                    raise ValueError(f'{t["id"]}: downloaded track metadata is immutable')
                continue
            c.execute('INSERT INTO tracks(id,metadata,source,rights) VALUES(?,?,?,?) '
                      'ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata,source=excluded.source,rights=excluded.rights',
                      (t['id'],json.dumps(t),source,rights))
            from app.hosts import register
            register(c,urlparse(t['bandcamp_url']).hostname,origin=t['bandcamp_url'])
    return len(tracks)
