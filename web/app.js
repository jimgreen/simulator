const page = document.body.dataset.page || 'dashboard';
const state = { snapshot: null, points: [], health: null, curves: null, pointSummary: null, pointKind: 'yc' };
const $ = id => document.getElementById(id);
const fmt = (value, digits = 1) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '--';
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
const json = value => JSON.stringify(value, null, 2);
function setText(id, value) { const node = $(id); if (node) node.textContent = value; }
function setHtml(id, value) { const node = $(id); if (node) node.innerHTML = value; }
function notice(id, message, error) { const node = $(id); if (!node) return; node.textContent = message; node.className = 'notice' + (error ? ' error-text' : ''); }
async function api(path, options = {}) { const response = await fetch(path, { headers: { 'Content-Type':'application/json', ...(options.headers || {}) }, ...options }); const data = await response.json(); if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status)); return data; }

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
  setText('modelName', model.name || '--'); setText('deviceCount', model.device_count == null ? '--' : model.device_count); setText('nodeCount', (model.topology || {}).nodes ? model.topology.nodes.length : 0); setText('curveCount', Object.values(model.curve_counts || {}).reduce((sum, value) => sum + value, 0));
  const hasAlarms = (snapshot.alarms || []).length > 0; setText('alarmBadge', hasAlarms ? '有告警' : '正常'); if ($('alarmBadge')) $('alarmBadge').className = 'badge ' + (hasAlarms ? 'error' : 'ok');
  setText('iecBadge', iec.running ? '运行中' : '已停止'); if ($('iecBadge')) $('iecBadge').className = 'badge ' + (iec.running ? 'ok' : ''); setText('iecEndpoint', (iec.bind_ip || '--') + ':' + (iec.port || '--')); setText('iecClients', iec.connections == null ? '--' : iec.connections); setText('iecPoints', iec.point_count == null ? '--' : iec.point_count); setText('iecSeq', iec.last_publish_seq == null ? '--' : iec.last_publish_seq);
  setHtml('flowSummary', '<dl><div><dt>状态</dt><dd>' + (flow.converged ? '收敛' : '未收敛') + '</dd></div><div><dt>迭代次数</dt><dd>' + (flow.iterations == null ? '--' : flow.iterations) + '</dd></div><div><dt>不平衡</dt><dd>' + fmt(flow.mismatch_kw,3) + ' kW</dd></div></dl>');
  setHtml('alarms', snapshot.alarms && snapshot.alarms.length ? snapshot.alarms.slice(0,8).map(alarm => '<div class="alarm ' + (alarm.severity === 'warning' ? 'warning' : '') + '"><b>' + esc(alarm.code) + '</b> ' + esc(alarm.message) + '<small>仿真时刻 ' + alarm.time + 's</small></div>').join('') : '<p>当前无告警</p>'); drawTrend(snapshot.history || []);
}

function renderModel(snapshot, pointSummary) {
  const model = snapshot.model || {}; setText('modelTitle', model.name || '--'); setText('modelSource', '来源：' + (model.source || '--'));
  setHtml('modelSummary', '<dl><div><dt>设备数量</dt><dd>' + (model.device_count || 0) + '</dd></div><div><dt>拓扑节点</dt><dd>' + ((model.topology || {}).nodes || []).length + '</dd></div><div><dt>拓扑支路</dt><dd>' + ((model.topology || {}).edges || []).length + '</dd></div><div><dt>环境曲线</dt><dd>' + ((model.curve_counts || {}).weather || 0) + ' 条</dd></div><div><dt>负荷曲线</dt><dd>' + ((model.curve_counts || {}).load || 0) + ' 条</dd></div><div><dt>柴发曲线</dt><dd>' + ((model.curve_counts || {}).diesel || 0) + ' 条</dd></div></dl>');
  const devices = snapshot.devices || []; setHtml('modelDevices', devices.length ? '<table><thead><tr><th>设备</th><th>类型</th><th>容量</th><th>状态</th></tr></thead><tbody>' + devices.map(device => '<tr><td>' + esc(device.name || device.id) + '</td><td>' + esc(device.type) + '</td><td>' + fmt(device.rated_kw,1) + ' kW</td><td>' + ((device.running == null ? device.run : device.running) ? '投入' : '退出') + '</td></tr>').join('') + '</tbody></table>' : '<p>当前模型没有导入设备</p>');
  if (pointSummary) setHtml('pointSummary', ['yc','yx','yk'].map(kind => '<div><span>' + kind.toUpperCase() + '</span><strong>' + (pointSummary[kind] || 0) + '</strong></div>').join(''));
}
function bindModel() {
  $('importModel')?.addEventListener('click', async () => { const file = $('modelFile')?.files[0]; if (!file) return alert('请选择模型文件'); try { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ''; for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index,index + 0x8000)); const result = await api('/api/model/import', { method:'POST', body:JSON.stringify({ filename:file.name, data_base64:btoa(binary) }) }); notice('importStatus', '已导入 ' + result.model.name + '，运行点 ' + result.points + ' 个'); await refresh(); } catch (error) { notice('importStatus', error.message, true); } });
  $('generatePoints')?.addEventListener('click', async () => { try { const result = await api('/api/scdfe/points/generate', { method:'POST', body:JSON.stringify({ replace:true }) }); notice('pointTableStatus', 'scdfe_s 已生成 ' + result.total + ' 个点'); await refresh(); } catch (error) { notice('pointTableStatus', error.message, true); } });
}

