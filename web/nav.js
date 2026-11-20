'use strict';
(() => {
  const links = [
    ['/', '总览'],
    ['/trend.html', '趋势'],
    ['/diagnostics.html', '诊断'],
    ['/events.html', '事件'],
    ['/model.html', '电网数据库'],
    ['/workspace.html', '工作目录'],
    ['/storage.html', '数据保存'],
    ['/model-summary.html', '模型摘要'],
    ['/curves.html', '曲线编辑'],
    ['/boundary.html', '边界导入'],
    ['/realtime.html', '实时曲线'],
    ['/diagram.html', '电网图形'],
    ['/devices.html', '设备操作'],
    ['/topology.html', '拓扑编辑'],
    ['/flow.html', '潮流状态'],
    ['/scada.html', 'IEC 104 服务'],
    ['/publication.html', '实时写库'],
    ['/points.html', '四遥点表'],
  ];
  const current = location.pathname === '/index.html' ? '/' : location.pathname || '/';
  document.querySelectorAll('.nav').forEach(nav => {
    nav.replaceChildren(...links.map(([href, label]) => {
      const link = document.createElement('a');
      link.href = href; link.textContent = label;
      link.className = href === current ? 'active' : '';
      return link;
    }));
    const select = document.createElement('select');
    select.className = 'nav-select'; select.setAttribute('aria-label', '功能页面');
    select.replaceChildren(...links.map(([href, label]) => {
      const option = document.createElement('option'); option.value=href; option.textContent=label; option.selected=href===current; return option;
    }));
    select.addEventListener('change', () => location.assign(select.value));
    nav.append(select);
  });
  // Persist view preferences in SQLite; device/curve edits use their explicit save APIs.
  const page = document.body.dataset.page || 'dashboard';
  const fields = new Set(['deviceSearch','deviceTypeFilter','deviceRunFilter','devicePageSize','showValues']);
  let values = {}, pending = {}, timer, saving = null, restoring = false;
  const restoreQueue = new Map();
  const setNotice = error => {
    for (const link of document.querySelectorAll('.nav a[href="/storage.html"]')) {
      link.textContent = error ? '保存失败' : '数据保存'; link.title = error || 'Web 修改保存至 SQLite';
      link.style.color = error ? 'var(--red)' : '';
    }
  };
  function flush() {
    clearTimeout(timer);
    if (saving) return saving;
    saving = (async()=>{
      while (Object.keys(pending).length) {
        const outgoing = pending; pending = {};
        try {
          const response = await fetch('/api/preferences', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({page,values:outgoing}), keepalive:true});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || '页面设置保存失败');
          setNotice('');
        } catch(error) { pending = {...outgoing,...pending}; setNotice(error.message); break; }
      }
    })().finally(()=>{saving=null;});
    return saving;
  }
  function update(changes) { Object.assign(values,changes); Object.assign(pending,changes);clearTimeout(timer);timer=setTimeout(flush,300); }
  function restoreFields() {
    restoring=true;
    try { for (const [id,value] of restoreQueue) {
      const input=document.getElementById(id);
      if (!input || document.activeElement===input) {restoreQueue.delete(id);continue;}
      if(input.tagName==='SELECT' && ![...input.options].some(option=>option.value===String(value)))continue;
      restoreQueue.delete(id);
      if (input.type==='checkbox') input.checked=Boolean(value); else input.value=String(value);
      input.dispatchEvent(new Event(input.tagName==='SELECT' || input.type==='checkbox'?'change':'input',{bubbles:true}));
      if(input.tagName==='SELECT') input.dispatchEvent(new Event('input',{bubbles:true}));
    }} finally {restoring=false;}
  }
  const observer=new MutationObserver(()=>{if(restoreQueue.size)restoreFields();else observer.disconnect();});
  const ready = fetch('/api/preferences?page='+encodeURIComponent(page)).then(r=>{if(!r.ok)throw new Error('页面设置读取失败');return r.json();}).then(result=>{
    values = {...result.values,...values};
    for(const id of fields)if(id in values)restoreQueue.set(id,values[id]);
    restoreFields();if(restoreQueue.size)observer.observe(document.body,{childList:true,subtree:true});
    return values;
  }).catch(error=>{setNotice(error.message);return values;});
  window.simulatorPreferences={ready,update,flush,get:()=>values};
  for(const type of ['input','change']) document.addEventListener(type,event=>{
    if(!restoring && fields.has(event.target.id)) {restoreQueue.delete(event.target.id);update({[event.target.id]:event.target.type==='checkbox'?event.target.checked:event.target.value});}
  });
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')flush();});
  window.addEventListener('pagehide',flush);
})();
