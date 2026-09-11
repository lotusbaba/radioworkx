"""Independent long-running workers. SQS messages are acknowledged after durable work."""
import fcntl
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import sys
import time
import threading
from contextlib import contextmanager
from app import db, queues
from app.config import DATA
from app.events import project
from app.service import process_reaction

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)  # Do not log short-lived media URL tokens.
log = logging.getLogger(__name__)


_last_genre_reconciliation=0

def dispatch_once():
    global _last_genre_reconciliation
    if time.time()-_last_genre_reconciliation>=60:
        from app.events import reconcile_fulfilled_genres
        reconcile_fulfilled_genres()
        _last_genre_reconciliation=time.time()
    with db.transaction() as c:
        from app.crawler import enqueue
        enqueue(c)
        from app.visuals import schedule
        schedule(c)
    with db.connect() as c:
        # Re-send until completion, so an emulator restart cannot silently lose jobs.
        rows = c.execute('SELECT * FROM outbox WHERE done IS NULL AND (sent IS NULL OR sent<?) '
                         'ORDER BY created LIMIT 100',(time.time()-1200,)).fetchall()
    for row in rows:
        queues.send(row['queue'],row['id'],json.loads(row['body']))
        with db.transaction() as c:
            c.execute('UPDATE outbox SET sent=? WHERE id=?',(time.time(),row['id']))
            if row['queue']=='download-failures':
                c.execute('UPDATE outbox SET done=? WHERE id=?',(time.time(),row['id']))
    return len(rows)


@contextmanager
def visibility_lease(url, receipt, duration):
    stop = threading.Event()
    def renew():
        while not stop.wait(duration/3):
            try:
                queues.client().change_message_visibility(QueueUrl=url,ReceiptHandle=receipt,VisibilityTimeout=duration)
            except Exception:
                log.error('Unable to renew queue visibility; idempotent recovery remains available')
    thread = threading.Thread(target=renew,daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


def consume_once(name, wait=10):
    if name=='visuals' and os.getenv('VIDEOS_ENABLED','1')!='1':
        time.sleep(min(wait,5))
        return 0  # Leave queued jobs untouched until video generation is re-enabled.
    url = queues.queue(name)
    messages = queues.client().receive_message(QueueUrl=url,MaxNumberOfMessages=1,
                                               WaitTimeSeconds=wait,MessageSystemAttributeNames=['ApproximateReceiveCount']).get('Messages',[])
    for message in messages:
        try:
            event = json.loads(message['Body'])
            with db.connect() as c:
                finished=c.execute('SELECT done FROM outbox WHERE id=?',(event['id'],)).fetchone()
            if finished and finished['done'] is not None:
                queues.client().delete_message(QueueUrl=url,ReceiptHandle=message['ReceiptHandle'])
                continue
            with visibility_lease(url,message['ReceiptHandle'],60 if name=='reactions' else 900):
                if name == 'reactions':
                    project(process_reaction(event))
                elif name == 'visuals':
                    from app.visuals import process
                    process(event)
                elif name == 'crawler':
                    from app.crawler import process
                    process(event)
                else:
                    from app.downloads import process_job
                    process_job(event)
            with db.transaction() as c:
                c.execute('UPDATE outbox SET done=? WHERE id=?',(time.time(),event['id']))
            queues.client().delete_message(QueueUrl=url,ReceiptHandle=message['ReceiptHandle'])
        except Exception as error:
            # No ack: SQS retries then moves repeatedly failing messages to the DLQ.
            log.error('%s consumer failed: %s',name,type(error).__name__)
            if int(message.get('Attributes',{}).get('ApproximateReceiveCount',0)) >= 5:
                with db.transaction() as c:
                    event = json.loads(message['Body'])
                    if event.get('kind') == 'request' and not event.get('discover_genre'):
                        c.execute("UPDATE requests SET status='failed',response=response || ' The download failed after repeated attempts; please try another track.' WHERE id=? AND status='pending'",(event.get('request_id'),))
                    c.execute('UPDATE outbox SET done=?,failed=? WHERE id=?',
                              (time.time(),type(error).__name__,json.loads(message['Body']).get('id')))
            queues.queue.cache_clear()
    return len(messages)


def consume_forever(name):
    while True:
        try:
            consume_once(name)
        except Exception as error:
            log.error('%s unavailable: %s',name,type(error).__name__)
            queues.queue.cache_clear()
            time.sleep(3)


def main():
    name = sys.argv[1]
    db.init()
    # Locks live on the shared volume, work across processes/containers, and release on crash.
    # SQLite transactions additionally serialize all capacity and history decisions.
    with (DATA / f'{name}.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        if name == 'station':
            from app.downloads import bootstrap
            from app.station import run
            bootstrap()
            run()
            return
        if name == 'visuals':
            def storage_loop():
                from app.object_store import sync_one
                while True:
                    try:sync_one()
                    except Exception as error:log.error('Object storage sync: %s',type(error).__name__)
                    time.sleep(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                pool.submit(storage_loop)
                consume_forever('visuals')
            return
        if name == 'downloads':
            with db.transaction() as c:
                c.execute("UPDATE tracks SET status='available' WHERE status='downloading'")
            # A separate priority consumer starts threshold downloads without waiting for the batch.
            queues.client()  # Initialize the boto session before starting threads.
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(consume_forever,q) for q in ('downloads','priority-downloads','request-downloads')]
                for future in futures:
                    future.result()
            return
        while True:
            try:
                if name == 'dispatch':
                    dispatch_once()
                    time.sleep(0.5)
                elif name in ('reactions','downloads','crawler'):
                    consume_once(name)
                else:
                    raise SystemExit('Expected dispatch, reactions, downloads, or station')
            except Exception as error:
                log.error('Worker unavailable: %s',type(error).__name__)
                queues.queue.cache_clear()
                time.sleep(3)

if __name__ == '__main__':
    main()
