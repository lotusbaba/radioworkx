const $=id=>document.getElementById(id);
const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
let tab='tracks',page=1,pages=1,version=0;
const titles={tracks:'Tracks',hosts:'Source hosts',requests:'Requests and chat',reactions:'Reaction events',downloads:'Successful downloads',crawls:'Crawler runs',visuals:'Artwork videos',objects:'Stored objects'};
function dates(){const end=new Date();$('to').value=end.toISOString().slice(0,16);$('from').value=new Date(end-Number($('period').value)*86400000).toISOString().slice(0,16);}
dates();
function params(){const start=Date.parse($('from').value+'Z')/1000,end=Date.parse($('to').value+'Z')/1000;if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end||end-start>366*86400)throw Error('Choose a valid date range of up to 366 days.');return new URLSearchParams({start,end});}
async function get(url){const r=await fetch(url);if(!r.ok)throw Error(r.status===401?'Admin authentication is required. Reload to sign in.':`Unable to load data (${r.status}).`);return r.json();}
function chart(series,key){const card=node('section','');card.className='card';card.append(node('h2',key[0].toUpperCase()+key.slice(1)));const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 600 160');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${key} over the selected period`);const max=Math.max(1,...series.map(r=>r[key]));const width=580/Math.max(1,series.length);for(let i=0;i<series.length;i++){const h=series[i][key]/max*125;const bar=document.createElementNS(svg.namespaceURI,'rect');for(const [k,v] of Object.entries({x:10+i*width,y:140-h,width:Math.max(1,width-2),height:h,fill:'#c2ef88'}))bar.setAttribute(k,v);const title=document.createElementNS(svg.namespaceURI,'title');title.textContent=`${new Date(series[i].at*1000).toISOString()}: ${series[i][key]} ${key}`;bar.append(title);svg.append(bar);}card.append(svg,node('small',`Peak: ${max===1&&!series.some(r=>r[key])?0:max} · hover bars for counts · UTC`));return card;}
async function overview(){const data=await get('/api/admin/overview?'+params());$('status').textContent=`${data.station_status} · ${data.hosts} hosts · Library: ${Object.entries(data.library).map(([k,v])=>`${v} ${k}`).join(', ')} · ${data.crawler_status}`;$('metrics').replaceChildren(...Object.entries(data.metrics).map(([key,value])=>{const card=node('section','');card.className='card';const label={reactions:'Reactions',downloads:'New downloads',requests:'Music requests',chat_messages:'Chat messages'}[key];const total=node('div',value.current.toLocaleString());total.className='metric';card.append(node('h2',label),total,node('small',`${value.previous} in previous equal-length period`));return card;}));$('charts').replaceChildren(...['reactions','downloads','requests'].map(key=>chart(data.series,key)));$('genres').replaceChildren(...data.genres.map(r=>node('span',`${r.genre}: ${r.reactions}`)));if(!data.genres.length)$('genres').append(node('p','No reactions in this period.'));}
async function table(){const current=++version;const p=params();p.set('page',page);p.set('page_size',$('size').value);p.set('q',$('search').value);const data=await get('/api/admin/repository/'+tab+'?'+p);if(current!==version)return;pages=data.pages;$('table-title').textContent=titles[tab];$('table-note').textContent=data.date_filter_applied?'Filtered by the selected dates.':'Complete repository; date selection applies to activity charts and history tables.';$('pagination').textContent=`Page ${page} of ${pages} · ${data.total.toLocaleString()} records`;$('previous').disabled=page<=1;$('next').disabled=page>=pages;const keys=data.items.length?Object.keys(data.items[0]):[];const header=node('tr','');for(const key of keys)header.append(node('th',key.replaceAll('_',' ')));$('head').replaceChildren(header);$('rows').replaceChildren(...data.items.map(row=>{const tr=node('tr','');for(const key of keys){let value=row[key];if(value!==null&&['created','accepted','completed','started','finished','downloaded_at','first_seen','last_seen'].includes(key))value=new Date(value*1000).toISOString().replace('T',' ').slice(0,19)+' UTC';const td=node('td',value===null?'—':String(value));tr.append(td);}return tr;}));if(!data.items.length){const tr=node('tr','');tr.append(node('td','No matching records.'));$('rows').append(tr);}}
async function load(all=false){$('error').textContent='';try{await Promise.all(all?[overview(),table()]:[table()]);}catch(e){$('error').textContent=e.message;}}
for(const [key,title] of Object.entries(titles)){const b=node('button',title);b.type='button';b.setAttribute('aria-selected',String(key===tab));b.onclick=()=>{tab=key;page=1;for(const e of $('tabs').children)e.setAttribute('aria-selected',String(e===b));load();};$('tabs').append(b);}
$('period').onchange=()=>{if($('period').value!=='custom'){dates();page=1;load(true);}};
$('apply').onclick=()=>{page=1;load(true);};$('refresh').onclick=()=>load(true);$('size').onchange=()=>{page=1;load();};let timer;$('search').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{page=1;load();},300);};$('previous').onclick=()=>{if(page>1){page--;load();}};$('next').onclick=()=>{if(page<pages){page++;load();}};load(true);

