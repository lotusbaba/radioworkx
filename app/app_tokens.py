"""Opaque app credentials: persist only a SHA-256 digest, never the bearer token."""
import hashlib
import secrets
import time
import uuid
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app import db

bearer=HTTPBearer(auto_error=False,scheme_name='AppToken')


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue(name):
    token='rwx_'+secrets.token_urlsafe(32)
    token_id=str(uuid.uuid4());now=time.time()
    with db.transaction() as c:
        c.execute('INSERT INTO app_tokens(id,name,digest,created) VALUES(?,?,?,?)',(token_id,name,digest(token),now))
    return {'id':token_id,'name':name,'token':token,'created':now}


def authenticate(request: Request, credentials: HTTPAuthorizationCredentials|None=Depends(bearer)):
    if credentials is None or credentials.scheme.lower()!='bearer':
        raise HTTPException(401,'App bearer token required.',headers={'WWW-Authenticate':'Bearer'})
    with db.transaction() as c:
        row=c.execute('SELECT id FROM app_tokens WHERE digest=? AND revoked IS NULL',(digest(credentials.credentials),)).fetchone()
        if not row:raise HTTPException(401,'Invalid or revoked app token.',headers={'WWW-Authenticate':'Bearer'})
        c.execute('UPDATE app_tokens SET last_used=? WHERE id=?',(time.time(),row['id']))
    request.scope['app_identity']='app:'+row['id']
    return 'app:'+row['id']
