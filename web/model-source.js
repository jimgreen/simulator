'use strict';
(() => {
  const el = id => document.getElementById(id);
  let active = null, preview = null, tablePage = 0, pageSize = 8, busy = false;
  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function message(text, error=false) { el('databaseMessage').textContent=text; el('databaseMessage').classList.toggle('error',error); }
  function selectPanel(name) {
    document.querySelector('.source-layout').dataset.sourcePanel=name;
    el('sourceSettingsTab').setAttribute('aria-selected',String(name==='settings'));
    el('sourceTablesTab').setAttribute('aria-selected',String(name==='tables'));
  }
  function browseLink() { el('browseDatabase').href='/workspace.html?'+new URLSearchParams({kind:'database',directory:el('modelDirectory').value.trim() || '.'}); }
  function renderTables() {
    const info=preview || active;
    if (!info) return;
    const tables=info.tables || [], pages=Math.max(1,Math.ceil(tables.length/pageSize));
    tablePage=Math.min(tablePage,pages-1);
    el('databaseTableTitle').textContent=preview && preview!==active?'校验预览 · 尚未切换':'已加载模型表';
    el('databaseStats').replaceChildren(...[['数据表',info.table_count],['记录',info.row_count],['设备',info.device_count],['节点',info.node_count]].map(([label,value])=>{
      const div=document.createElement('div'), small=document.createElement('small'), strong=document.createElement('strong');
      small.textContent=label; strong.textContent=value ?? '--'; div.append(small,strong); return div;
    }));
    el('databaseTables').replaceChildren(...tables.slice(tablePage*pageSize,(tablePage+1)*pageSize).map(table=>{
      const row=document.createElement('tr'), name=document.createElement('td'), count=document.createElement('td');
      name.textContent=table.name; name.title=table.name; count.textContent=table.rows; row.append(name,count); return row;
    }));
    el('tablePage').textContent=(tablePage+1)+' / '+pages;
    el('tablePrevious').disabled=tablePage===0; el('tableNext').disabled=tablePage===pages-1;
  }
  function renderActive(info, model) {
    active=info; preview=info; tablePage=0;
    el('modelDirectory').value=info.directory;
    el('activeDatabase').textContent=info.database;
    el('databaseModelTitle').textContent=model.name || '--';
    el('databaseLoadedAt').textContent=info.loaded_at?new Date(info.loaded_at).toLocaleString('zh-CN'):'--';
    el('databaseLoadTime').textContent=info.load_ms+' ms';
    browseLink(); renderTables();
  }
  async function apply(validate=false, current=false) {
    if(busy) return;
    const directory=current?active?.directory:el('modelDirectory').value.trim();
    if(!directory) return message('请输入根目录内的相对目录',true);
    busy=true;
    for(const id of ['validateDatabase','applyDatabase','reloadDatabase','defaultDirectory']) el(id).disabled=true;
    el('modelDirectory').disabled=true;
    message(validate?'正在读取并校验数据库…':'正在加载电网数据库…');
    try {
      const result=await request('/api/model/source'+(validate?'/validate':''),{directory});
      if(validate) {preview=result.source;tablePage=0;renderTables();}
      else {renderActive({...active,...result.source},result.model);await refresh();}
      const warnings=result.source.warnings || [];
      message(result.message+(validate?'，当前仿真未切换':'')+(warnings.length?'；'+warnings.length+' 项参数已按比例规范化':''),Boolean(result.iec104_error));
    } catch(error) { message(error.message,true); }
    finally { busy=false;el('modelDirectory').disabled=false;for(const id of ['validateDatabase','applyDatabase','reloadDatabase','defaultDirectory']) el(id).disabled=false; }
  }
  el('modelDirectory').addEventListener('input',browseLink);
  el('sourceSettingsTab').onclick=()=>selectPanel('settings');
  el('sourceTablesTab').onclick=()=>selectPanel('tables');
  el('validateDatabase').onclick=()=>apply(true);
  el('applyDatabase').onclick=()=>apply();
  el('reloadDatabase').onclick=()=>apply(false,true);
  el('defaultDirectory').onclick=()=>{el('modelDirectory').value=active?.default_directory || 'simulation/qinling/sqldb/model';browseLink();};
  el('tablePrevious').onclick=()=>{tablePage--;renderTables();};
  el('tableNext').onclick=()=>{tablePage++;renderTables();};
  new ResizeObserver(()=>{pageSize=Math.max(1,Math.floor((el('databaseTableSpace').clientHeight-34)/34));renderTables();}).observe(el('databaseTableSpace'));
  request('/api/model/source').then(result=>renderActive(result.source,result.model)).catch(error=>message(error.message,true));
})();