function renderCurves(snapshot) {
  const weather = snapshot.weather || {}, generation = snapshot.generation || {}; setHtml('curveSnapshot', '<dl><div><dt>风速</dt><dd>' + fmt(weather.wind_speed_mps,2) + ' m/s</dd></div><div><dt>太阳辐照</dt><dd>' + fmt(weather.solar_irradiance_w_m2,0) + ' W/m²</dd></div><div><dt>气温</dt><dd>' + fmt(weather.air_temp_c,1) + ' °C</dd></div><div><dt>负荷</dt><dd>' + fmt(weather.load_kw,1) + ' kW</dd></div></dl>'); setHtml('curveGeneration', '<dl><div><dt>风电</dt><dd>' + fmt(generation.wind_kw,1) + ' kW</dd></div><div><dt>光伏</dt><dd>' + fmt(generation.pv_kw,1) + ' kW</dd></div><div><dt>柴油机</dt><dd>' + fmt(generation.diesel_kw,1) + ' kW</dd></div><div><dt>储能</dt><dd>' + fmt(generation.battery_kw,1) + ' kW</dd></div></dl>');
  const editor = $('curveEditor'); if (editor && document.activeElement !== editor && state.curves) editor.value = json(state.curves);
}
async function loadCurves() { const result = await api('/api/curves'); state.curves = result.curves; if ($('curveEditor')) $('curveEditor').value = json(result.curves); setText('curveStatus','已读取'); }
function bindCurves() { $('loadCurves')?.addEventListener('click', () => loadCurves().catch(error => notice('curveMessage',error.message,true))); $('saveCurves')?.addEventListener('click', async () => { try { const curves = JSON.parse($('curveEditor').value); await api('/api/curves',{method:'POST',body:JSON.stringify({curves})}); state.curves = curves; notice('curveMessage','曲线已保存，后续仿真步进将使用新曲线'); setText('curveStatus','已保存'); await refresh(); } catch (error) { notice('curveMessage','曲线 JSON 无效或保存失败：' + error.message,true); } }); loadCurves().catch(error => notice('curveMessage',error.message,true)); }

function renderDevices(snapshot) {
  const devices = snapshot.devices || [], topology = snapshot.topology || {}, flow = snapshot.power_flow || {}; setHtml('deviceTable',devices.length ? '<table><thead><tr><th>设备</th><th>类型</th><th>状态</th><th>出力</th><th>操作</th></tr></thead><tbody>' + devices.map(device => { const running = device.running == null ? device.run : device.running; return '<tr><td>' + esc(device.name || device.id) + '</td><td>' + esc(device.type) + '</td><td>' + (running ? '投入' : '退出') + '</td><td>' + fmt(device.p_kw,1) + ' kW</td><td><button data-device-id="' + esc(device.id) + '" data-device-run="' + (running ? '0' : '1') + '">' + (running ? '退出' : '投入') + '</button></td></tr>'; }).join('') + '</tbody></table>' : '<p>当前模型没有可管理设备</p>'); document.querySelectorAll('[data-device-id]').forEach(button => button.onclick = async () => { try { await api('/api/devices/state',{method:'POST',body:JSON.stringify({device_id:button.dataset.deviceId,running:button.dataset.deviceRun === '1'})}); await refresh(); } catch (error) { alert(error.message); } });
  setHtml('topologyStats','<dl><div><dt>节点</dt><dd>' + (topology.nodes || []).length + '</dd></div><div><dt>支路</dt><dd>' + (topology.edges || []).length + '</dd></div></dl>'); setHtml('deviceFlow','<dl><div><dt>状态</dt><dd>' + (flow.converged ? '收敛' : '未收敛') + '</dd></div><div><dt>迭代次数</dt><dd>' + (flow.iterations == null ? '--' : flow.iterations) + '</dd></div><div><dt>不平衡</dt><dd>' + fmt(flow.mismatch_kw,3) + ' kW</dd></div></dl>'); setHtml('deviceStates','<dl><div><dt>并网</dt><dd>' + (snapshot.states && snapshot.states.tie_breaker_closed ? '合' : '分') + '</dd></div><div><dt>柴油机</dt><dd>' + (snapshot.states && snapshot.states.diesel_running ? '投入' : '退出') + '</dd></div><div><dt>储能</dt><dd>' + (snapshot.states && snapshot.states.battery_enabled ? '投入' : '退出') + '</dd></div></dl>'); const editor = $('topologyEditor'); if (editor && document.activeElement !== editor) editor.value = json(topology);
}
function bindDevices() { $('refreshTopology')?.addEventListener('click',refresh); $('saveTopology')?.addEventListener('click',async () => { try { await api('/api/topology',{method:'POST',body:JSON.stringify(JSON.parse($('topologyEditor').value))}); notice('topologyMessage','拓扑已保存并完成联锁计算'); await refresh(); } catch (error) { notice('topologyMessage','拓扑 JSON 无效或保存失败：' + error.message,true); } }); }

