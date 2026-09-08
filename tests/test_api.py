import time
from fastapi.testclient import TestClient
from app import api

def test_cookie_reaction_validation_and_status(isolated,playing,monkeypatch):
    monkeypatch.setattr(api,'r',isolated)
    play=playing(now=time.time()-1)
    with TestClient(api.app) as client:
        assert client.post('/api/reactions',json={'play_id':play,'emoji':'🔥'}).status_code==401
        page=client.get('/')
        assert page.status_code==200 and 'httponly' in page.headers['set-cookie'].lower()
        assert client.get('/api/status').json()['play']['id']==play
        assert 'playlist' in client.get('/api/status').json()
        assert 'download_queue' in client.get('/api/status').json()
        assert client.post('/api/reactions',json={'play_id':play,'emoji':'invalid'}).status_code==422
        assert client.post('/api/reactions',json={'play_id':play,'emoji':'🔥'}).status_code==202
        assert client.post('/api/reactions',json={'play_id':play,'emoji':'❤️'}).status_code==429
        assert client.get('/api/events',headers={'Last-Event-ID':'injection'}).status_code==400
        assert client.get('/audio/track-a.mp3').status_code==404


def test_https_proxy_secure_cookie_and_existing_session_upgrade(monkeypatch):
    with TestClient(api.app) as client:
        client.get('/')
        original=client.cookies.get('radio_listener')
        monkeypatch.setenv('COOKIE_SECURE','1')
        response=client.get('/')
        assert 'secure' in response.headers['set-cookie'].lower()
        assert client.cookies.get('radio_listener')==original
    with TestClient(api.app,base_url='https://radio.example') as client:
        client.get('/')
        assert client.get('/api/session').status_code==200
