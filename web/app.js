const page = document.body.dataset.page || 'dashboard';
const state = { snapshot: null, points: [], health: null, curves: null, pointSummary: null, pointKind: 'yc', refreshing: false, selectedDevices: new Set(), devicePage: 0, devicePageSize: 12, devicePowerDrafts: new Map() };
const $ = id => document.getElementById(id);
const fmt = (value, digits = 1) => value != null && value !== '' && Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '--';
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
const json = value => JSON.stringify(value, null, 2);
function setText(id, value) { const node = $(id); if (node) node.textContent = value; }
const tablePages = {};
function setHtml(id, value) { const node = $(id); if (node) { node.innerHTML = value; if (node.classList.contains('table-wrap')) requestAnimationFrame(() => paginateTable(node)); } }
function paginateTable(node) {
  const table=node.querySelector('table'); if(!table || !node.offsetHeight)return;
  const rows=[...table.querySelectorAll('tbody tr')], card=node.closest('.card');
  const available=Math.min(420, (card?.getBoundingClientRect().bottom || window.innerHeight-20)-node.getBoundingClientRect().top-55);
  const rowHeight=rows.find(row=>!row.hidden)?.getBoundingClientRect().height || 36;
  const size=Math.max(1,Math.floor((available-32)/Math.max(30,rowHeight))), total=Math.max(1,Math.ceil(rows.length/size));
  let index=Math.min(tablePages[node.id] || 0,total-1);
  rows.forEach((row,i)=>{row.hidden=i<index*size || i>=(index+1)*size;});
  node.style.maxHeight='none';
  let pager=node.nextElementSibling;
  if(!pager?.classList.contains('table-pager')){pager=document.createElement('div');pager.className='table-pager';node.after(pager);}
  pager.replaceChildren();
  const previous=document.createElement('button'),next=document.createElement('button'),status=document.createElement('span');
  previous.textContent='上一页';next.textContent='下一页';status.textContent=(index+1)+' / '+total+' · '+rows.length+' 条';
  previous.disabled=index===0;next.disabled=index===total-1;
  previous.onclick=()=>{tablePages[node.id]=index-1;paginateTable(node);};
  next.onclick=()=>{tablePages[node.id]=index+1;paginateTable(node);};
  pager.append(previous,status,next);
}
function notice(id, message, error) { const node = $(id); if (!node) return; node.textContent = message; node.className = 'notice' + (error ? ' error-text' : ''); }
async function api(path, options = {}) { const response = await fetch(path, { headers: { 'Content-Type':'application/json', ...(options.headers || {}) }, ...options }); const data = await response.json(); if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status)); if(data.delivery_error)throw new Error(data.message); return data; }

function updateClock(snapshot) {
  if (!snapshot || !snapshot.clock) return;
  setText('simTime', snapshot.clock.sim_time); setText('runState', snapshot.clock.running ? '运行中' : '已暂停');
  const speed = $('speedSetpoint'); if (speed && document.activeElement !== speed) speed.value = snapshot.clock.speed;
  setText('speedOutput', Number(snapshot.clock.speed).toFixed(1));
}
function bindClock() {
  document.querySelectorAll('[data-clock]').forEach(button => button.addEventListener('click', async () => { try { updateClock(await api('/api/clock', { method:'POST', body:JSON.stringify({ action:button.dataset.clock }) })); } catch (error) { alert(error.message); } }));
  const speed = $('speedSetpoint');
  if (speed) { speed.addEventListener('input', () => setText('speedOutput', Number(speed.value).toFixed(1))); speed.addEventListener('change', async () => { try { updateClock(await api('/api/clock', { method:'POST', body:JSON.stringify({ action:'speed', value:Number(speed.value) }) })); } catch (error) { alert(error.message); } }); }
}
function downloadJson(filename, value) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' });
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function bindShortcuts() {
  document.addEventListener('keydown', event => {
    const tag = (event.target && event.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'button' || tag === 'a' || event.ctrlKey && event.key.toLowerCase() !== 'e') return;
    if (event.key === ' ') { event.preventDefault(); document.querySelector('[data-clock="' + (state.snapshot && state.snapshot.clock && state.snapshot.clock.running ? 'pause' : 'start') + '"]')?.click(); }
    if (event.key.toLowerCase() === 'n') document.querySelector('[data-clock="step"]')?.click();
    if (event.ctrlKey && event.key.toLowerCase() === 'e') { event.preventDefault(); $('exportSnapshot')?.click(); }
  });
  $('exportSnapshot')?.addEventListener('click', () => { if (state.snapshot) downloadJson('simulator-snapshot-' + (state.snapshot.sequence || 0) + '.json', state.snapshot); });
}
function bindTabs() {
  document.querySelectorAll('[data-tabs]').forEach(group => {
    const buttons = group.querySelectorAll('[data-tab]');
    const panels = group.querySelectorAll('[data-panel]');
    buttons.forEach(button => button.addEventListener('click', () => {
      const target = button.dataset.tab;
      buttons.forEach(item => item.classList.toggle('active', item === button));
      panels.forEach(panel => panel.classList.toggle('active', panel.dataset.panel === target));
      if (page === 'dashboard' && target === 'trend' && state.snapshot) drawTrend(state.snapshot.history || []);
    }));
  });
}
function drawTrend(items) {
  const canvas = $('trend'); if (!canvas) return; const context = canvas.getContext('2d'), width = canvas.width, height = canvas.height;
  context.clearRect(0, 0, width, height); context.strokeStyle = '#dce6e8'; context.lineWidth = 1;
  for (let index = 0; index < 5; index += 1) { const y = 18 + index * (height - 38) / 4; context.beginPath(); context.moveTo(36, y); context.lineTo(width - 12, y); context.stroke(); }
  if (!items || !items.length) return; const series = [['wind_kw','#2f77b5'],['pv_kw','#db8b27'],['diesel_kw','#7359aa'],['battery_kw','#2b9460'],['load_kw','#c53c48']]; const max = Math.max(240, ...items.map(item => Number(item.load_kw) || 0));
  series.forEach(([key, color]) => { context.strokeStyle = color; context.lineWidth = 2; context.beginPath(); items.forEach((item, index) => { const x = 38 + index * (width - 56) / Math.max(1, items.length - 1); const y = height - 20 - (Number(item[key]) || 0) / max * (height - 42); index ? context.lineTo(x, y) : context.moveTo(x, y); }); context.stroke(); });
}

