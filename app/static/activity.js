/* Product telemetry is best-effort and never blocks controls or audio. */
(()=>{
  let sid;try{sid=sessionStorage.getItem('rwx-session')||crypto.randomUUID();sessionStorage.setItem('rwx-session',sid);}catch{sid=crypto.randomUUID();}
  const segments=location.pathname.split('/').filter(Boolean),page=segments[0]==='artists'?(segments[1]?'artist':'artists'):segments[0]==='albums'?(segments[1]?'album':'albums'):'station';
  let pending=[],sending=false,trackId=null,mode=page==='station'?'live':'personal',playbackId=crypto.randomUUID(),started=false,active=false,listened=0,lastClock=performance.now(),previousPosition=0,buffered=false,clickedAt=0;
  const audio=document.querySelector('audio');
  function emit(action,fields={}){try{if(pending.length>=100)pending.shift();pending.push({id:crypto.randomUUID(),timestamp:Date.now()/1000,action,page,entity_id:segments[1]||undefined,...fields});}catch{}}
  function context(){return {track_id:trackId||undefined,mode,playback_id:playbackId,position_seconds:audio&&Number.isFinite(audio.currentTime)?audio.currentTime:0};}
  function heartbeat(){if(!started)return;emit('playback.heartbeat',{...context(),listened_ms:Math.min(35000,Math.round(listened)),engaged:active&&!audio.paused&&!audio.ended});listened=0;}
  async function flush(){if(sending||!pending.length)return;sending=true;const batch=pending.splice(0,30);try{const response=await fetch('/api/activity',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid,events:batch}),keepalive:true});if(response.status>=500)pending=[...batch,...pending].slice(0,100);}catch{pending=[...batch,...pending].slice(0,100);}finally{sending=false;}}
  function select(id,newMode){if(id===trackId&&newMode===mode)return;heartbeat();trackId=id;mode=newMode;playbackId=crypto.randomUUID();started=false;listened=0;if(newMode==='live'&&audio&&!audio.paused&&active){started=true;emit('playback.started',context());}}
  window.Activity={emit,select,clicked(id,newMode){clickedAt=performance.now();select(id,newMode);emit('play.clicked',context());},error(code){emit('preparation.failed',{...context(),error_code:code});},ready(){emit('preparation.ready',context());}};
  emit('page.view');
  window.addEventListener('error',()=>emit('browser.error',{error_code:'javascript'}));
  window.addEventListener('unhandledrejection',()=>emit('browser.error',{error_code:'promise'}));
  if(audio){
    audio.addEventListener('playing',()=>{active=true;lastClock=performance.now();emit(started?'playback.resumed':'playback.started',{...context(),latency_ms:!started&&clickedAt?Math.min(600000,performance.now()-clickedAt):undefined});started=true;buffered=false;});
    audio.addEventListener('pause',()=>{heartbeat();active=false;if(started&&!audio.ended)emit('playback.paused',context());});
    for(const type of ['waiting','stalled'])audio.addEventListener(type,()=>{if(started&&!buffered){heartbeat();emit('playback.buffering',context());}active=false;buffered=true;});
    audio.addEventListener('seeking',()=>{heartbeat();active=false;emit('playback.seek',{...context(),seek_from:previousPosition,seek_to:audio.currentTime});});
    audio.addEventListener('seeked',()=>{active=!audio.paused;lastClock=performance.now();});
    audio.addEventListener('ended',()=>{heartbeat();active=false;emit('playback.ended',context());started=false;});
    audio.addEventListener('error',()=>{heartbeat();active=false;emit('playback.error',{...context(),error_code:'media'});});
    audio.addEventListener('emptied',()=>{if(started){heartbeat();emit('playback.stopped',context());}started=false;active=false;});
    setInterval(()=>{const now=performance.now();if(active&&!audio.paused&&!audio.ended&&!audio.seeking&&audio.readyState>=3)listened+=Math.min(5000,now-lastClock);lastClock=now;previousPosition=audio.currentTime||0;},1000);
    setInterval(heartbeat,30000);
  }
  setInterval(flush,5000);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){heartbeat();flush();}});
  window.addEventListener('pagehide',()=>{heartbeat();if(started)emit('playback.stopped',context());if(pending.length)navigator.sendBeacon('/api/activity',new Blob([JSON.stringify({session_id:sid,events:pending.slice(0,50)})],{type:'application/json'}));});
})();
