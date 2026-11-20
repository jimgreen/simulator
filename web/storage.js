'use strict';
(() => {
  const $=id=>document.getElementById(id);
  let rows=[],page=0,size=8,busy=false;
  const labels={'/api/clock':'仿真时钟','/api/curves':'曲线保存','/api/boundary/import':'边界加载','/api/diagram/import':'SVG 加载','/api/topology':'拓扑修改','/api/devices/state':'设备投退','/api/devices/states':'批量投退','/api/devices/actions':'设备操作','/api/devices/operate':'图形操作','/api/scenario':'场景切换','/api/commands':'遥控命令','/api/model/source':'电网数据源','/api/preferences':'页面设置','/api/iec104/start':'启动 IEC104','/api/iec104/stop':'停止 IEC104','/api/scdfe/points/generate':'生成四遥点表'};
  function render() {
    const pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(page,pages-1);
    $('storageRows').replaceChildren(...rows.slice(page*size,(page+1)*size).map(row=>{
      const tr=document.createElement('tr');
      for(const value of [new Date(row.created_at).toLocaleString('zh-CN'),labels[row.action] || row.action,JSON.stringify(row.detail)]){const td=document.createElement('td');td.textContent=value;td.title=value;tr.append(td);}
      return tr;
    }));
    $('storagePage').textContent=(page+1)+' / '+pages;$('storagePrevious').disabled=page===0;$('storageNext').disabled=page===pages-1;
  }
  async function refresh() {
    if(busy)return;busy=true;
    try {
      const [status,journal]=await Promise.all(['/api/storage','/api/storage/operations?limit=200'].map(async path=>{const response=await fetch(path),data=await response.json();if(!response.ok)throw new Error(data.error);return data;}));
      $('storageDatabase').textContent=status.database;
      $('storageSavedAt').textContent=status.last_saved_at?new Date(status.last_saved_at).toLocaleString('zh-CN'):'--';
      $('storageCount').textContent=status.operation_count;$('storageRestored').textContent=status.restored?'已恢复保存状态':'本次建立状态';
      $('storageStatus').textContent=status.last_error?'保存异常':'SQLite 已保存';$('storageStatus').className='badge '+(status.last_error?'error':'ok');
      $('storageError').textContent=status.last_error || '';rows=journal.items;render();
    } catch(error){$('storageError').textContent=error.message;}finally{busy=false;}
  }
  $('refreshStorage').onclick=refresh;$('storagePrevious').onclick=()=>{page--;render();};$('storageNext').onclick=()=>{page++;render();};
  new ResizeObserver(()=>{size=Math.max(1,Math.floor(($('storageTableSpace').clientHeight-35)/34));render();}).observe($('storageTableSpace'));
  refresh();setInterval(refresh,5000);
})();