function renderDashboard(snapshot, health) {
  const network = snapshot.network || {}, weather = snapshot.weather || {}, model = snapshot.model || {}, flow = snapshot.power_flow || {}, iec = (health || {}).iec104 || {};
  setText('frequency', fmt(network.frequency_hz,3)); setText('tieFlow', fmt(network.tie_flow_kw,1)); setText('soc', fmt(snapshot.soc_pct,1));
  setText('windSpeed', fmt(weather.wind_speed_mps,2)); setText('solar', fmt(weather.solar_irradiance_w_m2,0)); setText('temperature', fmt(weather.air_temp_c,1)); setText('load', fmt(network.load_kw,1));
  setText('modelName', model.name || '--'); setText('deviceCount', model.device_count == null ? '--' : model.device_count); setText('nodeCount', model.node_count == null ? ((model.topology || {}).nodes || []).length : model.node_count); setText('curveCount', Object.values(model.curve_counts || {}).reduce((sum, value) => sum + value, 0));
  const generation = snapshot.generation || {}; setHtml('generationSnapshot', '<div><span>风电</span><strong>' + fmt(generation.wind_kw,1) + ' kW</strong></div><div><span>光伏</span><strong>' + fmt(generation.pv_kw,1) + ' kW</strong></div><div><span>柴发</span><strong>' + fmt(generation.diesel_kw,1) + ' kW</strong></div><div><span>储能</span><strong>' + fmt(generation.battery_kw,1) + ' kW</strong></div><div><span>可用新能源</span><strong>' + fmt(generation.renewable_available_kw,1) + ' kW</strong></div><div><span>功率不平衡</span><strong>' + fmt(flow.mismatch_kw,2) + ' kW</strong></div>');
  const hasAlarms = (snapshot.alarms || []).length > 0; setText('alarmBadge', hasAlarms ? '有告警' : '正常'); if ($('alarmBadge')) $('alarmBadge').className = 'badge ' + (hasAlarms ? 'error' : 'ok');
  setText('iecBadge', iec.running ? '运行中' : '已停止'); if ($('iecBadge')) $('iecBadge').className = 'badge ' + (iec.running ? 'ok' : ''); setText('iecEndpoint', (iec.bind_ip || '--') + ':' + (iec.port || '--')); setText('iecClients', iec.connections == null ? '--' : iec.connections); setText('iecPoints', iec.point_count == null ? '--' : iec.point_count); setText('iecSeq', iec.last_publish_seq == null ? '--' : iec.last_publish_seq);
  setHtml('flowSummary', '<dl><div><dt>状态</dt><dd>' + (flow.converged ? '收敛' : '未收敛') + '</dd></div><div><dt>迭代次数</dt><dd>' + (flow.iterations == null ? '--' : flow.iterations) + '</dd></div><div><dt>不平衡</dt><dd>' + fmt(flow.mismatch_kw,3) + ' kW</dd></div></dl>');
  setHtml('alarms', snapshot.alarms && snapshot.alarms.length ? snapshot.alarms.slice(0,8).map(alarm => '<div class="alarm ' + (alarm.severity === 'warning' ? 'warning' : '') + '"><b>' + esc(alarm.code) + '</b> ' + esc(alarm.message) + '<small>仿真时刻 ' + alarm.time + 's</small></div>').join('') : '<p>当前无告警</p>'); renderEvents(snapshot.events || []); drawTrend(snapshot.history || []);
}
function renderEvents(events) {
  setHtml('eventLog', events && events.length ? events.map(event => '<div class="event-row"><time>' + esc(event.sim_time || '--') + '</time><span class="event-kind">' + esc(event.kind || 'event') + '</span><span class="event-message">' + esc(event.message || '') + '</span><span class="event-source">' + esc(event.source || 'system') + '</span></div>').join('') : '<p>暂无操作记录</p>');
}
function bindScenarios() {
  document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', async () => {
    try { const result = await api('/api/scenario', { method:'POST', body:JSON.stringify({ name: button.dataset.scenario, source:'web' }) }); notice('scenarioMessage', '已切换：' + result.label); await refresh(); }
    catch (error) { notice('scenarioMessage', error.message, true); }
  }));
}

