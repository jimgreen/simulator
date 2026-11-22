/**
 * 极地微电网 Web 前端通用人机交互增强引擎（UX Enhancements）
 * 提供：
 * 1. 全局快捷命令面板（Ctrl+K / Cmd+K）与 Alt+1~9 快捷切页；
 * 2. 异常/日志详情一键定位接线图设备（locateDeviceOnDiagram）与一键复制；
 * 3. 核心工程数据表表头三态点击排序（aria-sort）；
 * 4. 切页/切模型 2px 顶部微进度条反馈。
 */
(function initPolarUxEnhancements() {
  if (typeof document === "undefined" || typeof window === "undefined") return;
  if (window.__polarUxEnhancementsReady) return;
  window.__polarUxEnhancementsReady = true;

  const tr = (text) => (typeof translatePhrase === "function" ? translatePhrase(text) : text);

  /**
   * 顶部 2px 轻量加载进度条（切页 / 切模型时提供顺滑微反馈，消除白屏错觉）
   */
  let progressBarEl = null;
  let progressHideTimer = null;
  function flashTopProgress() {
    if (!progressBarEl) {
      const main = document.querySelector(".page-main") || document.body;
      if (!main) return;
      progressBarEl = document.createElement("div");
      progressBarEl.className = "ux-top-progress";
      progressBarEl.setAttribute("aria-hidden", "true");
      main.prepend(progressBarEl);
    }
    clearTimeout(progressHideTimer);
    progressBarEl.classList.remove("is-done");
    progressBarEl.classList.add("is-active");
    progressHideTimer = setTimeout(() => {
      progressBarEl.classList.add("is-done");
      setTimeout(() => progressBarEl.classList.remove("is-active", "is-done"), 220);
    }, 260);
  }

  function getCurrentSnapshotDevices() {
    if (typeof state === "undefined" || !state) return [];
    if (Array.isArray(state.snapshot?.devices)) return state.snapshot.devices;
    if (Array.isArray(state.localSnapshot?.devices)) return state.localSnapshot.devices;
    if (Array.isArray(state.devices)) return state.devices;
    return [];
  }

  /**
   * 统一跳转接线图并选中高亮目标设备
   */
  function locateDeviceOnDiagram(devName) {
    const targetName = String(devName || "").trim();
    if (!targetName) return false;
    if (typeof showPage === "function") {
      showPage("diagram");
    } else {
      document.querySelector('.page-nav button[data-nav-page="diagram"]')?.click();
    }
    const devices = getCurrentSnapshotDevices();
    const matched = devices.find((d) => {
      const name = String(d?.name || d?.dev_name || d?.id || "").trim();
      return name === targetName || (name && targetName.includes(name));
    });
    const resolvedKey = matched
      ? (typeof deviceKey === "function" ? deviceKey(matched) : `${matched.dev_type || matched.type || ""}:${matched.name || matched.dev_name || ""}`)
      : targetName;
    setTimeout(() => {
      if (typeof setDiagramSelectedDevice === "function") {
        try {
          setDiagramSelectedDevice(resolvedKey, { focus: true, center: true });
        } catch (_e) {
          try { setDiagramSelectedDevice(targetName); } catch (_e2) {}
        }
      }
    }, 60);
    if (typeof showUiToast === "function") {
      showUiToast(`${tr("定位接线图")}: ${targetName}`, "info", 1800);
    }
    return true;
  }
  window.locateDeviceOnDiagram = locateDeviceOnDiagram;

  /**
   * 复制文本到剪贴板并给出轻量 Toast 反馈
   */
  async function copyTextWithFeedback(rawText) {
    const val = String(rawText || "").trim();
    if (!val) return;
    try {
      await navigator.clipboard.writeText(val);
      if (typeof showUiToast === "function") {
        showUiToast(tr("已复制到剪贴板"), "ok", 1800);
      }
    } catch (_err) {
      // 降级静默处理
    }
  }

  /**
   * 全局快捷命令面板（Ctrl+K / Cmd+K）
   */
  let paletteDialog = null;
  let paletteInput = null;
  let paletteList = null;
  let paletteItems = [];
  let paletteActiveIdx = 0;

  function buildCommandPaletteItems() {
    const items = [];
    // 1. 一级导航页签
    document.querySelectorAll(".page-nav button[data-nav-page]").forEach((btn, idx) => {
      const page = btn.dataset.navPage;
      const label = (btn.textContent || "").trim();
      items.push({
        group: tr("主页"),
        label,
        hint: idx < 9 ? `Alt+${idx + 1}` : "Alt+0",
        keywords: `${label} ${page}`,
        run: () => {
          btn.click();
          flashTopProgress();
        },
      });
    });
    const scadaLink = document.querySelector(".page-nav a.scada104-link");
    if (scadaLink) {
      const label = (scadaLink.textContent || "").trim();
      items.push({
        group: tr("主页"),
        label,
        hint: "/simulator104",
        keywords: `${label} scada iec104`,
        run: () => window.open(scadaLink.getAttribute("href") || "/simulator104", "_blank", "noopener"),
      });
    }
    // 2. 当前模型设备（直达接线图定位）
    const devices = getCurrentSnapshotDevices();
    const seenDev = new Set();
    for (let i = 0; i < devices.length && seenDev.size < 160; i += 1) {
      const d = devices[i];
      const name = String(d?.name || d?.dev_name || "").trim();
      const devType = String(d?.dev_type || d?.type || "").trim();
      if (!name || seenDev.has(name)) continue;
      seenDev.add(name);
      items.push({
        group: tr("设备"),
        label: name,
        hint: devType,
        keywords: `${name} ${devType} diagram 接线图`,
        run: () => locateDeviceOnDiagram(name),
      });
    }
    // 3. 8 套视觉风格一键切换
    if (typeof UI_THEME_PRESETS !== "undefined" && Array.isArray(UI_THEME_PRESETS)) {
      UI_THEME_PRESETS.forEach((preset) => {
        const label = typeof t === "function" ? t(`theme.${preset.id}`) : preset.label;
        items.push({
          group: tr("风格"),
          label,
          hint: preset.id,
          keywords: `${label} ${preset.label} ${preset.id} theme 风格`,
          run: () => {
            if (typeof applyUiTheme === "function") {
              applyUiTheme(preset.id, { persist: true, notify: true, redraw: true });
            }
          },
        });
      });
    }
    // 4. 3 种语言一键切换
    if (typeof SUPPORTED_LANGS !== "undefined" && Array.isArray(SUPPORTED_LANGS)) {
      SUPPORTED_LANGS.forEach((lang) => {
        items.push({
          group: tr("语言"),
          label: lang.label,
          hint: lang.code,
          keywords: `${lang.label} ${lang.code} lang language 语言`,
          run: () => {
            if (typeof applyUiLanguage === "function") {
              applyUiLanguage(lang.code, { persist: true, notify: true, redraw: true });
            }
          },
        });
      });
    }
    return items;
  }

  function renderPaletteList() {
    if (!paletteList || !paletteInput) return;
    const q = paletteInput.value.trim().toLowerCase();
    const all = buildCommandPaletteItems();
    paletteItems = q
      ? all.filter((it) => `${it.label} ${it.hint} ${it.keywords}`.toLowerCase().includes(q)).slice(0, 24)
      : all.slice(0, 18);
    if (paletteActiveIdx >= paletteItems.length) paletteActiveIdx = 0;
    paletteList.replaceChildren();
    if (!paletteItems.length) {
      const li = document.createElement("li");
      li.className = "ux-palette-empty";
      li.textContent = "—";
      paletteList.appendChild(li);
      return;
    }
    paletteItems.forEach((item, idx) => {
      const li = document.createElement("li");
      li.className = `ux-palette-item${idx === paletteActiveIdx ? " is-active" : ""}`;
      li.setAttribute("role", "option");
      const badge = document.createElement("span");
      badge.className = "ux-palette-group";
      badge.textContent = item.group;
      const title = document.createElement("span");
      title.className = "ux-palette-label";
      title.textContent = item.label;
      const hint = document.createElement("span");
      hint.className = "ux-palette-hint";
      hint.textContent = item.hint || "";
      li.append(badge, title, hint);
      li.addEventListener("mouseenter", () => {
        paletteActiveIdx = idx;
        paletteList.querySelectorAll(".ux-palette-item").forEach((node, i) => {
          node.classList.toggle("is-active", i === idx);
        });
      });
      li.addEventListener("click", () => {
        closeCommandPalette();
        item.run();
      });
      paletteList.appendChild(li);
    });
  }

  function ensureCommandPalette() {
    if (paletteDialog) return;
    paletteDialog = document.createElement("dialog");
    paletteDialog.id = "uxCommandPalette";
    paletteDialog.className = "ux-command-palette";
    paletteDialog.innerHTML = `
      <div class="ux-palette-card">
        <div class="ux-palette-head">
          <input id="uxPaletteInput" type="search" autocomplete="off" placeholder="${tr("快速跳转或搜索命令、页签与设备…")}" />
          <kbd>Esc</kbd>
        </div>
        <ul id="uxPaletteList" class="ux-palette-list" role="listbox"></ul>
      </div>
    `;
    document.body.appendChild(paletteDialog);
    paletteInput = document.getElementById("uxPaletteInput");
    paletteList = document.getElementById("uxPaletteList");

    paletteDialog.addEventListener("click", (event) => {
      if (event.target === paletteDialog) closeCommandPalette();
    });
    paletteInput?.addEventListener("input", () => {
      paletteActiveIdx = 0;
      renderPaletteList();
    });
    paletteInput?.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (paletteItems.length) {
          paletteActiveIdx = (paletteActiveIdx + 1) % paletteItems.length;
          renderPaletteList();
        }
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        if (paletteItems.length) {
          paletteActiveIdx = (paletteActiveIdx - 1 + paletteItems.length) % paletteItems.length;
          renderPaletteList();
        }
      } else if (event.key === "Enter") {
        event.preventDefault();
        const item = paletteItems[paletteActiveIdx];
        if (item) {
          closeCommandPalette();
          item.run();
        }
      }
    });
  }

  function openCommandPalette() {
    ensureCommandPalette();
    if (!paletteDialog || paletteDialog.open) return;
    if (paletteInput) {
      paletteInput.placeholder = tr("快速跳转或搜索命令、页签与设备…");
      paletteInput.value = "";
    }
    paletteActiveIdx = 0;
    renderPaletteList();
    if (typeof paletteDialog.showModal === "function") {
      paletteDialog.showModal();
    }
    paletteInput?.focus();
  }

  function closeCommandPalette() {
    if (paletteDialog?.open) paletteDialog.close();
  }

  /**
   * 通用工程表格表头点击三态排序（不干扰列宽拖拽手柄）
   */
  const SORTABLE_TABLES = "table.measurement-compare-table, table.runtime-device-table, table.model-param-table, table.runtime-command-table";
  function parseCellSortValue(cell) {
    const raw = (cell?.textContent || "").trim();
    if (!raw || raw === "--" || raw === "—") return { num: null, text: "" };
    const cleaned = raw.replace(/[,%]/g, "").replace(/\s*(kW|kVar|kV|A|Hz|MPa|℃|m\/s|W\/m²|Nm3\/h|min|s)$/i, "").trim();
    const num = Number(cleaned);
    if (cleaned !== "" && Number.isFinite(num)) return { num, text: raw };
    return { num: null, text: raw };
  }

  function bindTableSorting() {
    document.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target || target.closest("input, select, button, .col-resizer, .runtime-log-col-resizer")) return;
      const th = target.closest("thead th");
      if (!th) return;
      const table = th.closest(SORTABLE_TABLES);
      if (!table) return;
      const tbody = table.tBodies && table.tBodies[0];
      if (!tbody || tbody.rows.length < 2) return;
      const row = th.parentElement;
      if (!row) return;
      const colIndex = Array.prototype.indexOf.call(row.children, th);
      if (colIndex < 0) return;

      const cur = th.getAttribute("aria-sort") || "none";
      const next = cur === "ascending" ? "descending" : (cur === "descending" ? "none" : "ascending");
      Array.from(row.children).forEach((cell) => cell.setAttribute("aria-sort", cell === th ? next : "none"));
      const rows = Array.from(tbody.rows).filter((r) => !r.classList.contains("virtual-table-spacer"));
      if (next === "none") {
        rows.sort((a, b) => Number(a.dataset.origIdx || 0) - Number(b.dataset.origIdx || 0));
      } else {
        rows.forEach((r, i) => {
          if (!r.dataset.origIdx) r.dataset.origIdx = String(i);
        });
        const dir = next === "ascending" ? 1 : -1;
        rows.sort((a, b) => {
          const va = parseCellSortValue(a.cells[colIndex]);
          const vb = parseCellSortValue(b.cells[colIndex]);
          if (va.num !== null && vb.num !== null) return (va.num - vb.num) * dir;
          if (va.num !== null) return -1 * dir;
          if (vb.num !== null) return 1 * dir;
          return va.text.localeCompare(vb.text, "zh-CN") * dir;
        });
      }
      tbody.append(...rows);
    });
  }

  /**
   * 为运行日志详情弹窗自动注入“复制文本”与“定位接线图”快捷按钮
   */
  function enhanceLogDetailDialog() {
    const dialog = document.getElementById("runtimeLogDetailDialog");
    if (!dialog) return;
    const actionBar = dialog.querySelector(".runtime-log-detail-actions, .dialog-actions, .runtime-log-detail-head, .dialog-head, .modal-head, header");
    if (!actionBar || actionBar.querySelector(".ux-log-copy-btn")) return;
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "compact-action-btn ux-log-copy-btn";
    copyBtn.textContent = tr("复制文本");
    copyBtn.addEventListener("click", () => {
      const metaText = dialog.querySelector("#runtimeLogDetailMeta, .runtime-log-detail-meta")?.textContent || "";
      const bodyText = dialog.querySelector("#runtimeLogDetailBody, .runtime-log-detail-content, pre")?.textContent || dialog.textContent || "";
      copyTextWithFeedback([metaText.trim(), bodyText.trim()].filter(Boolean).join("\n"));
    });
    const locateBtn = document.createElement("button");
    locateBtn.type = "button";
    locateBtn.className = "compact-action-btn ux-log-locate-btn";
    locateBtn.textContent = tr("定位接线图");
    locateBtn.addEventListener("click", () => {
      const targetText = [
        dialog.querySelector("#runtimeLogDetailMeta, .runtime-log-detail-meta")?.textContent || "",
        dialog.querySelector("#runtimeLogDetailBody")?.textContent || "",
      ].join(" ");
      const devices = getCurrentSnapshotDevices();
      const found = devices.find((d) => {
        const nm = String(d?.name || d?.dev_name || "").trim();
        return nm && targetText.includes(nm);
      });
      if (found) {
        if (dialog.open) dialog.close();
        locateDeviceOnDiagram(found.name || found.dev_name);
      } else if (typeof showUiToast === "function") {
        showUiToast(tr("未在日志对象中匹配到设备"), "warn", 1800);
      }
    });
    const closeBtn = actionBar.querySelector("button");
    if (closeBtn) {
      actionBar.insertBefore(copyBtn, closeBtn);
      actionBar.insertBefore(locateBtn, closeBtn);
    } else {
      actionBar.append(copyBtn, locateBtn);
    }
  }

  /**
   * 共享左侧导航边栏折叠/展开与持久化（双端通用）
   */
  const SPLIT_STATE_STORAGE_KEY = (() => {
    const isTrainee = Boolean(document.getElementById("traineeRunToggle"));
    return isTrainee ? "polarTraineeHorizontalSplitsV1" : "polarSimulatorHorizontalSplitsV1";
  })();

  function readHorizontalSplitStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(SPLIT_STATE_STORAGE_KEY) || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    } catch (_e) {}
    return {};
  }

  function writeHorizontalSplitEntry(key, entry) {
    try {
      const store = readHorizontalSplitStore();
      store[key] = entry;
      localStorage.setItem(SPLIT_STATE_STORAGE_KEY, JSON.stringify(store));
    } catch (_e) {}
  }

  function dispatchLayoutResize() {
    try {
      window.dispatchEvent(new Event("resize"));
    } catch (_e) {}
  }

  function createColSplitterElement(side, onToggleHidden) {
    const splitter = document.createElement("div");
    splitter.className = `ux-col-splitter is-side-${side}`;
    splitter.setAttribute("role", "separator");
    splitter.setAttribute("aria-orientation", "vertical");
    splitter.setAttribute("tabindex", "0");
    splitter.title = tr("拖拽调整宽度，双击恢复默认");

    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "ux-col-splitter-toggle";
    toggleBtn.setAttribute("aria-label", tr("隐藏面板"));
    toggleBtn.title = tr("隐藏面板");
    toggleBtn.innerHTML = `<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.5 2.5 4 6l3.5 3.5"/></svg>`;
    toggleBtn.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
    });
    toggleBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      onToggleHidden();
    });
    splitter.appendChild(toggleBtn);
    return { splitter, toggleBtn };
  }

  function updateSplitterToggleVisual(splitter, toggleBtn, side, hidden) {
    splitter.classList.toggle("is-target-hidden", Boolean(hidden));
    const label = tr(hidden ? "显示面板" : "隐藏面板");
    toggleBtn.title = label;
    toggleBtn.setAttribute("aria-label", label);
    toggleBtn.setAttribute("aria-pressed", hidden ? "true" : "false");
    // side="left": 展开时箭头朝左(收起)，隐藏时朝右(展开)；side="right" 相反
    const pointRight = side === "left" ? Boolean(hidden) : !Boolean(hidden);
    toggleBtn.classList.toggle("is-point-right", pointRight);
  }

  function initSharedSidebarToggle() {
    const toggleBtn = document.getElementById("appSidebarToggle");
    const sidebar = document.getElementById("appSidebar");
    const appBody = sidebar?.parentElement;

    const applyCollapsed = (collapsed, persist = true) => {
      document.documentElement.dataset.sidebarCollapsed = collapsed ? "true" : "false";
      if (toggleBtn) {
        toggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
        const label = tr(collapsed ? "展开侧栏" : "收起侧栏");
        toggleBtn.title = label;
        const span = toggleBtn.querySelector(".nav-label");
        if (span) span.textContent = label;
      }
      if (persist) {
        try {
          localStorage.setItem("polarSidebarCollapsed", collapsed ? "1" : "0");
        } catch (_e) {}
      }
      setTimeout(dispatchLayoutResize, 180);
    };

    if (toggleBtn && toggleBtn.dataset.bound !== "true") {
      toggleBtn.dataset.bound = "true";
      const initial = document.documentElement.dataset.sidebarCollapsed === "true";
      applyCollapsed(initial, false);
      toggleBtn.addEventListener("click", () => {
        document.documentElement.dataset.sidebarHidden = "false";
        const next = document.documentElement.dataset.sidebarCollapsed !== "true";
        applyCollapsed(next, true);
        if (sidebar) sidebar.dispatchEvent(new CustomEvent("ux-sidebar-sync"));
      });
    }

    if (!sidebar || !appBody || sidebar.dataset.uxSplitterBound === "true") return;
    sidebar.dataset.uxSplitterBound = "true";

    const DEFAULT_WIDTH = 184;
    const MIN_WIDTH = 136;
    const MAX_WIDTH = 320;
    const HIDE_THRESHOLD = 46;
    const COMPACT_THRESHOLD = 104;

    const store = readHorizontalSplitStore();
    const saved = store.__appSidebar || {};
    let expandedWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Number(saved.size) || DEFAULT_WIDTH));
    let isHidden = Boolean(saved.hidden);

    const { splitter, toggleBtn: hideBtn } = createColSplitterElement("left", () => {
      isHidden = !isHidden;
      applySidebarState(true);
    });
    splitter.classList.add("is-sidebar-splitter");

    function applySidebarState(persist = false) {
      document.documentElement.style.setProperty("--app-sidebar-width", `${Math.round(expandedWidth)}px`);
      document.documentElement.dataset.sidebarHidden = isHidden ? "true" : "false";
      updateSplitterToggleVisual(splitter, hideBtn, "left", isHidden);
      if (persist) {
        writeHorizontalSplitEntry("__appSidebar", { size: Math.round(expandedWidth), hidden: isHidden });
      }
      setTimeout(dispatchLayoutResize, 60);
    }

    sidebar.addEventListener("ux-sidebar-sync", () => {
      isHidden = document.documentElement.dataset.sidebarHidden === "true";
      updateSplitterToggleVisual(splitter, hideBtn, "left", isHidden);
      writeHorizontalSplitEntry("__appSidebar", { size: Math.round(expandedWidth), hidden: isHidden });
    });

    if (typeof appBody.insertBefore === "function") {
      appBody.insertBefore(splitter, sidebar.nextSibling);
    }
    applySidebarState(false);

    splitter.addEventListener("dblclick", () => {
      isHidden = false;
      expandedWidth = DEFAULT_WIDTH;
      applyCollapsed(false, true);
      applySidebarState(true);
    });

    splitter.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        isHidden = !isHidden;
        applySidebarState(true);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        isHidden = false;
        applyCollapsed(false, true);
        expandedWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, expandedWidth + (event.key === "ArrowRight" ? 16 : -16)));
        applySidebarState(true);
      }
    });

    splitter.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (event.target instanceof Element && event.target.closest(".ux-col-splitter-toggle")) return;
      event.preventDefault();
      const bodyRect = appBody.getBoundingClientRect();
      splitter.classList.add("is-dragging");
      document.body?.classList?.add("is-ux-col-resizing");
      try { splitter.setPointerCapture(event.pointerId); } catch (_e) {}

      const onMove = (moveEvent) => {
        const raw = moveEvent.clientX - bodyRect.left;
        if (raw <= HIDE_THRESHOLD) {
          isHidden = true;
          applySidebarState(false);
        } else if (raw <= COMPACT_THRESHOLD) {
          isHidden = false;
          applyCollapsed(true, false);
          applySidebarState(false);
        } else {
          isHidden = false;
          if (document.documentElement.dataset.sidebarCollapsed === "true") {
            applyCollapsed(false, false);
          }
          expandedWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, raw));
          applySidebarState(false);
        }
      };

      const onUp = () => {
        splitter.classList.remove("is-dragging");
        document.body?.classList?.remove("is-ux-col-resizing");
        splitter.removeEventListener("pointermove", onMove);
        splitter.removeEventListener("pointerup", onUp);
        splitter.removeEventListener("pointercancel", onUp);
        try { localStorage.setItem("polarSidebarCollapsed", document.documentElement.dataset.sidebarCollapsed === "true" ? "1" : "0"); } catch (_e) {}
        applySidebarState(true);
      };

      splitter.addEventListener("pointermove", onMove);
      splitter.addEventListener("pointerup", onUp);
      splitter.addEventListener("pointercancel", onUp);
    });
  }

  /**
   * 通用页面内部左右分栏纵向分隔条引擎（双端所有两栏页面自动接入）
   */
  const HORIZONTAL_SPLIT_SPECS = [
    { selector: ".model-page-layout", key: "model", side: "left", defaultSize: 280, minSize: 160, maxSize: 520 },
    { selector: ".curve-page-layout", key: "curves", side: "left", defaultSize: 280, minSize: 160, maxSize: 520 },
    { selector: ".fault-split-layout", key: "faults", side: "left", defaultSize: 280, minSize: 160, maxSize: 520 },
    { selector: ".mode-page-layout", key: "modes", side: "left", defaultSize: 280, minSize: 160, maxSize: 520 },
    { selector: ".runtime-page-layout", key: "runtime", side: "left", defaultSize: 280, minSize: 160, maxSize: 520 },
    { selector: ".measurement-page-layout", key: "measurements", side: "left", defaultSize: 280, minSize: 160, maxSize: 520 },
    { selector: ".renewable-page-layout", key: "renewable", side: "left", defaultSize: 340, minSize: 240, maxSize: 540 },
    { selector: ".renewable-trend-workspace", key: "renewable-trend", side: "left", defaultSize: 224, minSize: 150, maxSize: 380 },
    { selector: ".overview-main-grid", key: "overview-boundary", side: "right", defaultSize: 300, minSize: 190, maxSize: 480 },
    { selector: ".parameter-page-layout", key: "parameters", side: "right", defaultSize: 340, minSize: 210, maxSize: 520 },
  ];

  function resolveSplitStorageKey(container, spec) {
    const faultPanel = container.closest?.("[data-fault-panel]")?.getAttribute("data-fault-panel");
    if (faultPanel) return `${spec.key}:${faultPanel}`;
    const pageName = container.closest?.("[data-page]")?.getAttribute("data-page");
    return pageName ? `${pageName}:${spec.key}` : spec.key;
  }

  function bindGridHorizontalSplitter(container, spec) {
    if (!container || container.dataset.uxSplitBound === "true") return;
    const directChildren = Array.from(container.children || []).filter(
      (child) => !child.classList?.contains("ux-col-splitter"),
    );
    if (directChildren.length !== 2) return;
    const [leftPane, rightPane] = directChildren;
    const targetPane = spec.side === "left" ? leftPane : rightPane;
    container.dataset.uxSplitBound = "true";
    container.classList.add("ux-has-col-splitter", `is-side-${spec.side}`);
    targetPane.classList.add("ux-collapsible-pane");

    const storageKey = resolveSplitStorageKey(container, spec);
    const store = readHorizontalSplitStore();
    const saved = store[storageKey] || {};
    const HIDE_THRESHOLD = 72;
    let currentSize = Math.min(spec.maxSize, Math.max(spec.minSize, Number(saved.size) || spec.defaultSize));
    let isHidden = Boolean(saved.hidden);

    const { splitter, toggleBtn } = createColSplitterElement(spec.side, () => {
      isHidden = !isHidden;
      applyState(true);
    });

    function applyState(persist = false) {
      container.style.setProperty("--ux-split-size", `${Math.round(currentSize)}px`);
      container.classList.toggle("is-pane-hidden", isHidden);
      targetPane.setAttribute("aria-hidden", isHidden ? "true" : "false");
      updateSplitterToggleVisual(splitter, toggleBtn, spec.side, isHidden);
      if (persist) {
        writeHorizontalSplitEntry(storageKey, { size: Math.round(currentSize), hidden: isHidden });
      }
      setTimeout(dispatchLayoutResize, 60);
    }

    if (typeof container.insertBefore === "function") {
      container.insertBefore(splitter, rightPane);
    }
    applyState(false);

    splitter.addEventListener("dblclick", () => {
      isHidden = false;
      currentSize = spec.defaultSize;
      applyState(true);
    });

    splitter.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        isHidden = !isHidden;
        applyState(true);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const sign = spec.side === "left"
          ? (event.key === "ArrowRight" ? 1 : -1)
          : (event.key === "ArrowLeft" ? 1 : -1);
        isHidden = false;
        currentSize = Math.min(spec.maxSize, Math.max(spec.minSize, currentSize + sign * 20));
        applyState(true);
      }
    });

    splitter.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (event.target instanceof Element && event.target.closest(".ux-col-splitter-toggle")) return;
      event.preventDefault();
      const rect = container.getBoundingClientRect();
      const maxAllowed = Math.min(spec.maxSize, Math.max(spec.minSize, rect.width - 260));
      splitter.classList.add("is-dragging");
      document.body?.classList?.add("is-ux-col-resizing");
      try { splitter.setPointerCapture(event.pointerId); } catch (_e) {}

      const onMove = (moveEvent) => {
        const raw = spec.side === "left"
          ? (moveEvent.clientX - rect.left)
          : (rect.right - moveEvent.clientX);
        if (raw < HIDE_THRESHOLD) {
          isHidden = true;
          applyState(false);
        } else {
          isHidden = false;
          currentSize = Math.min(maxAllowed, Math.max(spec.minSize, raw));
          applyState(false);
        }
      };

      const onUp = () => {
        splitter.classList.remove("is-dragging");
        document.body?.classList?.remove("is-ux-col-resizing");
        splitter.removeEventListener("pointermove", onMove);
        splitter.removeEventListener("pointerup", onUp);
        splitter.removeEventListener("pointercancel", onUp);
        applyState(true);
      };

      splitter.addEventListener("pointermove", onMove);
      splitter.addEventListener("pointerup", onUp);
      splitter.addEventListener("pointercancel", onUp);
    });
  }

  function enhanceAllHorizontalSplitters() {
    for (const spec of HORIZONTAL_SPLIT_SPECS) {
      document.querySelectorAll(spec.selector).forEach((container) => {
        bindGridHorizontalSplitter(container, spec);
      });
    }
  }
  window.refreshUxSplitters = enhanceAllHorizontalSplitters;

  /**
   * 顶栏注入轻量 Ctrl+K 快捷入口按钮、全局快捷键与导航进度条监听
   */
  function initGlobalShortcutsAndChrome() {
    initSharedSidebarToggle();
    enhanceAllHorizontalSplitters();

    const pageMain = document.querySelector(".page-main");
    if (pageMain && typeof MutationObserver === "function") {
      const splitObserver = new MutationObserver(() => {
        enhanceAllHorizontalSplitters();
      });
      splitObserver.observe(pageMain, { childList: true });
    }
    const utilityGroup = document.querySelector(".topbar-utility-group");
    if (utilityGroup && !document.getElementById("uxCommandPaletteButton")) {
      const btn = document.createElement("button");
      btn.id = "uxCommandPaletteButton";
      btn.type = "button";
      btn.className = "ux-palette-trigger";
      btn.title = `${tr("快捷命令")} (Ctrl+K)`;
      btn.innerHTML = `<span data-i18n-skip="true">Ctrl+K</span>`;
      btn.addEventListener("click", openCommandPalette);
      utilityGroup.prepend(btn);
    }

    document.querySelectorAll(".page-nav button[data-nav-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        flashTopProgress();
        requestAnimationFrame(enhanceAllHorizontalSplitters);
      });
    });
    const modelSel = document.getElementById("modelSelector");
    modelSel?.addEventListener("change", flashTopProgress);

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && String(event.key).toLowerCase() === "k") {
        event.preventDefault();
        if (paletteDialog?.open) closeCommandPalette();
        else openCommandPalette();
        return;
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey) {
        const digit = event.key === "0" ? 10 : Number(event.key);
        if (Number.isInteger(digit) && digit >= 1 && digit <= 10) {
          const navBtns = document.querySelectorAll(".page-nav button[data-nav-page]");
          const targetBtn = navBtns[digit - 1];
          if (targetBtn) {
            event.preventDefault();
            targetBtn.click();
          }
        }
      }
    });

    bindTableSorting();
    enhanceLogDetailDialog();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGlobalShortcutsAndChrome, { once: true });
  } else {
    initGlobalShortcutsAndChrome();
  }
})();
