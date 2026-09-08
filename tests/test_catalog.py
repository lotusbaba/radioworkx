import json
from app import db
from app.catalog import import_catalog

def test_bootstrap_never_erases_authorized_source(metadata,tmp_path):
    path=tmp_path/'catalog.json'
    path.write_text(json.dumps([{**metadata,'source_url':'https://authorized.example/a.flac','rights':'Permission'}]))
    import_catalog(path)
    path.write_text(json.dumps([metadata]))
    import_catalog(path,overwrite=False)
    with db.connect() as c:
        row=c.execute('SELECT source,rights FROM tracks').fetchone()
        assert row['source']=='https://authorized.example/a.flac'
        assert row['rights']=='Permission'