function renderModel(snapshot, pointSummary) {
  const model = snapshot.model || {}; setText('modelTitle', model.name || '--'); setText('modelSource', '来源：' + (model.source || '--'));
  setHtml('modelSummary', '<dl><div><dt>设备数量</dt><dd>' + (model.device_count || 0) + '</dd></div><div><dt>拓扑节点</dt><dd>' + ((model.topology || {}).nodes || []).length + '</dd></div><div><dt>拓扑支路</dt><dd>' + ((model.topology || {}).edges || []).length + '</dd></div><div><dt>环境曲线</dt><dd>' + ((model.curve_counts || {}).weather || 0) + ' 条</dd></div><div><dt>负荷曲线</dt><dd>' + ((model.curve_counts || {}).load || 0) + ' 条</dd></div><div><dt>柴发曲线</dt><dd>' + ((model.curve_counts || {}).diesel || 0) + ' 条</dd></div></dl>');
  const devices = snapshot.devices || []; setHtml('modelDevices', devices.length ? '<table><thead><tr><th>设备</th><th>类型</th><th>容量</th><th>状态</th></tr></thead><tbody>' + devices.map(device => '<tr><td>' + esc(device.name || device.id) + '</td><td>' + esc(device.type) + '</td><td>' + fmt(device.rated_kw,1) + ' kW</td><td>' + ((device.running == null ? device.run : device.running) ? '投入' : '退出') + '</td></tr>').join('') + '</tbody></table>' : '<p>当前模型没有导入设备</p>');
  if (pointSummary) setHtml('pointSummary', ['yc','yx','yk'].map(kind => '<div><span>' + kind.toUpperCase() + '</span><strong>' + (pointSummary[kind] || 0) + '</strong></div>').join(''));
}
function bindModel() {
  $('importModel')?.addEventListener('click', async () => { const file = $('modelFile')?.files[0]; if (!file) return alert('请选择模型文件'); try { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ''; for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index,index + 0x8000)); const result = await api('/api/model/import', { method:'POST', body:JSON.stringify({ filename:file.name, data_base64:btoa(binary) }) }); notice('importStatus', '已导入 ' + result.model.name + '，运行点 ' + result.points + ' 个' + ((result.model.metadata?.warnings || []).length ? '；' + result.model.metadata.warnings.join('；') : '')); await refresh(); } catch (error) { notice('importStatus', error.message, true); } });
  $('generatePoints')?.addEventListener('click', async () => { try { const result = await api('/api/scdfe/points/generate', { method:'POST', body:JSON.stringify({ replace:true }) }); notice('pointTableStatus', result.message || ('scdfe_s 已生成 ' + result.total + ' 个点')); await refresh(); } catch (error) { notice('pointTableStatus', error.message, true); } });
}