let tokenPage=1,tokenPages=1;
function hideToken(){ $('token-value').value='';$('token-reveal').hidden=true;$('token-create').disabled=false; }
async function tokenCall(url,method,body){
  const response=await fetch(url,{method,headers:{'Content-Type':'application/json','X-Admin-Action':'tokens'},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  if(!response.ok)throw Error(`Token operation failed (${response.status}).`);
  return response.json();
}
async function tokenList(){
  const data=await get('/api/admin/tokens?page='+tokenPage);tokenPage=data.page;tokenPages=data.pages;
  $('token-rows').replaceChildren(...data.items.map(item=>{
    const row=node('tr','');
    for(const value of [item.name,item.token,new Date(item.created*1000).toLocaleString(),item.last_used?new Date(item.last_used*1000).toLocaleString():'Never',item.revoked?'Revoked':'Active'])row.append(node('td',value));
    const cell=node('td',''),button=node('button','Revoke');button.disabled=!!item.revoked;
    button.onclick=async()=>{button.disabled=true;try{await tokenCall('/api/admin/tokens/'+item.id,'DELETE');hideToken();await tokenList();}catch(e){button.disabled=false;$('token-message').textContent=e.message;}};
    cell.append(button);row.append(cell);return row;
  }));
  $('token-page').textContent=`Page ${data.page} of ${data.pages} · ${data.total} tokens`;
  $('token-previous').disabled=tokenPage<=1;$('token-next').disabled=tokenPage>=tokenPages;
}
$('token-form').onsubmit=async event=>{
  event.preventDefault();if(!$('token-reveal').hidden)return;
  $('token-create').disabled=true;$('token-message').textContent='';
  try{
    const result=await tokenCall('/api/admin/tokens','POST',{name:$('token-name').value.trim()});
    $('token-value').value=result.token;$('token-reveal').hidden=false;$('token-name').value='';tokenPage=1;await tokenList();
    $('token-message').textContent='Save this token now. It cannot be retrieved again.';
  }catch(e){$('token-message').textContent=e.message;if($('token-reveal').hidden)$('token-create').disabled=false;}
};
$('token-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('token-value').value);hideToken();$('token-message').textContent='Copied. The token is now permanently hidden here.';}catch{$('token-message').textContent='Clipboard unavailable. Copy the displayed token manually, then select Hide permanently.';}};
$('token-hide').onclick=()=>{hideToken();$('token-message').textContent='Token hidden. Generate a replacement if you did not save it.';};
window.addEventListener('pagehide',hideToken);
$('token-previous').onclick=()=>{tokenPage--;tokenList().catch(e=>$('token-message').textContent=e.message);};
$('token-next').onclick=()=>{tokenPage++;tokenList().catch(e=>$('token-message').textContent=e.message);};
tokenList().catch(e=>$('token-message').textContent=e.message);
