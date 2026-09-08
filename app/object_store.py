"""LocalStack S3 objects with durable local playback/cache copies."""
import hashlib
import os
import time
from pathlib import Path
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from app import db
from app.config import ENDPOINT


def client():
    return boto3.client('s3',endpoint_url=ENDPOINT,region_name=os.getenv('AWS_DEFAULT_REGION','us-east-1'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID','test'),aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY','test'),
        config=Config(signature_version='s3v4',s3={'addressing_style':'path'},connect_timeout=5,read_timeout=30,retries={'max_attempts':2}))


def bucket():return os.getenv('MEDIA_BUCKET','radioworkx-media')


def key(track_id,kind):
    suffix={'audio':'mp3','artwork':'jpg','video':'mp4'}[kind]
    return f'{kind}/{hashlib.sha256(track_id.encode()).hexdigest()}.{suffix}'


def put(track_id,kind,path):
    path=Path(path)
    mime={'audio':'audio/mpeg','artwork':'image/jpeg','video':'video/mp4'}[kind]
    object_key=key(track_id,kind)
    with db.transaction() as c:
        c.execute('INSERT INTO media_objects(object_key,track_id,kind,path,mime) VALUES(?,?,?,?,?) ON CONFLICT(object_key) DO UPDATE SET path=excluded.path',
                  (object_key,track_id,kind,str(path),mime))
    upload(object_key)
    return object_key


def upload(object_key):
    with db.connect() as c:row=c.execute('SELECT * FROM media_objects WHERE object_key=?',(object_key,)).fetchone()
    s3=client()
    try:s3.head_bucket(Bucket=bucket())
    except ClientError as error:
        if error.response['Error']['Code'] not in {'404','NoSuchBucket','NotFound'}:raise
        s3.create_bucket(Bucket=bucket())
    try:s3.head_object(Bucket=bucket(),Key=object_key)
    except ClientError as error:
        if error.response['Error']['Code'] not in {'404','NoSuchKey','NotFound'}:raise
        s3.upload_file(row['path'],bucket(),object_key,ExtraArgs={'ContentType':row['mime']})
    with db.transaction() as c:c.execute('UPDATE media_objects SET checked=? WHERE object_key=?',(time.time(),object_key))


def sync_one():
    # Backfill existing music incrementally, independent of on-air transmission.
    with db.connect() as c:
        track=c.execute("SELECT id,path FROM tracks WHERE status='ready' AND path IS NOT NULL AND id NOT IN (SELECT track_id FROM media_objects WHERE kind='audio') LIMIT 1").fetchone()
        row=c.execute('SELECT object_key FROM media_objects WHERE checked IS NULL OR checked<? ORDER BY COALESCE(checked,0) LIMIT 1',(time.time()-3600,)).fetchone()
    if track and Path(track['path']).exists():put(track['id'],'audio',track['path'])
    elif row:upload(row['object_key'])  # Restore objects after an emulator reset from durable copies.


def local_path(row):
    path=Path(row['path'])
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix(path.suffix+'.restore')
        client().download_file(bucket(),row['object_key'],str(temporary))
        temporary.replace(path)
    return path