function renderCurves(snapshot) {
  const weather = snapshot.weather || {}, generation = snapshot.generation || {}; setHtml('curveSnapshot', '<dl><div><dt>风速</dt><dd>' + fmt(weather.wind_speed_mps,2) + ' m/s</dd></div><div><dt>太阳辐照</dt><dd>' + fmt(weather.solar_irradiance_w_m2,0) + ' W/m²</dd></div><div><dt>气温</dt><dd>' + fmt(weather.air_temp_c,1) + ' °C</dd></div><div><dt>负荷</dt><dd>' + fmt(weather.load_kw,1) + ' kW</dd></div></dl>'); setHtml('curveGeneration', '<dl><div><dt>风电</dt><dd>' + fmt(generation.wind_kw,1) + ' kW</dd></div><div><dt>光伏</dt><dd>' + fmt(generation.pv_kw,1) + ' kW</dd></div><div><dt>柴油机</dt><dd>' + fmt(generation.diesel_kw,1) + ' kW</dd></div><div><dt>储能</dt><dd>' + fmt(generation.battery_kw,1) + ' kW</dd></div></dl>');
  // Keep unsaved curve edits intact across realtime refreshes.
}
let curveEditorKey = '', curveEditorPage = 0, curveEditorCount = 0;
const curveEditorSize = 6;
function storeCurvePage() {
  if (!curveEditorKey) return;
  const rows = JSON.parse($('curveEditor').value);
  if (!Array.isArray(rows)) throw new Error('当前页应为曲线记录数组');
  state.curves[curveEditorKey].splice(curveEditorPage*curveEditorSize, curveEditorCount, ...rows);
  curveEditorCount = rows.length;
}
function showCurvePage(reset=false) {
  if (reset) {
    curveEditorKey = Object.keys(state.curves)[0] || 'weather';
    curveEditorPage = 0;
    $('curveEditorSeries').replaceChildren(...Object.keys(state.curves).map(key => {
      const option=document.createElement('option');option.value=key;option.textContent=key;return option;
    }));
  }
  const rows=state.curves[curveEditorKey] || [], pages=Math.max(1,Math.ceil(rows.length/curveEditorSize));
  curveEditorPage=Math.min(curveEditorPage,pages-1);
  const visible=rows.slice(curveEditorPage*curveEditorSize,(curveEditorPage+1)*curveEditorSize);
  curveEditorCount=visible.length;
  $('curveEditor').value='[\n'+visible.map(row=>'  '+JSON.stringify(row)).join(',\n')+'\n]';
  $('curveEditorSeries').value=curveEditorKey;
  $('curveEditorPage').textContent=(curveEditorPage+1)+' / '+pages;
  $('curveEditorPrevious').disabled=curveEditorPage===0;
  $('curveEditorNext').disabled=curveEditorPage===pages-1;
}
async function loadCurves() {
  const result=await api('/api/curves'); state.curves=result.curves; showCurvePage(true); setText('curveStatus','已读取');
}
function bindCurves() {
  $('loadCurves')?.addEventListener('click',()=>loadCurves().catch(error=>notice('curveMessage',error.message,true)));
  $('curveEditorSeries').onchange=()=>{
    const key=$('curveEditorSeries').value;
    try{storeCurvePage();curveEditorKey=key;curveEditorPage=0;showCurvePage();}
    catch(error){$('curveEditorSeries').value=curveEditorKey;notice('curveMessage',error.message,true);}
  };
  for(const [id,step] of [['curveEditorPrevious',-1],['curveEditorNext',1]]) $(id).onclick=()=>{
    try{storeCurvePage();curveEditorPage+=step;showCurvePage();}catch(error){notice('curveMessage',error.message,true);}
  };
  $('saveCurves')?.addEventListener('click',async()=>{
    try{storeCurvePage();const result=await api('/api/curves',{method:'POST',body:JSON.stringify({curves:state.curves})});
      state.curves=result.curves;showCurvePage();notice('curveMessage','所有曲线已写入 simulator.sqlite3，实时仿真已更新');setText('curveStatus','数据库已保存');await refresh();
    }catch(error){notice('curveMessage','保存失败：'+error.message,true);}
  });
  loadCurves().catch(error=>notice('curveMessage',error.message,true));
}
const curvePresets = {
  daylight: { weather: [{ minute: 0, wind_speed_mps: 6, solar_irradiance_w_m2: 0, air_temp_c: -22, load_kw: 155 }, { minute: 720, wind_speed_mps: 5, solar_irradiance_w_m2: 900, air_temp_c: -14, load_kw: 185 }, { minute: 1439, wind_speed_mps: 6, solar_irradiance_w_m2: 0, air_temp_c: -22, load_kw: 155 }], load: [], diesel: [{ minute: 0, diesel_kw: 80 }, { minute: 720, diesel_kw: 60 }], battery: [{ minute: 0, battery_kw: -15 }, { minute: 720, battery_kw: 20 }] },
  storm: { weather: [{ minute: 0, wind_speed_mps: 18, solar_irradiance_w_m2: 0, air_temp_c: -25, load_kw: 140 }, { minute: 720, wind_speed_mps: 24, solar_irradiance_w_m2: 80, air_temp_c: -18, load_kw: 160 }, { minute: 1439, wind_speed_mps: 18, solar_irradiance_w_m2: 0, air_temp_c: -25, load_kw: 140 }], load: [], diesel: [{ minute: 0, diesel_kw: 120 }], battery: [{ minute: 0, battery_kw: 0 }] },
  peak: { weather: [{ minute: 0, wind_speed_mps: 7, solar_irradiance_w_m2: 0, air_temp_c: -22, load_kw: 150 }, { minute: 1080, wind_speed_mps: 6, solar_irradiance_w_m2: 100, air_temp_c: -17, load_kw: 245 }, { minute: 1439, wind_speed_mps: 7, solar_irradiance_w_m2: 0, air_temp_c: -22, load_kw: 150 }], load: [], diesel: [{ minute: 0, diesel_kw: 140 }, { minute: 1080, diesel_kw: 210 }], battery: [{ minute: 0, battery_kw: 0 }, { minute: 1080, battery_kw: 65 }] },
  island: { weather: [{ minute: 0, wind_speed_mps: 8, solar_irradiance_w_m2: 0, air_temp_c: -20, load_kw: 135 }, { minute: 720, wind_speed_mps: 9, solar_irradiance_w_m2: 650, air_temp_c: -14, load_kw: 150 }, { minute: 1439, wind_speed_mps: 8, solar_irradiance_w_m2: 0, air_temp_c: -20, load_kw: 135 }], load: [], diesel: [{ minute: 0, diesel_kw: 100 }], battery: [{ minute: 0, battery_kw: -55 }, { minute: 360, battery_kw: 15 }, { minute: 1080, battery_kw: 75 }] }
};
function bindCurveTools() {
  $('applyCurvePreset')?.addEventListener('click', () => { const key = $('curvePreset')?.value; if (!key || !curvePresets[key]) return notice('curveMessage', '请选择曲线预设', true); state.curves = JSON.parse(JSON.stringify(curvePresets[key])); showCurvePage(true); notice('curveMessage', '预设已填充，请点击保存曲线生效'); });
  $('downloadCurves')?.addEventListener('click', () => { try { storeCurvePage(); downloadJson('simulator-curves.json', state.curves); } catch (error) { notice('curveMessage', '当前曲线 JSON 无效', true); } });
}

