import json

import pytest
from fastapi.testclient import TestClient
from app.api import app
from app import db
from app.library import album_ref, artist_ref


def seed(metadata):
    with db.transaction() as c:
        for i in range(2):
            meta={**metadata,'id':f'search-{i}','artists':['Radiohead'],
                  'album':'Moonlight','album_id':'moon','title':'Everything In Its Right Place'}
            c.execute('INSERT INTO tracks(id,metadata,source,rights) VALUES(%s,%s,%s,%s)',
                      (meta['id'],json.dumps(meta),'private-source','private-rights'))
        demo={**meta,'id':'demo-only','demo':True,'artists':['Hidden Artist']}
        c.execute('INSERT INTO tracks(id,metadata) VALUES(%s,%s)',('demo-only',json.dumps(demo)))
    return meta


@pytest.mark.parametrize('kind,query,name',[
    ('artist','Radiohed','Radiohead'),('album','Moonligt','Moonlight'),
    ('track','Everythng','Everything In Its Right Place'),('artist','RADIO','Radiohead'),
])
def test_fuzzy_search_and_public_results(metadata,kind,query,name):
    meta=seed(metadata)
    response=TestClient(app).get('/api/library/search',params={'kind':kind,'q':query})
    assert response.status_code==200
    data=response.json()
    assert data['items'][0]['name']==name
    assert data['total']==(2 if kind=='track' else 1)
    assert 'private' not in response.text
    assert data['items'][0]['url']==('/artists/'+artist_ref('Radiohead')['id'] if kind=='artist' else '/albums/'+album_ref(meta)['id'])


@pytest.mark.parametrize('query',['','   ','%','_',"' OR 1=1 --",'Hidden Artist','zzzzzzzzz'])
def test_empty_and_unmatched_search(metadata,query):
    seed(metadata)
    assert TestClient(app).get('/api/library/search',params={'q':query}).json()=={'items':[],'total':0}


def test_validation_and_existing_pages(metadata):
    seed(metadata); client=TestClient(app)
    assert client.get('/api/library/search?kind=invalid&q=test').status_code==422
    assert client.get('/api/library/search',params={'q':'a'*201}).status_code==422
    assert client.get('/artists').status_code==200
    assert client.get('/albums').status_code==200
    assert client.get('/api/library/artists').json()['total']==1
