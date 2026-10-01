(() => {
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const {trackRow,playQueue}=PersonalMusic;
let selectedPlaylist=null;
function report(error){$('error').textContent=error.message;}
function renderAccount(){
  const signed=!!Music.user;$('auth-panel').hidden=signed;$('account-panel').hidden=!signed;$('summary').textContent='';
  if(!signed){$('content').replaceChildren();PersonalMusic.stop();return;}
  $('account-email').textContent='Signed in as '+Music.user.email;
  const data=Music.data;
  const tabs=el('div',undefined,'related-links');
  const liked=el('button',`Liked tracks (${data.likes.length})`);liked.onclick=()=>{selectedPlaylist=null;renderAccount();};tabs.append(liked);
  for(const p of [...data.playlists,...(data.social?.playlists||[])]){const b=el('button',`${p.owner?"Following · ":""}${p.name} (${p.tracks.length})`);b.onclick=()=>{selectedPlaylist=p.id;renderAccount();};tabs.append(b);}
  let playlist=[...data.playlists,...(data.social?.playlists||[])].find(p=>p.id===selectedPlaylist);if(!playlist)selectedPlaylist=null;
  const tracks=playlist?playlist.tracks:data.likes;
  const title=el('h2',playlist?playlist.name:'Liked tracks'), controls=el('div',undefined,'account-buttons');
  const playAll=el('button','▶ Play all');playAll.disabled=!tracks.some(t=>t.status!=='unavailable');playAll.onclick=()=>playQueue(tracks.filter(t=>t.status!=='unavailable'));controls.append(playAll);
  if(playlist&&!playlist.owner){
    const rename=el('form',undefined,'rename-playlist'), name=el('input');name.value=playlist.name;name.maxLength=80;name.required=true;name.setAttribute('aria-label','Playlist name');const save=el('button','Rename');rename.append(name,save);rename.onsubmit=async e=>{e.preventDefault();try{await Music.api('/api/me/playlists/'+playlist.id,'PATCH',{name:name.value});await Music.refresh();}catch(e){report(e);}};
    const remove=el('button','Delete playlist');remove.onclick=async()=>{if(!confirm(`Delete “${playlist.name}”?`))return;try{await Music.api('/api/me/playlists/'+playlist.id,'DELETE');selectedPlaylist=null;await Music.refresh();}catch(e){report(e);}};controls.append(rename,remove);
  }
  if(playlist?.owner){controls.append(Social.link('By '+playlist.owner.name,'/people/'+playlist.owner.id),Social.followButton('playlists',playlist.id));}
  const list=el('div',undefined,'track-list');tracks.forEach((track,i)=>{const row=trackRow(track,i);row.querySelector('.track-action>button').onclick=()=>playQueue(tracks,i);if(playlist&&!playlist.owner){const remove=el('button','Remove');remove.onclick=async()=>{try{await Music.api(`/api/me/playlists/${playlist.id}/tracks/${encodeURIComponent(track.id)}`,'DELETE');await Music.refresh();}catch(e){report(e);}};row.querySelector('.track-action').append(remove);}list.append(row);});
  if(!tracks.length)list.append(el('p',playlist?'This playlist is waiting for its first track. Explore an artist or album to add music.':'Your favorites will appear here. Like a track to save it for later.'));
  $('content').replaceChildren(tabs,title,controls,...(playlist&&!playlist.owner?[Social.shareControls(playlist)]:[]),list,Social.profileControls());
}
$('logout').onclick=async()=>{try{await Music.api('/api/account/logout','POST');Music.setUser(null);$('stop').click();renderAccount();}catch(e){report(e);}};
$('create-playlist').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const p=await Music.api('/api/me/playlists','POST',{name:$('playlist-name').value});selectedPlaylist=p.id;$('playlist-name').value='';await Music.refresh();}catch(e){report(e);}finally{button.disabled=false;}};
document.addEventListener('music-load-failed',()=>report(Error('Signed in, but your music could not be loaded. Reload to try again.')));
document.addEventListener('music-changed',renderAccount);Music.ready.then(renderAccount);

})();
