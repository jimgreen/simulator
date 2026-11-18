'use strict';
(() => {
  let curves = {}, pageIndex = 0;
  let size = 5;
  const labels = {weather:'环境',load:'总负荷',diesel:'柴发',battery:'储能'};
  const message = (text,error=false) => { const node=document.getElementById('boundaryMessage');node.textContent=text;node.classList.toggle('error-text',error); };
  function preview() {
    const height=document.getElementById('boundaryPreview').clientHeight;
    if(height>0)size=Math.max(1,Math.min(8,Math.floor((height-34)/30)));
    const rows=curves[document.getElementById('boundarySeries').value] || [], pages=Math.max(1,Math.ceil(rows.length/size));
    pageIndex=Math.min(pageIndex,pages-1);
    const visible=rows.slice(pageIndex*size,(pageIndex+1)*size);
    const fields=[...new Set(visible.flatMap(Object.keys))];
    const table=document.createElement('table'),head=document.createElement('thead'),body=document.createElement('tbody');
    const header=document.createElement('tr');
    for(const field of fields){const th=document.createElement('th');th.textContent=field;th.title=field;header.append(th);}
    head.append(header);
    for(const row of visible){const tr=document.createElement('tr');for(const field of fields){const td=document.createElement('td');td.textContent=row[field] ?? '--';td.title=field+': '+td.textContent;tr.append(td);}body.append(tr);}
    table.append(head,body);document.getElementById('boundaryPreview').replaceChildren(table);
    document.getElementById('boundaryPage').textContent=(pageIndex+1)+' / '+pages+' · '+rows.length+' 条';
    document.getElementById('boundaryPrevious').disabled=pageIndex===0;
    document.getElementById('boundaryNext').disabled=pageIndex===pages-1;
  }
  function setCurves(value){
    curves=value;pageIndex=0;const select=document.getElementById('boundarySeries');
    select.replaceChildren(...Object.keys(curves).filter(key=>curves[key].length).map(key=>{const option=document.createElement('option');option.value=key;option.textContent=labels[key] || key;return option;}));preview();
  }
  document.getElementById('boundaryPrevious').onclick=()=>{pageIndex=Math.max(0,pageIndex-1);preview();};
  document.getElementById('boundaryNext').onclick=()=>{pageIndex++;preview();};
  document.getElementById('boundarySeries').onchange=()=>{pageIndex=0;preview();};
  document.querySelector('[data-tab="boundary"]').addEventListener('click',()=>requestAnimationFrame(preview));
  window.addEventListener('resize',()=>{pageIndex=0;preview();});
  document.getElementById('importBoundary').onclick=async()=>{
    const file=document.getElementById('boundaryFile').files[0];if(!file)return message('请选择边界数据文件',true);
    const button=document.getElementById('importBoundary');button.disabled=true;message('正在校验并加载…');
    try{
      if(file.size>32*1024*1024)throw new Error('文件不能超过 32 MB');
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
      for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
      const response=await fetch('/api/boundary/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,data_base64:btoa(binary)})});
      const result=await response.json();if(!response.ok)throw new Error(result.error);
      setCurves(result.curves);message('已加载 '+result.source+' · '+result.rows+' 条记录'+(result.warnings?.length?'；'+result.warnings.join('；'):''));
      message(document.getElementById('boundaryMessage').textContent+'；编辑器中点击“读取当前曲线”可载入最新数据');
      // Do not overwrite an unsaved editor buffer; explicit reload is available.
    }catch(error){message(error.message,true);}finally{button.disabled=false;}
  };
  document.getElementById('downloadBoundaryExample').onclick=()=>{
    const blob=new Blob(['\uFEFFtime,wind_speed_mps,solar_irradiance_w_m2,air_temp_c,load_kw\n00:00,7,0,-20,160\n12:00,10,850,-10,210\n23:59,7,0,-20,160\n'],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='boundary-example.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  fetch('/api/curves').then(response=>response.json()).then(result=>setCurves(result.curves)).catch(error=>message(error.message,true));
})();