function deviceRows() {
  const devices = state.snapshot?.devices || [], query = ($('deviceSearch')?.value || '').trim().toLowerCase();
  const type = $('deviceTypeFilter')?.value || '', run = $('deviceRunFilter')?.value || '';
  return devices.filter(device => {
    const running = device.running == null ? device.run : device.running;
    return (!query || [device.id, device.name, device.type].some(value => String(value || '').toLowerCase().includes(query))) && (!type || device.type === type) && (!run || run === 'running' && running || run === 'stopped' && !running);
  });
}
function renderDevices(snapshot) {
  const devices = snapshot.devices || [], topology = snapshot.topology || {}, flow = snapshot.power_flow || {};
  const typeFilter = $('deviceTypeFilter');
  if (typeFilter) { const current = typeFilter.value; const types = [...new Set(devices.map(device => device.type).filter(Boolean))].sort(); typeFilter.replaceChildren(new Option('全部类型',''), ...types.map(type => new Option(type,type))); typeFilter.value = types.includes(current) ? current : ''; }
  state.selectedDevices = new Set([...state.selectedDevices].filter(id => devices.some(device => device.id === id)));
  const visible = deviceRows(); const pageSize = state.devicePageSize; const total = Math.max(1, Math.ceil(visible.length / pageSize)); state.devicePage = Math.min(state.devicePage, total - 1); const pageRows = visible.slice(state.devicePage * pageSize, (state.devicePage + 1) * pageSize);
  const html = pageRows.length ? '<table class="device-table"><thead><tr><th><input id="selectPage" type="checkbox" aria-label="选择当前页"></th><th>设备</th><th>类型</th><th>状态</th><th>功率 / SOC</th><th>操作</th></tr></thead><tbody>' + pageRows.map(device => { const running = device.running == null ? device.run : device.running; const selected = state.selectedDevices.has(device.id); const power = device.type === 'battery' ? fmt(device.p_kw,1) + ' kW · SOC ' + fmt(device.soc_pct,1) + '%' : fmt(device.p_kw,1) + ' kW'; const action = running ? 'stop' : 'start'; const adjustable = ['wind','pv','diesel','battery','generator','load'].includes(device.type); const draft = state.devicePowerDrafts.get(device.id) ?? ''; const reasons = (device.limit_reasons || []).length ? ' · 限制：' + device.limit_reasons.join('、') : ''; return '<tr class="' + (selected ? 'selected-row' : '') + '"><td><input type="checkbox" data-device-select="' + esc(device.id) + '" ' + (selected ? 'checked' : '') + '></td><td title="' + esc(device.id) + '">' + esc(device.name || device.id) + '</td><td>' + esc(device.type) + '</td><td>' + (running ? '投入' : '退出') + '</td><td>' + power + (device.control_mode === 'manual' ? ' · 手动' : '') + esc(reasons) + '</td><td class="device-actions"><button data-device-action="' + action + '" data-device-id="' + esc(device.id) + '">' + (running ? '退出' : '投入') + '</button>' + (device.type === 'switch' ? '<button data-device-action="' + (device.closed_status ? 'open' : 'close') + '" data-device-id="' + esc(device.id) + '">' + (device.closed_status ? '分闸' : '合闸') + '</button>' : adjustable ? '<input type="number" step="0.1" data-device-power="' + esc(device.id) + '" value="' + esc(draft) + '" placeholder="kW" title="功率设定"><button data-device-action="set_power" data-device-id="' + esc(device.id) + '">设定</button>' + (device.control_mode === 'manual' ? '<button data-device-action="follow_curve" data-device-id="' + esc(device.id) + '">跟随曲线</button>' : '') : '') + '</td></tr>'; }).join('') + '</tbody></table><div class="table-pager"><button id="devicePrev" ' + (state.devicePage === 0 ? 'disabled' : '') + '>上一页</button><span>' + (state.devicePage + 1) + ' / ' + total + ' · 结果 ' + visible.length + ' · 已选 ' + state.selectedDevices.size + '</span><button id="deviceNext" ' + (state.devicePage >= total - 1 ? 'disabled' : '') + '>下一页</button></div>' : '<p>没有匹配的设备</p>';
  const table = $('deviceTable'); if (table) { table.innerHTML = html; table.querySelectorAll('[data-device-select]').forEach(input => input.onchange = () => { input.checked ? state.selectedDevices.add(input.dataset.deviceSelect) : state.selectedDevices.delete(input.dataset.deviceSelect); renderDevices(snapshot); }); table.querySelectorAll('[data-device-power]').forEach(input => input.oninput = () => state.devicePowerDrafts.set(input.dataset.devicePower, input.value)); table.querySelector('#selectPage')?.addEventListener('change', event => { pageRows.forEach(device => event.target.checked ? state.selectedDevices.add(device.id) : state.selectedDevices.delete(device.id)); renderDevices(snapshot); }); table.querySelector('#devicePrev')?.addEventListener('click', () => { state.devicePage -= 1; renderDevices(snapshot); }); table.querySelector('#deviceNext')?.addEventListener('click', () => { state.devicePage += 1; renderDevices(snapshot); }); table.querySelectorAll('[data-device-action]').forEach(button => button.onclick = () => { const id = button.dataset.deviceId, action = button.dataset.deviceAction, value = table.querySelector('[data-device-power="' + CSS.escape(id) + '"]')?.value; operateDevices([{ device_id:id, action, value }]).then(() => state.devicePowerDrafts.delete(id)).catch(error => notice('deviceMessage', error.message, true)); }); }
  setText('deviceSelection', '已选 ' + state.selectedDevices.size); setHtml('topologyStats','<dl><div><dt>节点</dt><dd>' + (topology.nodes || []).length + '</dd></div><div><dt>支路</dt><dd>' + (topology.edges || []).length + '</dd></div></dl>'); setHtml('deviceFlow','<dl><div><dt>状态</dt><dd>' + (flow.converged ? '收敛' : '未收敛') + '</dd></div><div><dt>迭代次数</dt><dd>' + (flow.iterations == null ? '--' : flow.iterations) + '</dd></div><div><dt>不平衡</dt><dd>' + fmt(flow.mismatch_kw,3) + ' kW</dd></div></dl>'); setHtml('deviceStates','<dl><div><dt>并网</dt><dd>' + (snapshot.states && snapshot.states.tie_breaker_closed ? '合' : '分') + '</dd></div><div><dt>柴油机</dt><dd>' + (snapshot.states && snapshot.states.diesel_running ? '投入' : '退出') + '</dd></div><div><dt>储能</dt><dd>' + (snapshot.states && snapshot.states.battery_enabled ? '投入' : '退出') + '</dd></div></dl>'); const editor = $('topologyEditor'); if (editor && document.activeElement !== editor) editor.value = json(topology);
}
async function operateDevices(actions) { const normalized = actions.map(action => action.action === 'set_power' ? { ...action, value: Number(action.value) } : action); const result = await api('/api/devices/actions', { method:'POST', body:JSON.stringify({ actions: normalized, model_revision: state.snapshot?.model_revision }) }); notice('deviceMessage', '已执行 ' + result.devices.length + ' 项操作，潮流已更新'); await refresh(); }
async function setAllDevices(running) { const devices = state.snapshot?.devices || []; if (!devices.length) return notice('deviceMessage', '当前模型没有设备', true); try { const result = await api('/api/devices/states', { method:'POST', body:JSON.stringify({ states: devices.map(device => ({ device_id: device.id, running })) }) }); notice('deviceMessage', '已批量' + (running ? '投入' : '退出') + ' ' + result.devices.length + ' 个设备'); await refresh(); } catch (error) { notice('deviceMessage', error.message, true); } }
function bindDevices() { $('refreshTopology')?.addEventListener('click',refresh); $('refreshDevices')?.addEventListener('click',refresh); ['deviceSearch','deviceTypeFilter','deviceRunFilter'].forEach(id => $(id)?.addEventListener('input', () => { state.devicePage = 0; if (state.snapshot) renderDevices(state.snapshot); })); $('devicePageSize')?.addEventListener('change', event => { state.devicePageSize = Math.max(1, Number(event.target.value) || 12); state.devicePage = 0; if (state.snapshot) renderDevices(state.snapshot); }); $('selectVisible')?.addEventListener('click', () => { deviceRows().forEach(device => state.selectedDevices.add(device.id)); renderDevices(state.snapshot); }); $('clearSelection')?.addEventListener('click', () => { state.selectedDevices.clear(); renderDevices(state.snapshot); }); $('batchStart')?.addEventListener('click', () => operateDevices([...state.selectedDevices].map(device_id => ({device_id, action:'start'}))).catch(error => notice('deviceMessage',error.message,true))); $('batchStop')?.addEventListener('click', () => operateDevices([...state.selectedDevices].map(device_id => ({device_id, action:'stop'}))).catch(error => notice('deviceMessage',error.message,true))); $('batchOpen')?.addEventListener('click', () => operateDevices([...state.selectedDevices].map(device_id => ({device_id, action:'open'}))).catch(error => notice('deviceMessage',error.message,true))); $('batchClose')?.addEventListener('click', () => operateDevices([...state.selectedDevices].map(device_id => ({device_id, action:'close'}))).catch(error => notice('deviceMessage',error.message,true))); $('batchSetPower')?.addEventListener('click', () => { const value = Number($('batchPowerSetpoint')?.value); if (!Number.isFinite(value)) return notice('deviceMessage','请输入统一功率值',true); const adjustable = new Set(['wind','pv','diesel','battery','generator','load']); const actions = [...state.selectedDevices].map(device_id => state.snapshot?.devices.find(device => device.id === device_id)).filter(device => device && adjustable.has(device.type)).map(device => ({device_id:device.id, action:'set_power', value})); if (!actions.length) return notice('deviceMessage','请先选择可调功率设备',true); operateDevices(actions).catch(error => notice('deviceMessage',error.message,true)); }); $('batchFollowCurve')?.addEventListener('click', () => { const adjustable = new Set(['wind','pv','diesel','battery','generator','load']); const actions = [...state.selectedDevices].map(device_id => state.snapshot?.devices.find(device => device.id === device_id)).filter(device => device && adjustable.has(device.type)).map(device => ({device_id:device.id, action:'follow_curve'})); if (!actions.length) return notice('deviceMessage','请先选择可调功率设备',true); operateDevices(actions).catch(error => notice('deviceMessage',error.message,true)); }); $('setAllRunning')?.addEventListener('click',() => setAllDevices(true)); $('setAllStopped')?.addEventListener('click',() => setAllDevices(false)); $('saveTopology')?.addEventListener('click',async () => { try { await api('/api/topology',{method:'POST',body:JSON.stringify(JSON.parse($('topologyEditor').value))}); notice('topologyMessage','拓扑已保存并完成联锁计算'); await refresh(); } catch (error) { notice('topologyMessage','拓扑 JSON 无效或保存失败：' + error.message,true); } }); }

