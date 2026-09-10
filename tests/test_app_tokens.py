from fastapi.testclient import TestClient
from app.api import app
from app import db
from app.app_tokens import digest


def test_admin_issue_once_hashed_list_and_revocation(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','test-password')
    client=TestClient(app);auth=('admin','test-password');headers={'X-Admin-Action':'tokens'}
    assert client.post('/api/admin/tokens',json={'name':'App'},headers=headers).status_code==401
    assert client.post('/api/admin/tokens',json={'name':'App'},auth=auth).status_code==403
    assert client.post('/api/admin/tokens',json={'name':'App'},auth=auth,headers={**headers,'Origin':'https://evil.example'}).status_code==403
    created=client.post('/api/admin/tokens',json={'name':'App'},auth=auth,headers=headers)
    assert created.status_code==201 and created.headers['cache-control']=='no-store'
    data=created.json();token=data['token']
    with db.connect() as c:
        row=dict(c.execute('SELECT * FROM app_tokens').fetchone())
        assert token not in str(row) and row['digest']==digest(token)
    listing=client.get('/api/admin/tokens',auth=auth)
    assert token not in listing.text and digest(token) not in listing.text
    assert listing.json()['items'][0]['token']=='••••••••'
    assert client.get('/api/catalog/genres').status_code==401
    assert client.get('/api/catalog/tracks',headers={'Authorization':'Bearer invalid'}).status_code==401
    bearer={'Authorization':'Bearer '+token}
    assert client.get('/api/catalog/genres',headers=bearer).status_code==200
    assert client.get('/api/catalog/tracks',headers=bearer).status_code==200
    with db.connect() as c:assert c.execute('SELECT last_used FROM app_tokens').fetchone()[0] is not None
    assert client.delete('/api/admin/tokens/'+data['id'],auth=auth,headers=headers).status_code==200
    assert client.get('/api/catalog/tracks',headers=bearer).status_code==401
    assert client.get('/api/admin/tokens',auth=auth).json()['items'][0]['revoked'] is not None
    assert client.get('/api/catalog/genres',auth=auth).status_code==401
    # Website browsing does not require a calling-app token.
    assert client.get('/').status_code==200


def test_token_pagination_and_blank_label(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','test-password')
    client=TestClient(app);auth=('admin','test-password');headers={'X-Admin-Action':'tokens'}
    assert client.post('/api/admin/tokens',json={'name':'  '},auth=auth,headers=headers).status_code==422
    for n in range(3):assert client.post('/api/admin/tokens',json={'name':str(n)},auth=auth,headers=headers).status_code==201
    data=client.get('/api/admin/tokens?page=2&page_size=2',auth=auth).json()
    assert data['total']==3 and data['pages']==2 and len(data['items'])==1
