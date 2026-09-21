"""Authenticated, read-only activity views backed by Elasticsearch."""
import os
import time
import httpx
from fastapi import APIRouter,Depends,HTTPException,Query,Response
from app.admin import authorize

router=APIRouter(dependencies=[Depends(authorize)])

@router.get('/api/admin/activity')
def activity(response:Response,action:str=Query('',max_length=100),track:str=Query('',max_length=200),user:str=Query('',max_length=64),session:str=Query('',max_length=64),page:int=Query(1,ge=1,le=100),hours:int=Query(24,ge=1,le=720)):
    response.headers['Cache-Control']='no-store'
    filters=[{'range':{'@timestamp':{'gte':int((time.time()-hours*3600)*1000)}}}]
    for field,value in [('event.action',action),('radioworkx.track_id',track),('user.id',user),('session.id',session)]:
        if value:filters.append({'term':{field:value}})
    body={'query':{'bool':{'filter':filters}},'size':50,'from':(page-1)*50,'sort':[{'@timestamp':'desc'}],'track_total_hits':True,
          'aggs':{'actions':{'terms':{'field':'event.action','size':100}},'visitors':{'cardinality':{'field':'user.id'}},'listening_ms':{'sum':{'field':'radioworkx.listened_ms'}},
                  'active':{'filter':{'bool':{'filter':[{'term':{'event.action':'playback.heartbeat'}},{'term':{'radioworkx.engaged':True}},{'range':{'@timestamp':{'gte':'now-90s'}}}]}},'aggs':{'sessions':{'cardinality':{'field':'session.id'}}}}}}
    try:
        r=httpx.post(os.getenv('ELASTICSEARCH_URL','http://elasticsearch:9200')+'/radioworkx-events-*/_search',json=body,timeout=3)
        r.raise_for_status();data=r.json()
    except Exception:raise HTTPException(503,'Activity search is temporarily unavailable. Music playback is unaffected.')
    aggs=data.get('aggregations',{});actions={b['key']:b['doc_count'] for b in aggs.get('actions',{}).get('buckets',[])}
    return {'items':[hit['_source'] for hit in data['hits']['hits']],'total':data['hits']['total']['value'],'page':page,
            'metrics':{'events':data['hits']['total']['value'],'estimated_visitors':aggs.get('visitors',{}).get('value',0),'recent_listeners':aggs.get('active',{}).get('sessions',{}).get('value',0),'listening_minutes':round(aggs.get('listening_ms',{}).get('value',0)/60000,1)},'actions':actions}
