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
  let progressClearTimer = null;
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
    clearTimeout(progressClearTimer);
    progressBarEl.classList.remove("is-done");
    progressBarEl.classList.add("is-active");
    progressHideTimer = setTimeout(() => {
      progressBarEl.classList.add("is-done");
      progressClearTimer = setTimeout(() => {
        progressBarEl.classList.remove("is-active", "is-done");
      }, 220);
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
   * 统一跳转接线图并居中聚焦高亮目标设备
   */
  function locateDeviceOnDiagram(devName) {
    const targetName = String(devName || "").trim();
    if (!targetName) return false;
    if (typeof showPage === "function") {
      showPage("diagram");
    } else {
      document.querySelector('.page-nav button[data-nav-page="diagram"]')?.click();
    }
    let attempts = 0;
    const tryFocus = () => {
      attempts += 1;
      const canvas = document.getElementById("modelDiagramCanvas");
      if (canvas && canvas.querySelector("svg")) {
        if (typeof window.focusDiagramDeviceByName === "function") {
          const hit = window.focusDiagramDeviceByName(canvas, targetName);
          if (hit) return;
        }
        return;
      }
      if (attempts < 12) setTimeout(tryFocus, 80);
    };
    setTimeout(tryFocus, 70);
    if (typeof showUiToast === "function") {
      showUiToast(`${tr("定位接线图")}: ${targetName}`, "info", 1800);
    }
    return true;
  }
  window.locateDeviceOnDiagram = locateDeviceOnDiagram;

  /**
   * 从接线图或其它页面按设备名一键穿透到「实时量测」或「控制指令」并自动过滤定位（兼容教员端与学员端）
   */
  function jumpToDeviceMeasurements(devName) {
    const targetName = String(devName || "").trim();
    if (!targetName) return false;
    if (typeof showPage === "function") {
      showPage("measurements");
    } else {
      document.querySelector('.page-nav button[data-nav-page="measurements"]')?.click();
    }
    requestAnimationFrame(() => {
      if (typeof state !== "undefined" && state) {
        if ("measurementCompareFilter" in state) state.measurementCompareFilter = { dev_type: "all", dev_name: "" };
        if ("measurementCompareKeywordFilter" in state) state.measurementCompareKeywordFilter = targetName;
        if ("measurementFilter" in state) state.measurementFilter = { dev_type: "all", dev_name: "" };
        if ("measurementKeywordFilter" in state) state.measurementKeywordFilter = targetName;
      }
      const input = document.getElementById("measurementCompareKeywordFilter")
        || document.getElementById("traineeMeasurementKeywordFilter")
        || document.querySelector('[data-page="measurements"] input[type="search"]');
      if (input) {
        input.value = targetName;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (typeof renderMeasurementCompareTable === "function") renderMeasurementCompareTable();
      if (typeof renderMeasurements === "function") renderMeasurements();
    });
    return true;
  }

  function jumpToDeviceCommands(devName) {
    const targetName = String(devName || "").trim();
    if (!targetName) return false;
    const isTrainee = Boolean(document.getElementById("traineeRunToggle"));
    const targetPage = isTrainee ? "commands" : "runtime";
    if (typeof showPage === "function") {
      showPage(targetPage);
    } else {
      document.querySelector(`.page-nav button[data-nav-page="${targetPage}"]`)?.click();
    }
    requestAnimationFrame(() => {
      if (typeof state !== "undefined" && state) {
        if ("runtimeDeviceFilter" in state) state.runtimeDeviceFilter = { dev_type: "all", dev_name: "" };
        if ("runtimeCommandKeywordFilter" in state) state.runtimeCommandKeywordFilter = targetName;
        if ("controlFilter" in state) state.controlFilter = { dev_type: "all", dev_name: "" };
        if ("commandKeywordFilter" in state) state.commandKeywordFilter = targetName;
      }
      const input = document.getElementById("runtimeCommandKeywordFilter")
        || document.getElementById("commandKeywordFilter")
        || document.querySelector(`[data-page="${targetPage}"] input[type="search"]`);
      if (input) {
        input.value = targetName;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (typeof renderRuntimeDeviceTable === "function") renderRuntimeDeviceTable();
      if (typeof renderCombinedControlPage === "function") renderCombinedControlPage();
    });
    return true;
  }

  window.jumpToDeviceMeasurements = jumpToDeviceMeasurements;
  window.jumpToDeviceCommands = jumpToDeviceCommands;

  /**
   * 在接线图面板头部动态显示当前选中设备的快捷穿透入口（查看量测 / 查看控制）
   */
  function enhanceDiagramSelectionActions() {
    const canvas = document.getElementById("modelDiagramCanvas");
    const panelHead = canvas?.closest?.(".model-diagram-panel")?.querySelector?.(".panel-head");
    if (!canvas || !panelHead) return;
    let bar = panelHead.querySelector(".ux-diagram-selection-actions");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "ux-diagram-selection-actions";
      bar.hidden = true;
      bar.innerHTML = `
        <span class="ux-diagram-selected-name"></span>
        <button type="button" class="compact-action-btn" data-ux-diagram-jump="measurements">${tr("查看量测")}</button>
        <button type="button" class="compact-action-btn" data-ux-diagram-jump="commands">${tr("查看控制")}</button>
      `;
      bar.addEventListener("click", (event) => {
        const btn = event.target instanceof Element ? event.target.closest("[data-ux-diagram-jump]") : null;
        if (!btn) return;
        const devName = String(canvas.dataset.selectedDeviceName || "").trim();
        if (!devName) return;
        if (btn.dataset.uxDiagramJump === "measurements") jumpToDeviceMeasurements(devName);
        else jumpToDeviceCommands(devName);
      });
      const summary = panelHead.querySelector("#modelDiagramSummary, span");
      if (summary) panelHead.insertBefore(bar, summary);
      else panelHead.appendChild(bar);
    }
    if (canvas.dataset.uxSelectionActionsBound !== "true") {
      canvas.dataset.uxSelectionActionsBound = "true";
      const syncBar = () => {
        const devName = String(canvas.dataset.selectedDeviceName || "").trim();
        bar.hidden = !devName;
        const labelEl = bar.querySelector(".ux-diagram-selected-name");
        if (labelEl) labelEl.textContent = devName;
      };
      canvas.addEventListener("ux-diagram-selection", syncBar);
      syncBar();
    }
  }

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
    // 1. 一级导航页签及常用二级视图
    document.querySelectorAll(".page-nav button[data-nav-page]").forEach((btn, idx) => {
      const page = btn.dataset.navPage;
      const label = (btn.textContent || "").trim();
      items.push({
        group: tr("页面"),
        label,
        hint: idx < 9 ? `Alt+${idx + 1}` : "Alt+0",
        keywords: `${label} ${page}`,
        run: () => {
          btn.click();
          flashTopProgress();
        },
      });
    });
    if (typeof showPage === "function") {
      items.push({
        group: tr("页面"),
        label: tr("人工修改"),
        hint: "model",
        keywords: "人工修改 manual changes model 电网模型",
        run: () => {
          showPage("manual-changes");
          flashTopProgress();
        },
      });
      if (!document.getElementById("traineeRunToggle")) {
        items.push({
          group: tr("页面"),
          label: tr("故障与模式"),
          hint: "faults",
          keywords: "故障与模式 设备故障 量测故障 运行模式 faults modes",
          run: () => {
            showPage("faults");
            flashTopProgress();
          },
        });
      }
    }
    // 2. 高频快捷动作
    items.push({
      group: tr("操作"),
      label: tr("适应画布"),
      hint: "F / 0",
      keywords: "diagram fit reset zoom 接线图 适应 画布 缩放",
      run: () => {
        const canvas = document.getElementById("modelDiagramCanvas");
        if (canvas && typeof resetDiagramViewport === "function") {
          resetDiagramViewport(canvas);
        } else {
          document.querySelector('.page-nav button[data-nav-page="diagram"]')?.click();
          setTimeout(() => {
            const c = document.getElementById("modelDiagramCanvas");
            if (c && typeof resetDiagramViewport === "function") resetDiagramViewport(c);
          }, 120);
        }
      },
    });
    items.push({
      group: tr("操作"),
      label: tr("切换侧栏"),
      hint: "Sidebar",
      keywords: "sidebar collapse expand 侧栏 收起 展开",
      run: () => document.getElementById("appSidebarToggle")?.click(),
    });
    items.push({
      group: tr("操作"),
      label: tr("快捷键速查"),
      hint: "?",
      keywords: "shortcut hotkey help 快捷键 帮助",
      run: () => openShortcutsHelpDialog(),
    });
    // 3. 当前模型设备（直达接线图定位）
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
      if (!th || th.hasAttribute("data-scada104-sort")) return;
      const table = th.closest(SORTABLE_TABLES);
      if (!table || table.classList.contains("scada104-table")) return;
      // 虚拟滚动表格由数据源分页切片渲染，禁止直接 DOM 行排序破坏 spacer 与切片顺序
      if (table.closest("[data-virtual-table]")) return;
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

  let layoutResizeRaf = 0;
  let layoutResizeTimer = null;
  function dispatchLayoutResize(immediate = false) {
    if (immediate) {
      if (layoutResizeTimer) {
        clearTimeout(layoutResizeTimer);
        layoutResizeTimer = null;
      }
      if (layoutResizeRaf) cancelAnimationFrame(layoutResizeRaf);
      layoutResizeRaf = requestAnimationFrame(() => {
        layoutResizeRaf = 0;
        try {
          window.dispatchEvent(new Event("resize"));
        } catch (_e) {}
      });
      return;
    }
    if (layoutResizeTimer) return;
    layoutResizeTimer = setTimeout(() => {
      layoutResizeTimer = null;
      dispatchLayoutResize(true);
    }, 64);
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
        if (container.dataset.uxSplitBound !== "true") {
          bindGridHorizontalSplitter(container, spec);
        }
      });
    }
  }
  window.refreshUxSplitters = enhanceAllHorizontalSplitters;

  /**
   * 为所有 .table-filter-bar 自动注入轻量「清空筛选」按钮（仅在存在激活筛选时显示）
   */
  function filterBarHasActiveValue(bar) {
    const inputs = bar.querySelectorAll('input[type="search"], input[type="text"]');
    for (const input of inputs) {
      if (String(input.value || "").trim() !== "") return true;
    }
    const selects = bar.querySelectorAll("select");
    for (const sel of selects) {
      const firstVal = sel.options?.[0]?.value ?? "all";
      if (sel.value !== firstVal && sel.value !== "all" && sel.value !== "") return true;
    }
    const checkboxes = bar.querySelectorAll('input[type="checkbox"]');
    for (const box of checkboxes) {
      if (box.checked) return true;
    }
    return false;
  }

  function enhanceTableFilterClearButtons() {
    document.querySelectorAll(".table-filter-bar").forEach((bar) => {
      if (bar.dataset.uxClearFilterBound === "true") {
        const btn = bar.querySelector(".ux-clear-filter-btn");
        if (btn) btn.hidden = !filterBarHasActiveValue(bar);
        return;
      }
      bar.dataset.uxClearFilterBound = "true";
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "compact-action-btn ux-clear-filter-btn";
      clearBtn.textContent = tr("清空筛选");
      clearBtn.hidden = !filterBarHasActiveValue(bar);
      const syncVisibility = () => {
        clearBtn.hidden = !filterBarHasActiveValue(bar);
      };
      bar.addEventListener("input", syncVisibility);
      bar.addEventListener("change", syncVisibility);
      clearBtn.addEventListener("click", () => {
        bar.querySelectorAll('input[type="search"], input[type="text"]').forEach((input) => {
          if (input.value !== "") {
            input.value = "";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
          }
        });
        bar.querySelectorAll("select").forEach((sel) => {
          const resetVal = Array.from(sel.options || []).some((o) => o.value === "all")
            ? "all"
            : (sel.options?.[0]?.value ?? "");
          if (sel.value !== resetVal) {
            sel.value = resetVal;
            sel.dispatchEvent(new Event("change", { bubbles: true }));
          }
        });
        bar.querySelectorAll('input[type="checkbox"]').forEach((box) => {
          if (box.checked) {
            box.checked = false;
            box.dispatchEvent(new Event("change", { bubbles: true }));
          }
        });
        syncVisibility();
      });
      bar.appendChild(clearBtn);
    });
  }

  /**
   * 全局快捷键速查弹窗（按 ? 打开）
   */
  let shortcutsDialog = null;
  function openShortcutsHelpDialog() {
    if (!shortcutsDialog) {
      shortcutsDialog = document.createElement("dialog");
      shortcutsDialog.id = "uxShortcutsHelpDialog";
      shortcutsDialog.className = "ux-shortcuts-dialog";
      shortcutsDialog.addEventListener("click", (event) => {
        if (event.target === shortcutsDialog) shortcutsDialog.close();
      });
      document.body.appendChild(shortcutsDialog);
    }
    const rows = [
      ["Ctrl+K", tr("打开全局快捷命令面板")],
      ["Alt+1 ~ Alt+0", tr("快速切换左侧主页面")],
      ["?", tr("打开或关闭快捷键速查")],
      ["+ / -", tr("接线图放大 / 缩小")],
      ["0 / F", tr("接线图适应画布")],
      ["Esc", tr("关闭弹窗或取消当前操作")],
    ];
    shortcutsDialog.innerHTML = `
      <div class="ux-shortcuts-card">
        <div class="ux-shortcuts-head">
          <h3>${tr("快捷键速查")}</h3>
          <button type="button" class="compact-action-btn" data-close-shortcuts>${tr("关闭")}</button>
        </div>
        <dl class="ux-shortcuts-list">
          ${rows.map(([keys, desc]) => `<div><dt><kbd>${keys}</kbd></dt><dd>${desc}</dd></div>`).join("")}
        </dl>
      </div>
    `;
    shortcutsDialog.querySelector("[data-close-shortcuts]")?.addEventListener("click", () => shortcutsDialog.close());
    if (shortcutsDialog.open) shortcutsDialog.close();
    else if (typeof shortcutsDialog.showModal === "function") shortcutsDialog.showModal();
  }

  /**
   * 顶栏注入轻量 Ctrl+K 快捷入口按钮、全局快捷键与导航进度条监听
   */
  function initGlobalShortcutsAndChrome() {
    initSharedSidebarToggle();
    enhanceAllHorizontalSplitters();
    enhanceTableFilterClearButtons();
    enhanceDiagramSelectionActions();

    const pageMain = document.querySelector(".page-main");
    if (pageMain && typeof MutationObserver === "function") {
      let splitSyncRaf = 0;
      const splitObserver = new MutationObserver(() => {
        if (splitSyncRaf) return;
        splitSyncRaf = requestAnimationFrame(() => {
          splitSyncRaf = 0;
          enhanceAllHorizontalSplitters();
          enhanceTableFilterClearButtons();
          enhanceDiagramSelectionActions();
        });
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
        return;
      }
      if (event.key === "?" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const active = document.activeElement;
        const isTyping = active && (
          active.tagName === "INPUT"
          || active.tagName === "TEXTAREA"
          || active.tagName === "SELECT"
          || active.isContentEditable
        );
        if (!isTyping) {
          event.preventDefault();
          openShortcutsHelpDialog();
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
