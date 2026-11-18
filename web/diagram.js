'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const shadow = $('svgHost').attachShadow({mode:'open'});
  const menu = $('diagramMenu'), viewport = $('diagramViewport');
  let snapshot, svg, drawingKey = '', bindings = [], graphics = [], selectedId = '', busy = false, pending = false, menuRevision;
  let originalBox = [0, 0, 1000, 800], box = [...originalBox], drag = null;
  let devices = new Map(), names = new Map();
  const valueText = value => value == null || !Number.isFinite(Number(value)) ? '--' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits:3});
  const message = (text, error=false) => { $('diagramNotice').textContent = text; $('diagramNotice').classList.toggle('error-text',error); };
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '请求失败');
    return result;
  }
  function indexDevices(rows) {
    devices = new Map(); names = new Map();
    for (const row of rows) {
      for (const alias of [row.id, ...(row.aliases || [])]) devices.set(alias, row);
      const key = row.block + '\0' + row.name;
      names.set(key, row);
      // An ambiguous unqualified name must not operate the wrong device.
      names.set(row.name, names.has(row.name) ? null : row);
    }
  }
  function resolve(element) {
    if (!element) return null;
    const owner = element.closest('[dev-id], [dev], use[id][name], [data-device-id]');
    if (!owner) return null;
    const id = owner.getAttribute('dev-id') || owner.getAttribute('dev') || owner.getAttribute('data-device-id') || owner.id;
    return devices.get(id) || names.get((owner.closest('[device-type]')?.getAttribute('device-type') || '') + '\0' + owner.getAttribute('name')) || names.get(owner.getAttribute('name'));
  }
  function currentDevice() { return devices.get(selectedId); }
  function selectDevice(device) {
    selectedId = device?.id || '';
    $('selectedMenu').disabled = !device;
    $('deviceSearch').value = device?.name || '';
    paint();
  }
  function setBox() {
    if (svg) svg.setAttribute('viewBox', box.join(' '));
    $('zoomLabel').textContent = Math.round(originalBox[2] / box[2] * 100) + '%';
  }
  function fit() { box = [...originalBox]; setBox(); }
  function zoom(factor, clientX, clientY) {
    if (!svg) return;
    const scale = originalBox[2] / (box[2] * factor);
    if (scale < .15 || scale > 40) return;
    const point = svg.createSVGPoint();
    point.x = clientX ?? viewport.getBoundingClientRect().left + viewport.clientWidth / 2;
    point.y = clientY ?? viewport.getBoundingClientRect().top + viewport.clientHeight / 2;
    const anchor = point.matrixTransform(svg.getScreenCTM().inverse());
    box = [anchor.x - (anchor.x-box[0])*factor, anchor.y-(anchor.y-box[1])*factor, box[2]*factor, box[3]*factor];
    setBox();
  }
  function metricValue(element, device) {
    for (const attr of ['data-meas-name','data-scada-name','data-real-name','data-control-name']) {
      if (element.hasAttribute(attr)) {
        const row = snapshot.diagram_measurements?.[element.getAttribute(attr)];
        if (!row) return null;
        const metric = (element.getAttribute('mti') || element.getAttribute('mt') || '').toLowerCase();
        return row.meas_type === 'SOC' && ['level','soc','stateofcharge'].includes(metric) && row.value != null ? row.value * 100 : row.value;
      }
    }
    if (!device) return null;
    const metric = (element.getAttribute('mti') || element.getAttribute('mt') || '').toLowerCase().replace(/[\s_-]/g,'');
    if (['p','activepower','pgen','pload','power'].includes(metric)) return device.p_kw;
    if (['level','soc','stateofcharge'].includes(metric)) return device.soc_pct;
    if (['status','closedstatus','switchstatus'].includes(metric)) return device.type === 'switch' ? Number(device.closed_status) : Number(device.running);
    if (['runstat','running'].includes(metric)) return Number(device.running);
    if (['availablepower','pmax'].includes(metric)) return device.available_kw;
    return null;
  }
  function paint() {
    if (!svg || !snapshot) return;
    for (const binding of bindings) {
      const value = metricValue(binding.element, devices.get(binding.id));
      const shown = valueText(value);
      if (binding.previous !== shown) {
        if (['text','tspan'].includes(binding.element.localName)) binding.element.textContent = shown;
        else binding.element.setAttribute('data-current-value', shown);
        binding.element.setAttribute('data-bound-value', shown);
        binding.previous = shown;
      }
      binding.element.style.visibility = $('showValues').checked ? '' : 'hidden';
    }
    for (const binding of graphics) {
      const device = devices.get(binding.id), element = binding.element;
      element.classList.toggle('runtime-offline', !!device && !device.running);
      element.classList.toggle('runtime-selected', device?.id === selectedId);
      if (device?.type === 'switch' && element.localName === 'use') {
        const href = element.getAttribute(device.closed_status ? 'data-closed-href' : 'data-open-href') ||
          binding.href.replace(/_state_[01](?=(?:_\d+)?(?:$|[?#]))/, '_state_' + Number(device.closed_status));
        if (href && href !== element.getAttribute('href')) {
          element.setAttribute('href', href);
          element.setAttributeNS('http://www.w3.org/1999/xlink', 'href', href);
        }
        element.setAttribute('data-closed-status', Number(device.closed_status));
      }
    }
    if ($('deviceDialog').open) showDetails(false);
  }
  function compile(text) {
    const documentSvg = new DOMParser().parseFromString(text,'image/svg+xml');
    if (documentSvg.querySelector('parsererror')) throw new Error('SVG 解析失败');
    const root = documentSvg.documentElement;
    svg = document.importNode(root, true);
    const style = document.createElement('style');
    style.textContent = ':host{display:block;width:100%;height:100%}svg{display:block;width:100%;height:100%;user-select:none}.runtime-offline{opacity:.35;filter:grayscale(1)}.runtime-selected{filter:drop-shadow(0 0 5px #008fce)}[dev-id],use[id][name]{cursor:pointer}';
    shadow.replaceChildren(style, svg);
    const raw = (svg.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
    originalBox = raw.length === 4 && raw.every(Number.isFinite) && raw[2] > 0 && raw[3] > 0 ? raw : [0,0,parseFloat(svg.getAttribute('width')) || 1000,parseFloat(svg.getAttribute('height')) || 800];
    svg.setAttribute('width','100%'); svg.setAttribute('height','100%');
    svg.setAttribute('preserveAspectRatio','xMidYMid meet');
    graphics = [...svg.querySelectorAll('[dev-id], use[id][name], [data-device-id]')].map(element => ({element,id:resolve(element)?.id,href:element.getAttribute('href') || element.getAttributeNS('http://www.w3.org/1999/xlink','href') || ''}));
    bindings = [...svg.querySelectorAll('[dev] [mt], [dev] [mti], [data-meas-name], [data-scada-name], [data-real-name], [data-control-name]')].map(element => ({element,id:resolve(element)?.id}));
    const bound = graphics.filter(g => g.id).length;
    $('bindingStats').textContent = '图元 ' + bound + '/' + graphics.length + ' · 测量 ' + bindings.length;
    $('diagramEmpty').hidden = true;
    svg.addEventListener('contextmenu', event => { event.preventDefault(); openMenu(resolve(event.target), event.clientX, event.clientY); });
    svg.addEventListener('click', event => { if (!drag?.moved) selectDevice(resolve(event.target)); });
    svg.addEventListener('pointermove', event => {
      if (drag || !menu.hidden) return;
      const device = resolve(event.target), tip = $('diagramTooltip');
      tip.hidden = !device;
      if (!device) return;
      tip.textContent = device.name + '\n' + (device.running ? '投入' : '退出 / 拓扑隔离') + (device.type === 'switch' ? ' · ' + (device.closed_status ? '合位' : '分位') : '\n有功 ' + valueText(device.p_kw) + ' kW');
      const rect = viewport.getBoundingClientRect();
      tip.style.left = Math.max(4,Math.min(event.clientX-rect.left+12, rect.width-tip.offsetWidth-8))+'px';
      tip.style.top = Math.max(4,Math.min(event.clientY-rect.top+12, rect.height-tip.offsetHeight-8))+'px';
    });
    svg.addEventListener('pointerleave', () => { $('diagramTooltip').hidden = true; });
    fit(); paint();
  }
  function closeMenu() { menu.hidden = true; }
  function openMenu(device, x, y) {
    menuRevision = snapshot?.diagram.model_revision;
    selectDevice(device);
    menu.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = device?.name || '图形视图'; menu.append(title);
    const add = (label, action, disabled=false) => {
      const button = document.createElement('button'); button.textContent = label; button.setAttribute('role','menuitem'); button.disabled = disabled;
      button.onclick = () => { closeMenu(); action(); }; menu.append(button);
    };
    if (device) {
      add('查看实时状态', () => showDetails());
      add(device.run ? '退出设备' : '投入设备', () => operate(device.id, device.run ? 'stop' : 'start'), busy);
      if (device.type === 'switch') {
        add('合闸', () => operate(device.id,'close'), busy || device.closed_status || !device.run);
        add('分闸', () => operate(device.id,'open'), busy || !device.closed_status);
      }
    } else {
      add('适应窗口', fit); add('放大', () => zoom(.8)); add('缩小', () => zoom(1.25));
      add($('showValues').checked ? '隐藏测量数值' : '显示测量数值', () => { $('showValues').checked = !$('showValues').checked; paint(); });
      add('刷新实时数据', () => refresh());
    }
    menu.hidden = false;
    menu.style.left = Math.max(8,Math.min(x,window.innerWidth-menu.offsetWidth-8))+'px';
    menu.style.top = Math.max(8,Math.min(y,window.innerHeight-menu.offsetHeight-8))+'px';
    menu.querySelector('button:not(:disabled)')?.focus();
  }
  async function operate(id, action) {
    if (busy) return;
    busy = true;
    try { await api('/api/devices/operate', {device_id:id, action, model_revision:menuRevision}); await refresh(); message('已执行：' + ({start:'投入',stop:'退出',open:'分闸',close:'合闸'}[action]) + '，状态与实时点已更新'); }
    catch (error) { message(error.message,true); }
    finally { busy = false; }
  }
  function showDetails(open=true) {
    const d = currentDevice();
    if (!d) { $('deviceDialog').close(); return; }
    $('deviceTitle').textContent = d.name;
    const details = [['编号', d.id],['设备类型',d.block || d.type],['请求状态',d.run ? '投入':'退出'],['实时状态',d.running ? '运行':'退出 / 拓扑隔离'],['实际分合',d.type === 'switch' ? (d.closed_status ? '合位':'分位') : '--'],['有功',valueText(d.p_kw)+' kW'],['可用上限',valueText(d.available_kw)+' kW'],['储能 SOC',valueText(d.soc_pct)+' %']];
    $('deviceDetails').replaceChildren(...details.map(([label,value]) => { const row=document.createElement('div'), dt=document.createElement('dt'), dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;row.append(dt,dd);return row; }));
    if (open && !$('deviceDialog').open) $('deviceDialog').showModal();
  }
  async function refresh() {
    if (pending) return;
    pending = true;
    try {
      snapshot = await api('/api/snapshot?history=1');
      indexDevices(snapshot.devices || []);
      $('simTime').textContent = snapshot.clock.sim_time;
      $('runState').textContent = (snapshot.clock.running ? '运行中':'已暂停') + ' · ' + snapshot.clock.speed + '×';
      const key = snapshot.diagram.model_revision + ':' + snapshot.diagram.revision;
      if (key !== drawingKey) {
        closeMenu();
        const diagram = await api('/api/diagram');
        if (diagram.model_revision !== snapshot.diagram.model_revision || diagram.revision !== snapshot.diagram.revision) return;
        if (diagram.available) compile(diagram.svg);
        else { shadow.replaceChildren(); svg=null; bindings=[]; graphics=[]; $('diagramEmpty').hidden=false; $('bindingStats').textContent='未加载'; }
        drawingKey=key; selectDevice(null);
        $('deviceOptions').replaceChildren(...snapshot.devices.map(d => { const option=document.createElement('option');option.value=d.id;option.label=d.name;return option; }));
        $('diagramSource').textContent = snapshot.model.name + ' · ' + (diagram.source || '无图形');
      }
      if (selectedId && !devices.has(selectedId)) selectDevice(null);
      paint();
    } catch(error) { message('刷新失败：'+error.message,true); }
    finally { pending=false; }
  }
  $('importSvg').onclick = async () => {
    const file=$('svgFile').files[0]; if (!file) return message('请选择 SVG 文件',true);
    const button=$('importSvg');button.disabled=true;
    try { if(file.size>4*1024*1024) throw new Error('SVG 文件不能超过 4 MB');
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
      for(let i=0;i<bytes.length;i+=32768) binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      await api('/api/diagram/import',{filename:file.name,data_base64:btoa(binary)});
      drawingKey=''; await refresh();message('SVG 已加载；可右键设备操作，未匹配设备的图元仅展示');
    } catch(error) { message(error.message,true); } finally { button.disabled=false; }
  };
  $('fitDiagram').onclick=fit; $('zoomIn').onclick=()=>zoom(.8); $('zoomOut').onclick=()=>zoom(1.25);
  $('refreshDiagram').onclick=()=>refresh(); $('showValues').onchange=paint;
  $('closeDeviceDialog').onclick=()=>$('deviceDialog').close();
  $('selectedMenu').onclick=()=>{const r=$('selectedMenu').getBoundingClientRect();openMenu(currentDevice(),r.left,r.bottom+4);};
  $('locateDevice').onclick=()=>{
    const query=$('deviceSearch').value.trim(), d=devices.get(query) || names.get(query);
    const graphic=graphics.find(g=>g.id===d?.id && g.element.localName!=='g') || graphics.find(g=>g.id===d?.id);
    if(!d || !graphic) return message('未找到唯一匹配的设备图元，请使用设备编号',true);
    selectDevice(d);
    const rect=graphic.element.getBoundingClientRect(), p=svg.createSVGPoint();p.x=rect.left+rect.width/2;p.y=rect.top+rect.height/2;
    const center=p.matrixTransform(svg.getScreenCTM().inverse());box=[center.x-originalBox[2]/8,center.y-originalBox[3]/8,originalBox[2]/4,originalBox[3]/4];setBox();message('已定位 '+d.name);
  };
  document.querySelectorAll('[data-clock]').forEach(button=>button.onclick=async()=>{try{await api('/api/clock',{action:button.dataset.clock});await refresh();}catch(error){message(error.message,true);}});
  viewport.addEventListener('wheel', event=>{event.preventDefault();zoom(event.deltaY<0?.85:1/.85,event.clientX,event.clientY);},{passive:false});
  viewport.addEventListener('contextmenu',event=>{if(event.composedPath().includes(svg)) return;event.preventDefault();openMenu(null,event.clientX,event.clientY);});
  viewport.addEventListener('pointerdown',event=>{if(event.button!==0 || !svg)return;closeMenu();drag={x:event.clientX,y:event.clientY,box:[...box],moved:false};});
  window.addEventListener('pointermove',event=>{
    if(!drag || !svg || !(event.buttons&1))return;
    if(Math.abs(event.clientX-drag.x)+Math.abs(event.clientY-drag.y)>4)drag.moved=true;
    const scale=svg.getScreenCTM();box=[drag.box[0]-(event.clientX-drag.x)/scale.a,drag.box[1]-(event.clientY-drag.y)/scale.d,drag.box[2],drag.box[3]];setBox();$('diagramTooltip').hidden=true;
  });
  window.addEventListener('pointerup',()=>{setTimeout(()=>{drag=null;},0);});
  document.addEventListener('pointerdown',event=>{if(!menu.contains(event.target))closeMenu();});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'){closeMenu();$('diagramTooltip').hidden=true;}
    if(!menu.hidden && ['ArrowDown','ArrowUp'].includes(event.key)){
      event.preventDefault();const buttons=[...menu.querySelectorAll('button:not(:disabled)')],i=buttons.indexOf(document.activeElement);buttons[(i+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();
    }
  });
  window.addEventListener('resize',closeMenu);
  refresh();setInterval(refresh,1000);
})();
