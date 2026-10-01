(() => {
  const {el,link,followButton}=Social, $=id=>document.getElementById(id);
  const [kind,id]=location.pathname.split('/').filter(Boolean);
  let data;
  function render(){
    if(!data)return;
    $('heading').textContent=data.name;document.title=data.name+' — RadioWorkx';
    $('description').textContent=kind==='playlists'?'A playlist shared with you. Follow it to keep up with new tracks.':'Shared playlists from this listener.';
    const content=$('content');content.replaceChildren();
    if(kind==='people'){
      if(Music.user?.id!==data.id)content.append(followButton('people',data.id));
      else content.append(link('Edit your profile','/my-music'));
      const list=el('div');list.className='shared-playlist-list';
      for(const p of data.playlists){const row=el('p');row.append(link(p.name,'/playlists/'+p.id));list.append(row);}
      if(!data.playlists.length)list.append(el('p','No public playlists yet.'));content.append(list);
    }else{
      const controls=el('div');controls.className='account-buttons';controls.append(link('By '+data.owner.name,'/people/'+data.owner.id));
      if(Music.user?.id!==data.owner.id)controls.append(followButton('playlists',data.id));
      else controls.append(link('Edit in My music','/my-music'));
      const play=el('button','▶ Play all');play.disabled=!data.tracks.some(t=>t.status!=='unavailable');play.onclick=()=>PersonalMusic.playQueue(data.tracks);controls.append(play);
      const copy=el('button','Copy playlist link');copy.onclick=()=>Social.copyLink('/playlists/'+data.id);controls.append(copy);content.append(controls);
      const list=el('div');list.className='track-list';data.tracks.forEach((track,i)=>{const row=PersonalMusic.trackRow(track,i);row.querySelector('.track-action>button').onclick=()=>PersonalMusic.playQueue(data.tracks,i);list.append(row);});if(!data.tracks.length)list.append(el('p','No tracks in this playlist yet.'));content.append(list);
    }
  }
  document.addEventListener('music-changed',render);
  (async()=>{try{data=await Music.api(kind==='playlists'?'/api/shared/playlists/'+encodeURIComponent(id):'/api/people/'+encodeURIComponent(id));$('summary').textContent='';render();}catch(e){$('heading').textContent='Music unavailable';$('summary').textContent='';$('error').textContent=e.message;}})();
})();
