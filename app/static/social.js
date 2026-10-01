/* Shared playlists remain the owner's collection; following never grants editing rights. */
window.Social = (() => {
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const link=(text,path)=>{const n=el('a',text);n.href=path;return n;};
  function followButton(kind,id){
    const following=()=>!!Music.data.social?.[kind]?.some(p=>p.id===id);
    const button=el('button',following()?'Unfollow':kind==='people'?'Follow listener':'Follow playlist');
    button.type='button';button.setAttribute('aria-pressed',String(following()));
    button.onclick=async()=>{button.disabled=true;try{await Music.ready;if(!Music.user&&!await Music.authenticate())return;const current=await Music.api('/api/me/social');await Music.api(`/api/me/following/${kind}/${id}`,current[kind].some(p=>p.id===id)?'DELETE':'PUT');await Music.refresh();}catch(e){document.getElementById('error').textContent=e.message;}finally{button.disabled=false;}};
    return button;
  }
  function shareControls(playlist){
    const box=el('div');box.className='share-controls';
    const shared=Music.data.social?.shared.includes(playlist.id);
    const status=el('p',shared?'Public · visible on your profile and to anyone with the link.':'Private · only you can see this playlist. Sharing makes it public on your profile.');box.append(status);
    const button=el('button',shared?'Copy playlist link':'Share playlist');button.type='button';
    button.onclick=async()=>{button.disabled=true;try{if(!shared){await Music.api(`/api/me/playlists/${playlist.id}/sharing`,'PUT');await Music.refresh();}await copyLink('/playlists/'+playlist.id);}catch(e){document.getElementById('error').textContent=e.message;}finally{button.disabled=false;}};box.append(button);
    if(shared){box.append(link('Open shared playlist ↗','/playlists/'+playlist.id));const revoke=el('button','Make private');revoke.type='button';revoke.onclick=async()=>{if(!confirm('Make this playlist private? Its link will stop working and playlist followers will be removed.'))return;revoke.disabled=true;try{await Music.api(`/api/me/playlists/${playlist.id}/sharing`,'DELETE');await Music.refresh();}catch(e){document.getElementById('error').textContent=e.message;}finally{revoke.disabled=false;}};box.append(revoke);}
    return box;
  }
  let copyPending=false, copyDialog=null;
  async function copyLink(path){
    const url=new URL(path,location.origin).href;
    if(copyDialog?.open){const input=copyDialog.querySelector('input');input.value=url;input.focus();input.select();return;}
    if(copyPending)return;
    copyPending=true;
    try{await navigator.clipboard.writeText(url);document.getElementById('summary').textContent='Link copied.';}
    catch{const dialog=el('dialog');copyDialog=dialog;dialog.className='music-dialog';const title=el('h2','Share this link'),input=el('input'),close=el('button','Done');input.value=url;input.readOnly=true;input.setAttribute('aria-label','Share link');close.onclick=()=>dialog.close();dialog.append(title,input,close);dialog.onclose=()=>{dialog.remove();if(copyDialog===dialog)copyDialog=null;};document.body.append(dialog);dialog.showModal();input.select();}
    finally{copyPending=false;}
  }
  function profileControls(){
    const social=Music.data.social;if(!social)return el('div');
    const box=el('section');box.className='social-profile';box.append(el('h2','Your public profile'),el('p','Choose a name for your shared playlists. Your email and liked tracks stay private.'));
    const form=el('form'),label=el('label','Public name'),input=el('input'),save=el('button','Save name');input.id='public-name';label.htmlFor=input.id;input.value=social.profile.name;input.maxLength=60;input.required=true;form.append(label,input,save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await Music.api('/api/me/profile','PUT',{name:input.value});await Music.refresh();document.getElementById('summary').textContent='Public name saved.';}catch(e){document.getElementById('error').textContent=e.message;}finally{save.disabled=false;}};
    const copy=el('button','Copy profile link');copy.onclick=()=>copyLink('/people/'+Music.user.id);box.append(form,link('View your profile ↗','/people/'+Music.user.id),copy);
    if(social.people.length){box.append(el('h3','Listeners you follow'));const list=el('div');list.className='following-people';for(const p of social.people){const row=el('p');row.append(link(p.name,'/people/'+p.id),followButton('people',p.id));list.append(row);}box.append(list);}
    return box;
  }
  return {el,link,followButton,shareControls,profileControls,copyLink};
})();
