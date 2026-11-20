'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const kinds = {database:'/model.html', boundary:'/boundary.html', diagram:'/diagram.html'};
  const state = {directory:new URLSearchParams(location.search).get('directory') || '.', parent:null, page:1, pages:1, pageSize:8, request:0, importing:false, ready:false, remembered:null};
  const initialKind = new URLSearchParams(location.search).get('kind');
  if (kinds[initialKind]) $('inputKind').value = initialKind;
  function message(text, error=false) { $('workspaceMessage').textContent=text; $('workspaceMessage').title=text; $('workspaceMessage').classList.toggle('error',error); }
  async function api(url, options) { const response=await fetch(url,options); const data=await response.json(); if(!response.ok) {const error=new Error(data.error || '请求失败');error.status=response.status;throw error;} return data; }
  async function importFile(path) {
    if(state.importing) return;
    state.importing=true;
    const kind=$('inputKind').value;
    for(const button of $('fileRows').querySelectorAll('button')) button.disabled=true;
    $('viewResult').hidden=true;
    message('正在加载 '+path+'…');
    try {
      const endpoint=kind==='database'?'/api/model/source':'/api/'+kind+'/import';
      const body=kind==='database'?{directory:path.split('/').slice(0,-1).join('/') || '.'}:{path};
      const result=await api(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const warnings=result.model?.metadata?.warnings || [];
      message('已加载：'+path+(warnings.length?'；'+warnings.join('；'):'')); $('viewResult').href=kinds[kind]; $('viewResult').hidden=false;
    } catch(error) { message(error.message,true); }
    finally { state.importing=false; for(const button of $('fileRows').querySelectorAll('button')) button.disabled=false; }
  }
  function render(data) {
    state.directory=data.directory; state.parent=data.parent; state.page=data.page; state.pages=data.pages;
    $('directoryPath').value=data.directory; $('parentFolder').disabled=data.parent===null;
    $('previousPage').disabled=data.page===1; $('nextPage').disabled=data.page===data.pages;
    $('pageIndicator').textContent=data.page+' / '+data.pages; $('entryCount').textContent=data.total+' 项';
    $('emptyFolder').hidden=Boolean(data.entries.length);
    $('fileRows').replaceChildren(...data.entries.map(entry=>{
      const row=document.createElement('tr');
      const name=document.createElement('td'); name.textContent=(entry.directory?'📁 ':'')+entry.name; name.title=entry.path;
      const size=document.createElement('td'); size.textContent=entry.directory?'目录':(entry.bytes/1024).toFixed(1)+' KB';
      const action=document.createElement('td'), button=document.createElement('button'); button.type='button';
      button.textContent=entry.directory?'打开':'加载'; button.setAttribute('aria-label',(entry.directory?'打开 ':'加载 ')+entry.name); button.disabled=state.importing;
      button.onclick=()=>entry.directory?load(entry.path,1):importFile(entry.path);
      action.append(button); row.append(name,size,action); return row;
    }));
  }
  async function load(directory=state.directory,page=state.page) {
    const sequence=++state.request;
    const params=new URLSearchParams({directory,kind:$('inputKind').value,page,page_size:state.pageSize,q:$('fileSearch').value.trim()});
    try { const data=await api('/api/workspace?'+params); if(sequence===state.request) {
      render(data); if($('workspaceMessage').classList.contains('error')) message('路径均相对于配置的工作区根目录。');
      const selection={directory:data.directory,kind:params.get('kind')}, key=JSON.stringify(selection);
      if(state.remembered!==key) {state.remembered=key;window.simulatorPreferences.update(selection);await window.simulatorPreferences.flush();}
      return true;
    }}
    catch(error) { if(sequence===state.request) {state.loadError=error.status;$('directoryPath').value=state.directory;message(error.message,true);} }
    return false;
  }
  function resize() {
    const size=Math.max(1,Math.min(50,Math.floor(($('workspaceTable').clientHeight-43)/42)));
    if(size!==state.pageSize) {state.pageSize=size;if(state.ready)load(state.directory,1);}
  }
  $('directoryForm').onsubmit=event=>{event.preventDefault();load($('directoryPath').value.trim(),1);};
  $('rootFolder').onclick=()=>load('.',1);
  $('parentFolder').onclick=()=>{if(state.parent!==null) load(state.parent,1);};
  for(const button of document.querySelectorAll('[data-folder]')) button.onclick=()=>{ $('fileSearch').value='';load(button.dataset.folder,1); };
  $('inputKind').onchange=()=>{ $('viewResult').hidden=true;load(state.directory,1); };
  $('previousPage').onclick=()=>load(state.directory,state.page-1);
  $('nextPage').onclick=()=>load(state.directory,state.page+1);
  let searchTimer;
  $('fileSearch').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>load(state.directory,1),200);};
  new ResizeObserver(resize).observe($('workspaceTable'));
  window.simulatorPreferences.ready.then(async saved=>{
    const params=new URLSearchParams(location.search);
    if(!params.has('directory') && typeof saved.directory==='string')state.directory=saved.directory;
    if(!params.has('kind') && kinds[saved.kind])$('inputKind').value=saved.kind;
    state.ready=true;
    if(!await load() && !params.has('directory') && state.directory!=='.' && [400,404].includes(state.loadError)) {
      await load('.',1);message('上次目录已失效，已返回根目录。',true);
    }
  });
})();
