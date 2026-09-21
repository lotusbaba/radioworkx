"""Install the RadioWorkx index policy, data view, visualizations and dashboards."""
import json
from pathlib import Path
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
ES='http://127.0.0.1:9200';KB='http://127.0.0.1:5601'
VIEW='radioworkx-events'
objects=[{'type':'index-pattern','id':VIEW,'attributes':{'title':'radioworkx-events-*','timeFieldName':'@timestamp','name':'RadioWorkx activity'}}]


def visual(id,title,spec):
    objects.append({'type':'visualization','id':id,'attributes':{'title':title,'visState':json.dumps({'title':title,'type':'vega','params':{'spec':json.dumps(spec)}}),'uiStateJSON':'{}','description':'RadioWorkx structured activity','kibanaSavedObjectMeta':{'searchSourceJSON':'{}'}},'references':[]})
    return ('visualization',id,title)


def source(aggs,filter=None):
    return {'url':{'%context%':True,'%timefield%':'@timestamp','index':'radioworkx-events-*','body':{'size':0,'aggs':{'scope':{'filter':filter or {'match_all':{}},'aggs':aggs}}}},'format':{'property':'aggregations.scope'}}


def metric(id,title,field=None,filter=None,operation='cardinality',scale=1):
    data=source({'value':{operation:{'field':field}}} if field else {},filter)
    formula=f'datum.value.value/{scale}' if field else 'datum.doc_count'
    return visual(id,title,{'$schema':'https://vega.github.io/schema/vega-lite/v5.json','data':data,'transform':[{'calculate':formula,'as':'value'}],'mark':{'type':'text','fontSize':42},'encoding':{'text':{'field':'value','type':'quantitative','format':',.1f' if scale!=1 else ',.0f'}}})


def terms(id,title,field,filter=None):
    data=source({'items':{'terms':{'field':field,'size':15}}},filter);data['format']['property']='aggregations.scope.items.buckets'
    return visual(id,title,{'$schema':'https://vega.github.io/schema/vega-lite/v5.json','data':data,'mark':'bar','encoding':{'y':{'field':'key','type':'nominal','sort':'-x','title':None},'x':{'field':'doc_count','type':'quantitative','title':'Events'},'tooltip':[{'field':'key'},{'field':'doc_count'}]}})


def trend(id,title,filter=None):
    data=source({'items':{'date_histogram':{'field':'@timestamp','fixed_interval':'1h','min_doc_count':0}}},filter);data['format']['property']='aggregations.scope.items.buckets'
    return visual(id,title,{'$schema':'https://vega.github.io/schema/vega-lite/v5.json','data':data,'mark':{'type':'line','point':True},'encoding':{'x':{'field':'key','type':'temporal','title':'Time'},'y':{'field':'doc_count','type':'quantitative','title':'Events'},'tooltip':[{'field':'key','type':'temporal'},{'field':'doc_count'}]}})


def action(*names):return {'terms':{'event.action':list(names)}}
def both(*filters):return {'bool':{'filter':list(filters)}}

def ratio(id,title,numerator,denominator):
    data=source({'numerator':{'filter':action(numerator)},'denominator':{'filter':action(denominator)}})
    return visual(id,title,{'$schema':'https://vega.github.io/schema/vega-lite/v5.json','data':data,'transform':[{'calculate':'datum.denominator.doc_count > 0 ? datum.numerator.doc_count / datum.denominator.doc_count : 0','as':'rate'}],'mark':{'type':'text','fontSize':42},'encoding':{'text':{'field':'rate','type':'quantitative','format':'.1%'}}})


