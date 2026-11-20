'use strict';
(() => {
  const set = (id, value) => { document.getElementById(id).textContent = value; };
  async function refresh() {
    try {
      const response = await fetch('/api/scdfe/realtime', {cache:'no-store'});
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || '读取写库状态失败');
      set('writeStatus', value.last_error ? '写入失败 · 自动重试' : value.pending ? '正在写入' : value.batches ? '已同步' : '等待数据');
      document.getElementById('writeStatus').className = 'badge ' + (value.last_error ? 'error' : 'ok');
      set('writeDatabase', value.database);
      set('deviceDatabase', value.device_database || '未配置');
      set('writeTarget', `${value.rtu_id} / ${value.channel_id}`);
      set('writePoints', value.written_points);
      set('writeTime', value.last_commit_ms ? new Date(value.last_commit_ms).toLocaleTimeString('zh-CN', {hour12:false}) : '--');
      set('writeSimTime', value.last_sim_time || '--');
      set('writeDuration', value.last_duration_ms == null ? '--' : `${value.last_duration_ms} ms`);
      set('writeBatches', value.batches);
      set('writeSerial', `${value.devices_committed} / ${value.points_committed} / ${value.submitted}`);
      set('deviceWriteSummary', `设备记录 ${value.written_devices} 条 · 两库帧号${value.last_device_frame && value.last_device_frame === value.last_point_frame ? '一致' : '等待同步'}`);
      set('mappingSummary', value.mapping_database ? `量测映射：${value.mapping_database} · 有效 ${value.valid_points || 0} / ${value.mapped_points || 0} 点，其余标记无效质量` : '按当前模型生成发布点号');
      set('writeRetries', `${value.coalesced} / ${value.failures}`);
      set('writeError', value.last_error || '');
    } catch (error) {
      set('writeStatus', '连接异常');
      set('writeError', error.message);
    } finally { setTimeout(refresh, 1000); }
  }
  refresh();
})();
