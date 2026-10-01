/* Account state and reusable save controls; never store credentials in browser storage. */
window.Music = (() => {
  let user = null, music = {likes: [], playlists: []}, accountEpoch=0, refreshEpoch=0;
  async function api(url, method='GET', body) {
    const response = await fetch(url, {method, headers: {'X-RWX-Request':'1', ...(body ? {'Content-Type':'application/json'} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
    let data; try { data = await response.json(); } catch { throw Error('Unable to connect. Please try again.'); }
    if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'Please check your details and try again.');
    return data;
  }
  async function refresh() {
    const account=accountEpoch, version=++refreshEpoch;
    const [collection,social] = await Promise.all([api('/api/me/music'),api('/api/me/social')]);
    if(account!==accountEpoch||version!==refreshEpoch||!user)return music;
    music = {...collection,social};
    document.dispatchEvent(new Event('music-changed'));
    return music;
  }
  function nav() {
    for (const a of document.querySelectorAll('[data-account-link]')) a.textContent = 'My music';
    let button=document.querySelector('header [data-auth-mode]');
    if(!button){button=element('button','Sign in');button.type='button';button.dataset.authMode='login';button.className='account-signin';document.querySelector('header nav')?.append(button);}
    if(button)button.hidden=!!user;
  }
  const ready = (async () => {try {user = await api('/api/account'); await refresh();} catch {} nav();})();
  function element(tag, text) {const n=document.createElement(tag);if(text)n.textContent=text;return n;}
  let authDialog, authPromise, finishAuth, authEpoch=0;
  function setUser(value){accountEpoch++;if(user?.id!==value?.id||!value)music={likes:[],playlists:[]};user=value;nav();document.dispatchEvent(new Event('music-changed'));}
  function authenticate(mode='login') {
    if(user)return Promise.resolve(true);
    if(authDialog?.open)return authPromise;
    if(!authDialog){
      authDialog=element('dialog');authDialog.id='auth-dialog';authDialog.className='music-dialog auth-dialog';authDialog.setAttribute('aria-labelledby','auth-title');
      authDialog.innerHTML=`<button type="button" class="auth-close" aria-label="Close sign in">×</button><p class="eyebrow">YOUR RADIOWORKX COLLECTION</p><h2 id="auth-title"></h2><p>Keep your favorites and playlists across devices.</p><form id="auth-form"><label for="email">Email address</label><input id="email" type="email" autocomplete="email" maxlength="254" required><label for="password">Password · 12–128 characters</label><input id="password" type="password" minlength="12" maxlength="128" required><button id="auth-submit" type="submit"></button><p id="auth-error" role="alert"></p></form><button type="button" id="auth-switch"></button>`;
      document.body.append(authDialog);
      authDialog.querySelector('.auth-close').onclick=()=>authDialog.close();
      authDialog.addEventListener('click',e=>{if(e.target===authDialog){const r=authDialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)authDialog.close();}});
      authDialog.addEventListener('close',()=>{authEpoch++;authDialog.querySelector('#password').value='';const done=finishAuth;finishAuth=null;done?.(!!user);});
    }
    const form=authDialog.querySelector('form'), submit=authDialog.querySelector('#auth-submit'), change=authDialog.querySelector('#auth-switch'), password=authDialog.querySelector('#password'), error=authDialog.querySelector('#auth-error');
    function setMode(value){mode=value;authEpoch++;submit.disabled=false;change.disabled=false;error.textContent='';password.value='';password.autocomplete=mode==='register'?'new-password':'current-password';authDialog.querySelector('#auth-title').textContent=mode==='register'?'Make yourself at home.':'Welcome back.';submit.textContent=mode==='register'?'Create account':'Sign in';change.textContent=mode==='register'?'Already registered? Sign in':'New here? Create account';}
    setMode(mode);
    change.onclick=()=>setMode(mode==='login'?'register':'login');
    form.onsubmit=async e=>{
      e.preventDefault();if(submit.disabled)return;const epoch=authEpoch;submit.disabled=true;change.disabled=true;error.textContent='';
      try {
        const account=await api('/api/account/'+mode,'POST',{email:form.querySelector('#email').value,password:password.value});
        // A dismissed/reopened form must not receive stale messages or focus changes.
        if(epoch!==authEpoch){const current=await api('/api/account');setUser(current);await refresh();return;}
        setUser(account);password.value='';authDialog.close();
        try{await refresh();}catch{document.dispatchEvent(new Event('music-load-failed'));}
      } catch(e){if(epoch===authEpoch)error.textContent=e.message;}
      finally{if(epoch===authEpoch){submit.disabled=false;change.disabled=false;}}
    };
    authPromise=new Promise(resolve=>{finishAuth=resolve;});authDialog.showModal();form.querySelector('#email').focus();return authPromise;
  }
  document.addEventListener('click',e=>{
    const button=e.target.closest('[data-auth-mode]'), account=e.target.closest('[data-account-link]');
    if(button||account&&!user){e.preventDefault();authenticate(button?.dataset.authMode||'login');}
  });
  document.addEventListener('music-changed',()=>{
    for(const box of document.querySelectorAll('.save-actions[data-track-id]')){
      const button=box.querySelector('[data-like]');if(!button)continue;
      const liked=music.likes.some(track=>track.id===box.dataset.trackId);
      button.textContent=liked?'♥ Liked':'♡ Like';button.setAttribute('aria-pressed',String(liked));
    }
  });
  function actions(track) {
    const box=element('div');box.className='save-actions';box.dataset.trackId=track.id;
    const like=element('button','♡ Like'), add=element('button','+ Playlist'), status=element('small');status.setAttribute('role','status');
    like.type=add.type='button';like.dataset.like='';
    const update=()=>{const liked=music.likes.some(t=>t.id===track.id);like.textContent=liked?'♥ Liked':'♡ Like';like.setAttribute('aria-pressed',String(liked));};
    const signin=async()=>{await ready;return user?true:authenticate();};
    like.onclick=async()=>{if(like.disabled)return;like.disabled=true;try{if(!await signin())return;const liked=music.likes.some(t=>t.id===track.id);await api('/api/me/likes/'+encodeURIComponent(track.id),liked?'DELETE':'PUT');await refresh();update();status.textContent=liked?'Removed from liked tracks.':'Saved to liked tracks.';}catch(e){status.textContent=e.message;}finally{like.disabled=false;}};
    add.onclick=async()=>{if(add.disabled)return;add.disabled=true;try{if(!await signin())return;await refresh();const dialog=element('dialog');dialog.className='music-dialog';const heading=element('h2','Add to a playlist'),label=element('label','Choose a playlist'), select=element('select');select.setAttribute('aria-label','Choose a playlist');for(const p of music.playlists){const option=element('option',p.name);option.value=p.id;select.append(option);}const name=element('input');name.placeholder='Or create a new playlist';name.maxLength=80;name.setAttribute('aria-label','New playlist name');const save=element('button','Save track'),cancel=element('button','Cancel'),message=element('p');message.setAttribute('role','alert');save.onclick=async()=>{save.disabled=true;try{let id=select.value;if(name.value.trim()){const p=await api('/api/me/playlists','POST',{name:name.value});id=p.id;}if(!id)throw Error('Choose a playlist or enter a name.');await api(`/api/me/playlists/${id}/tracks/${encodeURIComponent(track.id)}`,'PUT');await refresh();status.textContent='Track saved to playlist.';dialog.close();}catch(e){message.textContent=e.message;}finally{save.disabled=false;}};cancel.onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.append(heading,label,select,name,save,cancel,message);document.body.append(dialog);dialog.showModal();}catch(e){status.textContent=e.message;}finally{add.disabled=false;}};
    box.append(like,add,status);ready.then(update);return box;
  }
  return {api,ready,refresh,actions,get user(){return user;},get data(){return music;},setUser,authenticate};
})();
