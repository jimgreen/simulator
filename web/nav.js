'use strict';
(() => {
  const links = [
    ['/', '总览'],
    ['/trend.html', '趋势'],
    ['/diagnostics.html', '诊断'],
    ['/events.html', '事件'],
    ['/model.html', '模型导入'],
    ['/model-summary.html', '模型摘要'],
    ['/curves.html', '曲线编辑'],
    ['/boundary.html', '边界导入'],
    ['/realtime.html', '实时曲线'],
    ['/diagram.html', '电网图形'],
    ['/devices.html', '设备操作'],
    ['/topology.html', '拓扑编辑'],
    ['/flow.html', '潮流状态'],
    ['/scada.html', 'IEC 104 服务'],
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
  });
})();
