const $ = (id) => document.getElementById(id);
const audio = $('audio');
let autoplayAttempted=false, autoplayBlocked=false, audioContext, analyser, frequencies, mediaSource;
let state, tuned = false, serverOffset = 0, nextReactionAt = 0, reactionPending = false;
const emojiNames = {'❤️':'Love it','🔥':'Fire','🙌':'Hands up','😍':'Adore it','💃':'Dance','🤯':'Mind blown'};
const node = (tag, text, cls) => {const el = document.createElement(tag); if(text !== undefined) el.textContent=text; if(cls) el.className=cls; return el;};
const time = (seconds) => `${Math.floor(Math.max(0,seconds)/60)}:${String(Math.floor(Math.max(0,seconds)%60)).padStart(2,'0')}`;
const wave = document.querySelector('.wave');
for(let i=0;i<38;i++){const bar=node('i');bar.style.height=`${8+Math.abs(Math.sin(i*1.8)*Math.cos(i*.22))*30}px`;bar.style.animationDelay=`${i*.07}s`;wave.append(bar);}
function showStatus(s){
  state=s;syncVisual(s);
  if(!autoplayAttempted){autoplayAttempted=true;startPlayback(true);}
  serverOffset=s.server_time*1000-Date.now();
  $('demo-banner').hidden=!s.demo;
  const play=s.play, m=play?.metadata || s.announcement?.metadata;
  $('announcer-panel').hidden=!s.announcement;
  $('announcer-script').textContent=s.announcement?.script || '';
  $('announcer-source').hidden=!s.announcement?.source;
  if(s.announcement?.source)$('announcer-source').href=s.announcement.source;
  $('chat-engine').textContent=s.chat_engine==='rag'?'AI music chat · grounded in the station catalog':'Basic catalog search';
  $('genre').textContent=m?.genre || 'OPEN FREQUENCY';
  $('title').textContent=m?.title || 'Good things are on the way.';
  $('artist').textContent=m?.artists.join(' & ') || 'Your next discovery starts here.';
  $('album').textContent=m?.album || (s.demo?'Preparing a demo transmission':'Add authorized audio to bring the station to life.');
  $('bandcamp').hidden=!m?.bandcamp_url;
  if(m?.bandcamp_url)$('bandcamp').href=m.bandcamp_url;
  $('license').hidden=!m?.license_url;
  if(m?.license_url){$('license').href=m.license_url;$('license').textContent=`${m.license_name} · ${m.audio_changes}`;}

  $('station-status').textContent=s.station_status;
  $('listen').disabled=false;
  $('library').textContent=`LIBRARY · ${s.downloaded.toLocaleString()} / 10,000${s.library_only?' · LOCAL ONLY':''}`;
  const total=Object.values(s.reactions).reduce((a,b)=>a+b,0);
  $('reaction-total').textContent=`${total} THIS PLAY`;
  $('pulse-track-count').textContent=play?`Current track: ${total} reaction${total===1?'':'s'} across all emojis.`:'No track is playing.';
  const follow=s.reaction_followup;
  $('energy-label').textContent=total>s.threshold?(follow?.play_id===play?.id?follow.status:'Threshold reached · waiting for processing'):`${total} / ${s.threshold+1} on this track to spark a discovery`;
  $('reaction-followup').hidden=!follow;
  if(follow){
    const source=follow.source?.title || 'the previous track';
    const target=follow.target?`“${follow.target.title}” by ${follow.target.artists.join(' & ')} (${follow.target.genre})`:'a matching song';
    $('reaction-followup').textContent=`Reactions to “${source}” → ${target} · ${follow.status}`;
  }
  $('energy-fill').style.width=`${Math.min(100,total/(s.threshold+1)*100)}%`;
  $('emojis').replaceChildren(...s.emojis.map(emoji=>{
    const b=node('button');b.append(node('span',emoji),node('small',String(s.reactions[emoji]||0)));
    b.setAttribute('aria-label',`${emojiNames[emoji]}: ${s.reactions[emoji]||0} reactions on this play`);
    b.title=`${s.reactions[emoji]||0} ${emojiNames[emoji]} reactions on this play`;
    b.onclick=()=>react(emoji);return b;
  }));
  const max=s.ranking[0]?.reactions||1;
  if(!s.ranking.length)$('rankings').replaceChildren(node('p','No outstanding genre reactions. React to start the next discovery.','empty'));
  if(s.ranking.length)$('rankings').replaceChildren(...s.ranking.slice(0,5).map((r,i)=>{
    const row=node('div',undefined,'rank'), name=node('div',r.genre,'rank-name'),bar=node('div',undefined,'rank-bar'), fill=node('span');
    fill.style.width=`${r.reactions/max*100}%`;bar.append(fill);name.append(bar);
    row.append(node('span',String(i+1).padStart(2,'0'),'rank-num'),name,node('span',r.reactions,'rank-count'));return row;
  }));
  const recent=s.recent.filter(p=>!play || p.starts!==play.starts).slice(0,6);
  if(recent.length)$('recent').replaceChildren(...recent.map(p=>{
    const m=p.metadata,el=node('article',undefined,'recent-track'),details=node('div',undefined,'recent-meta');
    details.append(node('h3',m.title),node('p',m.artists.join(' & ')),node('small',m.genre));el.append(node('div','▣','mini-art'),details);return el;
  }));
  renderQueue(s);
  updateCooldown();
  tick();
}
function renderQueue(s){
  $('playlist-count').textContent=`${s.playlist.length} TRACKS`;
  $('up-next').textContent=s.up_next ? `Up next: ${s.up_next.title} · ${s.up_next.artists.join(' & ')}` : 'Next track will appear when eligible audio is ready.';
  $('request-count').textContent=`${s.request_queue.length} REQUESTS`;
  $('request-queue').replaceChildren(...s.request_queue.map(queueItem));
  for(const pager of activityPagers)if(Date.now()-pager.lastRefresh>5000)pager.refresh();
  if(!s.request_queue.length)$('request-queue').append(node('p','No listener requests yet. Make the next discovery yours.','empty'));
  $('playlist').replaceChildren(...s.playlist.map(queueItem));
  if(s.playlist.length && s.playlist.length<10)$('playlist').append(node('p',`${s.playlist.length} distinct playable tracks forecast. Repeats are not used to fill this list. Downloading or policy-deferred requests appear in the request queue until ready.`,'empty'));
  if(!s.playlist.length)$('playlist').append(node('p','No eligible tracks are ready yet. The preview updates automatically.','empty'));
  $('download-summary').textContent=s.download_summary;
  $('download-count').textContent=`${s.active_download_count} ACTIVE`;
  if(Date.now()-downloadLastRefresh>5000)refreshDownloads();
}
function updateCooldown(){
  const seconds=Math.max(0,Math.ceil((nextReactionAt-(Date.now()+serverOffset))/1000));
  document.querySelectorAll('#emojis button').forEach(b=>{b.disabled=!state?.play||reactionPending||seconds>0;});
  $('reaction-cooldown').textContent=reactionPending?'Sending reaction…':seconds>0?`React again in ${seconds}s`:`React as often as you like · ${state?.reaction_cooldown || 1} second between reactions`;
}
setInterval(updateCooldown,200);
async function react(emoji){
  if(!state?.play||reactionPending||(Date.now()+serverOffset)<nextReactionAt)return;
  reactionPending=true;updateCooldown();$('reaction-error').textContent='';
  try{
    const response=await fetch('/api/reactions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_id:crypto.randomUUID(),play_id:state.play.id,emoji})});
    const body=await response.json();
    if(!response.ok){
      if(response.status===429)nextReactionAt=Date.now()+serverOffset+Number(response.headers.get('Retry-After')||1)*1000;
      throw new Error(typeof body.detail==='string'?body.detail:'That reaction could not be sent.');
    }
    serverOffset=body.server_time*1000-Date.now();nextReactionAt=body.next_reaction_at*1000;
  }catch(e){$('reaction-error').textContent=e.message;}
  finally{reactionPending=false;updateCooldown();}
}
async function syncSession(){
  try{const response=await fetch('/api/session');if(response.ok){const s=await response.json();serverOffset=s.server_time*1000-Date.now();nextReactionAt=s.next_reaction_at*1000;updateCooldown();}}catch{}
}
syncSession();
window.addEventListener('focus',syncSession);
function reactionEvent(e){
  const row=node('div',undefined,'feed-item');row.append(node('span',e.emoji),node('small',`Someone is feeling ${e.genre}`));
  if($('feed').querySelector('.empty'))$('feed').replaceChildren();
  $('feed').prepend(row);while($('feed').children.length>4)$('feed').lastChild.remove();
  const floater=node('span',e.emoji,'floater');floater.style.right=`${Math.random()*100}px`;$('floating-reactions').append(floater);setTimeout(()=>floater.remove(),3100);
}
function tick(){
  if(autoplayBlocked)$('audio-status').textContent='Tap anywhere to enable sound — your browser blocked autoplay.';
  if(state?.announcement){
    if(!autoplayBlocked)$('audio-status').textContent='AI announcer is introducing the next track. Music starts after the introduction.';
    $('elapsed').textContent='INTRO';$('duration').textContent='—:—';$('progress').style.width='0%';return;
  }
  if(state && !state.play){
    const remaining=state.next_airtime?Math.max(0,Math.ceil(state.next_airtime-(Date.now()+serverOffset)/1000)):null;
    const waiting=remaining===0?'Eligible music is ready; waiting for the station to start. ':remaining!==null?`Next eligible music in ${time(remaining)}. `:`${state.station_status}. `;
    if(!autoplayBlocked)$('audio-status').textContent=waiting+(tuned?'You’re tuned in; audio will start automatically.':'Tune in now to join when playback resumes.');
  }
  if(!state?.play){$('elapsed').textContent='0:00';$('duration').textContent='—:—';$('progress').style.width='0%';return;}
  const p=state.play,elapsed=Math.min(p.ends-p.starts,(Date.now()+serverOffset)/1000-p.starts);
  $('elapsed').textContent=time(elapsed);$('duration').textContent=time(p.ends-p.starts);$('progress').style.width=`${Math.max(0,elapsed/(p.ends-p.starts)*100)}%`;
}
setInterval(tick,1000);
function stop(){tuned=false;audio.pause();audio.removeAttribute('src');audio.load();document.body.classList.remove('playing');$('play-icon').textContent='▶';$('play-label').textContent='Tune in';$('audio-status').textContent='Live together, wherever you are.';}
async function startPlayback(automatic=false){
  if(tuned)return;
  autoplayBlocked=false;
  tuned=true;$('play-icon').textContent='■';$('play-label').textContent='Tune out';$('audio-status').textContent='Connecting to the live frequency…';
  audio.src='/api/live';audio.volume=Number($('volume').value);
  // Create/resume Web Audio in a user gesture; do not route successful autoplay into a suspended context.
  if(!automatic)enableAnalyser();
  try{await audio.play();if(automatic && navigator.userActivation?.hasBeenActive)enableAnalyser();}
  catch(e){if(tuned){stop();autoplayBlocked=e.name==='NotAllowedError';$('audio-status').textContent=autoplayBlocked?'Tap anywhere to enable sound — your browser blocked autoplay.':'Playback could not start. Try tuning in again.';}}
}
function enableAnalyser(){
  try{
    if(!audioContext)audioContext=new (window.AudioContext||window.webkitAudioContext)();
    const connect=()=>{if(mediaSource||audioContext.state!=='running')return;analyser=audioContext.createAnalyser();analyser.fftSize=256;analyser.smoothingTimeConstant=.78;frequencies=new Uint8Array(analyser.frequencyBinCount);mediaSource=audioContext.createMediaElementSource(audio);mediaSource.connect(analyser);analyser.connect(audioContext.destination);};
    audioContext.resume().then(connect).catch(()=>{});connect();
  }catch{}
}
$('listen').onclick=()=>{if(tuned){stop();return;}startPlayback();};
function unlockSound(event){
  if(event.target.closest?.('#listen'))return;
  if(autoplayBlocked)startPlayback(false);else if(tuned)enableAnalyser();
}
document.addEventListener('click',unlockSound,{capture:true});
document.addEventListener('keydown',event=>{if(!event.ctrlKey&&!event.metaKey&&!event.altKey)unlockSound(event);});
const reduceMotion=matchMedia('(prefers-reduced-motion: reduce)');
function drawWave(){
  if(analyser && audioContext.state==='running')analyser.getByteFrequencyData(frequencies);
  [...wave.children].forEach((bar,i)=>{const level=tuned && !audio.paused && !reduceMotion.matches && frequencies?frequencies[Math.floor(i*(frequencies.length/2)/wave.children.length)]/255:0;bar.style.height=`${4+level*38}px`;});
  requestAnimationFrame(drawWave);
}
requestAnimationFrame(drawWave);
let visualURL=null, motionPaused=reduceMotion.matches, videoFailed=false;
function syncVisual(s){
  const visual=s.visual, video=$('track-video'), art=$('track-artwork');
  const url=visual?.video_url || null;
  if(url!==visualURL){videoFailed=false;video.pause();video.removeAttribute('src');video.load();visualURL=url;if(url){video.src=url;video.muted=true;video.loop=true;video.load();}}
  if(visual?.artwork_url){if(art.getAttribute('src')!==visual.artwork_url)art.src=visual.artwork_url;art.hidden=false;}else{art.hidden=true;art.removeAttribute('src');}
  video.hidden=!url||videoFailed;document.querySelector('.art').classList.toggle('has-media',!!url||!!visual?.artwork_url);
  $('visual-label').hidden=!url;$('motion-toggle').hidden=!url;
  const labels={queued:'Artwork video is queued. Music plays while it is prepared.',submitting:'Preparing the artwork video…',generating:'Generating the artwork video… It will appear here when ready.',failed:'Video generation was unavailable for this artwork. Showing the cover instead.',unavailable:'No usable artwork video is available for this track.',submission_unknown:'Artwork video is awaiting review.'};
  $('visual-status').textContent=videoFailed?'The artwork video could not load. Tap Retry video.':url?(motionPaused?'Artwork motion is paused. Tap Play motion to watch.':'10-second artwork video · loops throughout the track.'):labels[visual?.status]||(s.play||s.announcement?'Artwork video has not been prepared yet.':'');
  $('motion-toggle').textContent=videoFailed?'Retry video':motionPaused?'Play motion':'Pause motion';
  $('motion-toggle').setAttribute('aria-label',videoFailed?'Retry artwork video':motionPaused?'Play artwork motion':'Pause artwork motion');
  if(url && !motionPaused && !videoFailed && !document.hidden)video.play().catch(error=>{if(error.name==='NotAllowedError'&&visualURL===url){motionPaused=true;if(state)syncVisual(state);}});else video.pause();
}
$('motion-toggle').onclick=()=>{if(videoFailed){videoFailed=false;motionPaused=false;$('track-video').load();}else motionPaused=!motionPaused;if(state)syncVisual(state);};
$('track-video').addEventListener('error',()=>{if(visualURL){videoFailed=true;if(state)syncVisual(state);}});
reduceMotion.addEventListener('change',()=>{motionPaused=reduceMotion.matches;if(state)syncVisual(state);});
document.addEventListener('visibilitychange',()=>{if(state)syncVisual(state);});
audio.onplaying=()=>{enableAnalyser();document.body.classList.add('playing');$('audio-status').textContent='You’re on the live frequency.';};
audio.onwaiting=()=>{if(tuned)$('audio-status').textContent='Waiting for the live signal…';};
audio.onerror=()=>{if(tuned){stop();$('audio-status').textContent='Signal interrupted. Tune in to reconnect.';}};
$('volume').oninput=(e)=>{audio.volume=Number(e.target.value);};
const events=new EventSource('/api/events');
events.addEventListener('snapshot',e=>{try{showStatus(JSON.parse(e.data));}catch(err){console.error(err);}});
events.addEventListener('reaction',e=>reactionEvent(JSON.parse(e.data)));
events.onopen=()=>{$('connection').textContent='Connected live';$('connection-dot').classList.add('connected');};
events.onerror=()=>{$('connection').textContent='Reconnecting';$('connection-dot').classList.remove('connected');};
fetch('/api/status').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(showStatus).catch(()=>{$('station-status').textContent='Station is reconnecting';});

let chatBusy=false;
function renderChat(messages){
  if(!messages.length)return;
  $('chat-messages').replaceChildren(...messages.flatMap(m=>{
    const reply=node('div',undefined,'chat-reply');
    reply.append(node('p',m.response),node('small',m.engine==='rag'?'Catalog-grounded AI':'Basic catalog search'));
    for(const source of m.sources||[]){
      try{
        const url=new URL(source.bandcamp_url);
        if(url.protocol!=='https:' || !(url.hostname.endsWith('.bandcamp.com') || url.hostname==='archive.org'))continue;
        const link=node('a',source.title);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';
        reply.append(document.createTextNode(' · '),link);
      }catch{}
    }
    return [node('p',m.query,'chat-question'),reply];
  }));
  const last=messages[messages.length-1];
  if(last.status==='awaiting_confirmation' && last.suggestions?.length){
    const choices=node('div',undefined,'chat-choices');
    for(const genre of last.suggestions){
      const button=node('button',genre);button.type='button';
      button.onclick=()=>{if(chatBusy)return;$('request-query').value=genre;$('request-form').requestSubmit();};
      choices.append(button);
    }
    $('chat-messages').append(choices);
  }
  $('chat-messages').scrollTop=$('chat-messages').scrollHeight;
}
async function syncChat(){try{const r=await fetch('/api/requests');if(r.ok)renderChat((await r.json()).messages);}catch{}}
syncChat();window.addEventListener('focus',syncChat);
$('request-form').onsubmit=async e=>{
  e.preventDefault();if(chatBusy)return;
  const query=$('request-query').value.trim();if(!query)return;
  const thinking=node('p','Let me find that for you…','chat-reply');
  $('chat-messages').append(node('p',query,'chat-question'),thinking);
  $('chat-messages').scrollTop=$('chat-messages').scrollHeight;
  chatBusy=true;$('request-send').disabled=true;$('request-send').textContent='Searching…';$('request-error').textContent='';
  try{
    const r=await fetch('/api/requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,mode:'auto',request_id:crypto.randomUUID()})});
    const body=await r.json();if(!r.ok)throw new Error(typeof body.detail==='string'?body.detail:'Please enter a valid request.');
    $('request-query').value='';await syncChat();
    const status=await fetch('/api/status');if(status.ok)showStatus(await status.json());
  }catch(error){$('request-error').textContent=error.message;}
  finally{thinking.remove();chatBusy=false;$('request-send').disabled=false;$('request-send').textContent='Hit the line ↗';}
};


let statsPeriod='7d', statsRevision=0;
async function refreshStats(){
  const revision=++statsRevision;
  try{
    const response=await fetch(`/api/stats?period=${statsPeriod}`);
    if(!response.ok)throw new Error('Stats unavailable');
    const stats=await response.json();if(revision!==statsRevision)return;
    $('stats-metrics').replaceChildren(...[['Downloaded tracks',stats.library],['Likes',stats.likes],['Downloads',stats.downloads],['Track requests',stats.requests]].map(([label,value])=>{
      const card=node('div',undefined,'stat-metric');card.append(node('strong',value.toLocaleString()),node('span',label));return card;
    }));
    const max=Math.max(1,...stats.genres.map(g=>g.likes));
    $('stats-genres').replaceChildren(...stats.genres.map(g=>{
      const row=node('div',undefined,'stat-genre');
      const label=node('div',undefined,'stat-genre-label');label.append(node('span',g.genre),node('strong',`${g.likes.toLocaleString()} likes`));
      const track=node('div',undefined,'stat-bar');track.setAttribute('aria-hidden','true');const fill=node('i');fill.style.width=`${g.likes/max*100}%`;track.append(fill);row.append(label,track);return row;
    }));
    if(!stats.genres.length)$('stats-genres').append(node('p','No likes in this period yet. Send an emoji to start the chart.','empty'));
    $('stats-status').textContent=`${{ '24h':'Last 24 hours','7d':'Last 7 days',all:'All time'}[stats.period]} · Updated ${new Date(stats.updated_at*1000).toLocaleTimeString()} · Refreshes every 30 seconds`;
  }catch{if(revision===statsRevision)$('stats-status').textContent='Stats are temporarily unavailable. Retrying in 30 seconds.';}
}
document.querySelectorAll('[data-period]').forEach(button=>button.onclick=()=>{
  statsPeriod=button.dataset.period;
  document.querySelectorAll('[data-period]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  $('stats-status').textContent='Updating stats…';refreshStats();
});
refreshStats();setInterval(()=>{if(!document.hidden)refreshStats();},30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshStats();});

function queueItem(entry,i){
    const row=node('div',undefined,'queue-track'),m=entry.metadata;
    const details=node('div',undefined,'queue-details');
    details.append(node('strong',m?.title || entry.label || (entry.kind==='boost'?'Reaction-inspired selection':entry.kind==='request'?'Listener request':entry.kind==='recovery'?'Finding eligible new music':'Automatic ten-track batch')),node('span',m?`${m.artists.join(' & ')} · ${m.genre}`:'The downloader is preparing this request.'));
    if(entry.updated_at)details.append(node('small',new Date(entry.updated_at*1000).toLocaleString()));
    if(entry.selection)details.append(node('small',entry.selection));
    if(entry.requested_by)details.append(node('small',`${entry.requested_by} · ${new Date(entry.requested_at*1000).toLocaleString()}`));
    if(entry.kind)details.append(node('small',entry.kind==='boost'?'Reaction threshold':entry.kind==='request'?'Listener request':entry.kind==='recovery'?'No eligible music · recovery':'Automatic refill'));
    row.append(node('span',String(i+1).padStart(2,'0'),'queue-number'),details,node('span',entry.status,'queue-status'));
    row.classList.toggle('is-current',entry.status==='Now playing'||entry.status==='Downloading');
    if(entry.duration)row.append(node('span',time(entry.duration),'queue-duration'));
    return row;
}

let downloadPage=1, downloadPages=1, downloadLastRefresh=0, downloadRevision=0;
async function refreshDownloads(){
  downloadLastRefresh=Date.now();const revision=++downloadRevision;
  $('downloads-previous').disabled=true;$('downloads-next').disabled=true;
  try{
    const response=await fetch(`/api/downloads?page=${downloadPage}&page_size=10`);
    if(!response.ok)throw new Error();
    const data=await response.json();if(revision!==downloadRevision)return;
    downloadPage=data.page;downloadPages=data.pages;
    $('download-queue').replaceChildren(...data.items.map((entry,i)=>queueItem(entry,(data.page-1)*data.page_size+i)));
    if(!data.items.length)$('download-queue').append(node('p','No downloads yet. New activity will appear here.','empty'));
    $('downloads-page').textContent=`Page ${data.page} of ${data.pages} · ${data.total.toLocaleString()} entries · Latest first`;
  }catch{if(revision===downloadRevision)$('downloads-page').textContent='Could not refresh downloads. Retrying automatically.';}
  finally{if(revision===downloadRevision){$('downloads-previous').disabled=downloadPage<=1;$('downloads-next').disabled=downloadPage>=downloadPages;}}
}
$('downloads-previous').onclick=()=>{if(downloadPage>1){downloadPage--;refreshDownloads();}};
$('downloads-next').onclick=()=>{if(downloadPage<downloadPages){downloadPage++;refreshDownloads();}};


function activityPager(prefix,container,endpoint,empty){
  const pager={page:1,pages:1,lastRefresh:0,revision:0};
  pager.refresh=async()=>{
    pager.lastRefresh=Date.now();const revision=++pager.revision;
    $(prefix+'-previous').disabled=true;$(prefix+'-next').disabled=true;
    try{
      const response=await fetch(`${endpoint}${endpoint.includes('?')?'&':'?'}page=${pager.page}&page_size=10`);
      if(!response.ok)throw new Error();
      const data=await response.json();if(revision!==pager.revision)return;
      pager.page=data.page;pager.pages=data.pages;
      $(container).replaceChildren(...data.items.map((entry,i)=>queueItem(entry,(data.page-1)*data.page_size+i)));
      if(!data.items.length)$(container).append(node('p',empty,'empty'));
      $(prefix+'-page').textContent=`Page ${data.page} of ${data.pages} · ${data.total.toLocaleString()} entries · Latest first`;
    }catch{if(revision===pager.revision)$(prefix+'-page').textContent='Could not refresh activity. Retrying automatically.';}
    finally{if(revision===pager.revision){$(prefix+'-previous').disabled=pager.page<=1;$(prefix+'-next').disabled=pager.page>=pager.pages;}}
  };
  $(prefix+'-previous').onclick=()=>{if(pager.page>1){pager.page--;pager.refresh();}};
  $(prefix+'-next').onclick=()=>{if(pager.page<pager.pages){pager.page++;pager.refresh();}};
  pager.refresh();return pager;
}
const activityPagers=[
  activityPager('community','community-requests','/api/community-requests','No music requests yet.'),
  activityPager('automatic','download-activity','/api/downloads?scope=automatic','No completed automatic acquisition activity yet.')
];