function renderScada(snapshot,health,pointSummary) {
  const iec = (health || {}).iec104 || {}, values = snapshot.point_values || {}; setText('scadaStatus',iec.running ? '运行中' : '已停止'); if ($('scadaStatus')) $('scadaStatus').className = 'badge ' + (iec.running ? 'ok' : 'error'); setHtml('iecSummary','<dl><div><dt>监听地址</dt><dd>' + esc(iec.bind_ip) + ':' + (iec.port || '--') + '</dd></div><div><dt>公共地址</dt><dd>' + (iec.common_address || '--') + '</dd></div><div><dt>RTU</dt><dd>' + (iec.rtu_id || '--') + '</dd></div><div><dt>客户端</dt><dd>' + (iec.connections || 0) + '</dd></div><div><dt>最新上送</dt><dd>' + (iec.last_publish_seq == null ? '--' : iec.last_publish_seq) + '</dd></div></dl>'); setHtml('telemetrySummary','<dl><div><dt>YC 实时点</dt><dd>' + (pointSummary.publication?.mapping_mode === 'device_measurement' ? pointSummary.yc : Object.keys(values.yc || {}).length) + '</dd></div><div><dt>YX 实时点</dt><dd>' + (pointSummary.publication?.mapping_mode === 'device_measurement' ? pointSummary.yx : Object.keys(values.yx || {}).length) + '</dd></div><div><dt>序号</dt><dd>' + snapshot.sequence + '</dd></div><div><dt>仿真时刻</dt><dd>' + ((snapshot.clock || {}).sim_time || '--') + '</dd></div></dl>'); setHtml('pointCounts','<dl><div><dt>YC</dt><dd>' + (pointSummary.yc || 0) + '</dd></div><div><dt>YX</dt><dd>' + (pointSummary.yx || 0) + '</dd></div><div><dt>YK</dt><dd>' + (pointSummary.yk || 0) + '</dd></div></dl>'); const visiblePoints = state.pointKind === 'all' ? state.points : state.points.filter(point => point.kind === state.pointKind); setHtml('pointTable',visiblePoints.length ? '<table><thead><tr><th>类型</th><th>点号</th><th>名称</th><th>实时值</th><th>单位</th><th>说明</th></tr></thead><tbody>' + visiblePoints.map(point => { const value = Object.hasOwn(point,'value') ? point.value : (values[point.kind] || {})[point.point_no]; const shown = point.quality === 128 ? '无有效量测' : typeof value === 'boolean' ? (value ? '合' : '分') : fmt(value,point.unit === 'Hz' ? 3 : 2); return '<tr><td>' + point.kind.toUpperCase() + '</td><td>' + (point.rtu_id ? point.rtu_id + ' / ' : '') + point.point_no + '</td><td>' + esc(point.name) + '</td><td class="value">' + shown + '</td><td>' + esc(point.unit) + '</td><td>' + esc(point.description) + '</td></tr>'; }).join('') + '</tbody></table>' : '<p>暂无点表</p>');
}
function bindIecControls() { $('iecStart')?.addEventListener('click',async () => { try { await api('/api/iec104/start',{method:'POST',body:'{}'}); await refresh(); } catch (error) { alert(error.message); } }); $('iecStop')?.addEventListener('click',async () => { try { await api('/api/iec104/stop',{method:'POST',body:'{}'}); await refresh(); } catch (error) { alert(error.message); } }); }
function bindScada() { document.querySelectorAll('[data-point-kind]').forEach(button => button.addEventListener('click', () => { state.pointKind = button.dataset.pointKind; document.querySelectorAll('[data-point-kind]').forEach(item => item.classList.toggle('active', item === button)); if (state.snapshot && state.health) renderScada(state.snapshot, state.health, state.pointSummary || { yc:0,yx:0,yk:0,yt:0 }); })); }