function renderScada(snapshot,health,pointSummary) {
  const iec = (health || {}).iec104 || {}, values = snapshot.point_values || {}; setText('scadaStatus',iec.running ? '运行中' : '已停止'); if ($('scadaStatus')) $('scadaStatus').className = 'badge ' + (iec.running ? 'ok' : 'error'); setHtml('iecSummary','<dl><div><dt>监听地址</dt><dd>' + esc(iec.bind_ip) + ':' + (iec.port || '--') + '</dd></div><div><dt>公共地址</dt><dd>' + (iec.common_address || '--') + '</dd></div><div><dt>RTU</dt><dd>' + (iec.rtu_id || '--') + '</dd></div><div><dt>客户端</dt><dd>' + (iec.connections || 0) + '</dd></div><div><dt>最新上送</dt><dd>' + (iec.last_publish_seq == null ? '--' : iec.last_publish_seq) + '</dd></div></dl>'); setHtml('telemetrySummary','<dl><div><dt>YC 实时点</dt><dd>' + Object.keys(values.yc || {}).length + '</dd></div><div><dt>YX 实时点</dt><dd>' + Object.keys(values.yx || {}).length + '</dd></div><div><dt>序号</dt><dd>' + snapshot.sequence + '</dd></div><div><dt>仿真时刻</dt><dd>' + ((snapshot.clock || {}).sim_time || '--') + '</dd></div></dl>'); setHtml('pointCounts','<dl><div><dt>YC</dt><dd>' + (pointSummary.yc || 0) + '</dd></div><div><dt>YX</dt><dd>' + (pointSummary.yx || 0) + '</dd></div><div><dt>YK</dt><dd>' + (pointSummary.yk || 0) + '</dd></div></dl>'); const visiblePoints = state.pointKind === 'all' ? state.points : state.points.filter(point => point.kind === state.pointKind); setHtml('pointTable',visiblePoints.length ? '<table><thead><tr><th>类型</th><th>点号</th><th>名称</th><th>实时值</th><th>单位</th><th>说明</th></tr></thead><tbody>' + visiblePoints.map(point => { const value = (values[point.kind] || {})[point.point_no]; const shown = typeof value === 'boolean' ? (value ? '合' : '分') : fmt(value,point.unit === 'Hz' ? 3 : 2); return '<tr><td>' + point.kind.toUpperCase() + '</td><td>' + point.point_no + '</td><td>' + esc(point.name) + '</td><td class="value">' + shown + '</td><td>' + esc(point.unit) + '</td><td>' + esc(point.description) + '</td></tr>'; }).join('') + '</tbody></table>' : '<p>暂无点表</p>');
}
function bindIecControls() { $('iecStart')?.addEventListener('click',async () => { try { await api('/api/iec104/start',{method:'POST',body:'{}'}); await refresh(); } catch (error) { alert(error.message); } }); $('iecStop')?.addEventListener('click',async () => { try { await api('/api/iec104/stop',{method:'POST',body:'{}'}); await refresh(); } catch (error) { alert(error.message); } }); }
function bindScada() { document.querySelectorAll('[data-point-kind]').forEach(button => button.addEventListener('click', () => { state.pointKind = button.dataset.pointKind; document.querySelectorAll('[data-point-kind]').forEach(item => item.classList.toggle('active', item === button)); if (state.snapshot && state.health) renderScada(state.snapshot, state.health, state.pointSummary || { yc:0,yx:0,yk:0,yt:0 }); })); }

async function refresh() {
  try { const requests = [api('/api/snapshot?history=120'),api('/api/health')]; if (page === 'model' || page === 'scada') requests.push(page === 'model' ? api('/api/scdfe/points') : api('/api/points')); const result = await Promise.all(requests); const snapshot = result[0], health = result[1]; state.snapshot = snapshot; state.health = health; updateClock(snapshot); if (page === 'dashboard') renderDashboard(snapshot,health); if (page === 'model') { state.pointSummary = result[2]; renderModel(snapshot,result[2]); } if (page === 'curves') renderCurves(snapshot); if (page === 'devices') renderDevices(snapshot); if (page === 'scada') { state.points = result[2].items || []; state.pointSummary = await api('/api/scdfe/points'); renderScada(snapshot,health,state.pointSummary); } } catch (error) { console.error(error); }
}
bindClock(); bindTabs(); bindIecControls(); if (page === 'model') bindModel(); if (page === 'curves') bindCurves(); if (page === 'devices') bindDevices(); if (page === 'scada') bindScada(); refresh(); setInterval(refresh,1000);