def dashboard(slug,title,panels,query=''):
    search_id='rwx-'+slug+'-timeline'
    objects.append({'type':'search','id':search_id,'attributes':{'title':title+' — action timeline','columns':['event.action','user.id','session.id','radioworkx.track_title','radioworkx.mode','event.outcome','radioworkx.error_code'],'sort':[['@timestamp','desc']],'kibanaSavedObjectMeta':{'searchSourceJSON':json.dumps({'indexRefName':'kibanaSavedObjectMeta.searchSourceJSON.index','query':{'query':query,'language':'kuery'},'filter':[]})}},'references':[{'name':'kibanaSavedObjectMeta.searchSourceJSON.index','type':'index-pattern','id':VIEW}]})
    panels=panels+[('search',search_id,'Action timeline')];refs=[];layout=[]
    for i,(type,id,label) in enumerate(panels):
        name='panel_'+str(i);refs.append({'name':name,'type':type,'id':id})
        layout.append({'panelIndex':str(i),'type':type,'panelRefName':name,'gridData':{'x':(i%2)*24,'y':(i//2)*15,'w':24,'h':15,'i':str(i)},'embeddableConfig':{'title':label}})
    objects.append({'type':'dashboard','id':'rwx-'+slug,'attributes':{'title':'RadioWorkx · '+title,'description':'Use time range and Add filter for user.id, session.id, radioworkx.track_id, artists, mode and event.action. Client activity and active sessions are estimates. Event ratios can cross reporting-window boundaries.','panelsJSON':json.dumps(layout),'optionsJSON':'{"useMargins":true,"hidePanelTitles":false}','timeRestore':False,'kibanaSavedObjectMeta':{'searchSourceJSON':'{"query":{"language":"kuery","query":""},"filter":[]}'}},'references':refs})


def build():
    browser={'term':{'radioworkx.origin':'browser'}}
    personal=both(action('playback.started'),{'term':{'radioworkx.mode':'personal'}})
    dashboard('audience','Audience',[
        metric('rwx-visitors','Estimated visitors','user.id',browser),
        metric('rwx-active','Listening sessions with heartbeat in last 90s','session.id',both(action('playback.heartbeat'),{'term':{'radioworkx.engaged':True}},{'range':{'@timestamp':{'gte':'now-90s'}}})),
        metric('rwx-minutes','Estimated listening minutes','radioworkx.listened_ms',action('playback.heartbeat'),'sum',60000),
        terms('rwx-pages','Page views','radioworkx.page',action('page.view')),
        trend('rwx-listening-trend','Listening starts over time',action('playback.started')),
        terms('rwx-devices','Devices','radioworkx.device',action('page.view')),
        terms('rwx-buffer','Playback reliability','event.action',action('playback.buffering','playback.reconnect','playback.error','playback.blocked')),
        metric('rwx-zero-search','Zero-result searches',filter=both(action('search.results'),{'term':{'radioworkx.result_count':0}}))])
    dashboard('music','Music engagement',[
        metric('rwx-first-audio','Average time to personal audio (ms)','radioworkx.latency_ms',personal,'avg'),
        metric('rwx-personal','Personal playback starts',filter=personal),metric('rwx-broadcasts','Station broadcasts',filter=action('broadcast.started')),
        terms('rwx-top-tracks','Personal plays by track','radioworkx.track_title',personal),terms('rwx-top-artists','Personal plays by artist','radioworkx.artists',personal),
        terms('rwx-reactions','Accepted reactions by genre','radioworkx.genre',action('reaction.accepted')),
        terms('rwx-albums','Album listening','radioworkx.album',personal),
        ratio('rwx-completion','Playback ends / starts (event ratio)','playback.ended','playback.started'),
        terms('rwx-emoji','Accepted emojis','radioworkx.emoji',action('reaction.accepted'))])
    dashboard('requests','Requests & downloads',[
        terms('rwx-request-stages','Request outcomes','event.action',{'prefix':{'event.action':'request.'}}),
        metric('rwx-queue-wait','Average request wait (seconds)','radioworkx.queue_delay_ms',action('request.fulfilled'),'avg',1000),
        terms('rwx-downloads','Download outcomes','event.action',{'prefix':{'event.action':'download.'}}),
        metric('rwx-download-time','Average download time (seconds)','event.duration',action('download.completed'),'avg',1000000000),
        terms('rwx-provider-failures','Download failures by provider','radioworkx.provider',action('download.failed')),
        terms('rwx-failure-codes','Acquisition error codes','radioworkx.error_code',action('download.failed')),
        terms('rwx-retries','Queue retries','radioworkx.queue',action('job.retried')),
        ratio('rwx-request-conversion','Requests fulfilled / submitted (event ratio)','request.fulfilled','request.submitted')])
    dashboard('errors','Errors & admin audit',[
        trend('rwx-error-trend','Failures over time',{'term':{'event.outcome':'failure'}}),
        terms('rwx-errors','Failure actions','event.action',{'term':{'event.outcome':'failure'}}),
        metric('rwx-latency','Average API latency (ms)','radioworkx.latency_ms',action('api.request'),'avg'),
        terms('rwx-api-status','HTTP status codes','radioworkx.status_code',action('api.request')),
        terms('rwx-admin','Admin actions','event.action',{'prefix':{'event.action':'admin.'}}),
        terms('rwx-config','Configuration observations','radioworkx.config_key',action('configuration.changed','configuration.observed')),
        metric('rwx-dropped','Reported buffer drops','radioworkx.buffer_drops',None,'sum')], 'event.outcome: failure or event.action: admin.* or event.action: configuration.*')
    path=ROOT/'infra/elk/dashboards.ndjson';path.write_text('\n'.join(json.dumps(o) for o in objects)+'\n');return path


def main():
    path=build()
    with httpx.Client(timeout=30) as client:
        for base,endpoint in [(ES,'/_cluster/health'),(KB,'/api/status')]:
            for _ in range(120):
                try:
                    response=client.get(base+endpoint)
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(2)
            else:raise RuntimeError('ELK readiness timed out: '+base)
        r=client.put(ES+'/_ilm/policy/radioworkx-30d',json={'policy':{'phases':{'hot':{'actions':{}},'delete':{'min_age':'30d','actions':{'delete':{}}}}}});r.raise_for_status()
        mapping={'dynamic_templates':[{'strings':{'match_mapping_type':'string','mapping':{'type':'keyword','ignore_above':1024}}}], 'properties':{'@timestamp':{'type':'date'},'event':{'properties':{'duration':{'type':'long'}}},'radioworkx':{'properties':{'latency_ms':{'type':'double'},'queue_delay_ms':{'type':'double'},'listened_ms':{'type':'long'},'position_seconds':{'type':'double'},'seek_from':{'type':'double'},'seek_to':{'type':'double'}}}}}
        r=client.put(ES+'/_index_template/radioworkx-events',json={'index_patterns':['radioworkx-events-*'],'priority':200,'template':{'settings':{'number_of_shards':1,'number_of_replicas':0,'index.lifecycle.name':'radioworkx-30d'},'mappings':mapping}});r.raise_for_status()
        with path.open('rb') as f:r=client.post(KB+'/api/saved_objects/_import?overwrite=true',headers={'kbn-xsrf':'true'},files={'file':('dashboards.ndjson',f,'application/ndjson')})
        r.raise_for_status();result=r.json()
        if not result.get('success'):raise RuntimeError(json.dumps(result))
        print(json.dumps({'imported':result.get('successCount'),'dashboards':[KB+'/app/dashboards#/view/rwx-'+name for name in ['audience','music','requests','errors']]}))
if __name__=='__main__':main()