async function refresh() {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    const dashboardPages = new Set(['dashboard','trend','diagnostics','events']);
    const devicePages = new Set(['devices','topology','flow']);
    const modelPages = new Set(['model','model-summary']);
    const curvePages = new Set(['curves','boundary','realtime']);
    const profile = dashboardPages.has(page) || page === 'model' ? 'dashboard' : devicePages.has(page) || modelPages.has(page) ? 'devices' : 'full';
    const needsPoints = page === 'model-summary' || page === 'scada' || page === 'points';
    const requests = [api('/api/overview?profile=' + profile)];
    if (needsPoints) requests.push(api('/api/points'));
    const result = await Promise.all(requests);
    const overview = result[0], snapshot = overview.snapshot, health = overview.health;
    state.snapshot = snapshot; state.health = health; updateClock(snapshot);
    if (dashboardPages.has(page)) renderDashboard(snapshot,health);
    if (page === 'trend') drawTrend(snapshot.history || []);
    if (page === 'model-summary') { state.pointSummary = result[1]; renderModel(snapshot,result[1]); }
    if (curvePages.has(page)) renderCurves(snapshot);
    if (devicePages.has(page)) renderDevices(snapshot);
    if (page === 'scada' || page === 'points') { state.points = result[1].items || []; state.pointSummary = await api('/api/scdfe/points'); renderScada(snapshot,health,state.pointSummary); }
  } catch (error) { console.error(error); } finally { state.refreshing = false; }
}
bindClock(); bindShortcuts(); bindTabs(); bindIecControls(); if (['dashboard'].includes(page)) bindScenarios(); if (page === 'model') bindModel(); if (page === 'curves') { bindCurves(); bindCurveTools(); } if (['devices','topology','flow'].includes(page)) bindDevices(); if (['scada','points'].includes(page)) bindScada(); refresh(); setInterval(refresh,1000);
