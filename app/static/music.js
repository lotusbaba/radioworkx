/* Account state and reusable save controls; never store credentials in browser storage. */
window.Music = (() => {
  let user = null, music = {likes: [], playlists: []};
  async function api(url, method='GET', body) {
    const response = await fetch(url, {method, headers: {'X-RWX-Request':'1', ...(body ? {'Content-Type':'application/json'} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
    let data; try { data = await response.json(); } catch { throw Error('Unable to connect. Please try again.'); }
    if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'Please check your details and try again.');
    return data;
  }
  async function refresh() {
    music = await api('/api/me/music');
    document.dispatchEvent(new Event('music-changed'));
    return music;
  }
  function nav() {
    for (const a of document.querySelectorAll('[data-account-link]')) a.textContent = user ? 'My music' : 'Sign in / My music';
  }
  const ready = (async () => {try {user = await api('/api/account'); await refresh();} catch {} nav();})();
  function element(tag, text) {const n=document.createElement(tag);if(text)n.textContent=text;return n;}
  function actions(track) {
    const box=element('div');box.className='save-actions';
    const like=element('button','♡ Like'), add=element('button','+ Playlist'), status=element('small');status.setAttribute('role','status');
    like.type=add.type='button';
    const update=()=>{const liked=music.likes.some(t=>t.id===track.id);like.textContent=liked?'♥ Liked':'♡ Like';like.setAttribute('aria-pressed',String(liked));};
    const signin=()=>{if(user)return true;location.href='/my-music';return false;};
    like.onclick=async()=>{if(!signin())return;like.disabled=true;try{const liked=music.likes.some(t=>t.id===track.id);await api('/api/me/likes/'+encodeURIComponent(track.id),liked?'DELETE':'PUT');await refresh();update();status.textContent=liked?'Removed from liked tracks.':'Saved to liked tracks.';}catch(e){status.textContent=e.message;}finally{like.disabled=false;}};
    add.onclick=async()=>{if(!signin())return;add.disabled=true;try{await refresh();const dialog=element('dialog');dialog.className='music-dialog';const heading=element('h2','Add to a playlist'),label=element('label','Choose a playlist'), select=element('select');select.setAttribute('aria-label','Choose a playlist');for(const p of music.playlists){const option=element('option',p.name);option.value=p.id;select.append(option);}const name=element('input');name.placeholder='Or create a new playlist';name.maxLength=80;name.setAttribute('aria-label','New playlist name');const save=element('button','Save track'),cancel=element('button','Cancel'),message=element('p');message.setAttribute('role','alert');save.onclick=async()=>{save.disabled=true;try{let id=select.value;if(name.value.trim()){const p=await api('/api/me/playlists','POST',{name:name.value});id=p.id;}if(!id)throw Error('Choose a playlist or enter a name.');await api(`/api/me/playlists/${id}/tracks/${encodeURIComponent(track.id)}`,'PUT');await refresh();status.textContent='Track saved to playlist.';dialog.close();}catch(e){message.textContent=e.message;}finally{save.disabled=false;}};cancel.onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.append(heading,label,select,name,save,cancel,message);document.body.append(dialog);dialog.showModal();}catch(e){status.textContent=e.message;}finally{add.disabled=false;}};
    box.append(like,add,status);ready.then(update);return box;
  }
  return {api,ready,refresh,actions,get user(){return user;},get data(){return music;},setUser(value){user=value;nav();}};
})();
