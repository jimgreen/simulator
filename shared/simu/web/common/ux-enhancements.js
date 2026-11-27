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
      label: tr("切换日/夜风格"),
      hint: "Light / Dark",
      keywords: "theme light dark toggle 日夜 切换 浅色 深色",
      run: () => toggleLightDarkTheme(),
    });
    items.push({
      group: tr("操作"),
      label: tr("导出当前曲线 PNG"),
      hint: "PNG",
      keywords: "export png chart curve screenshot 导出 曲线 图片",
      run: () => exportVisibleChartPng(),
    });
    // 仿真时钟与接收快捷控制
    const clockActions = [
      ["start", "启动仿真", "start play run clock 启动 运行"],
      ["pause", "暂停仿真", "pause clock 暂停"],
      ["stop", "停止仿真", "stop clock 停止"],
      ["step", "单步推进", "step clock 单步"],
      ["faster", "仿真加速", "faster speed up 加速"],
      ["slower", "仿真减速", "slower speed down 减速"],
    ];
    for (const [act, zhLabel, kw] of clockActions) {
      const btn = document.querySelector(`#topbarClockControls button[data-clock="${act}"]`);
      if (btn) {
        items.push({
          group: tr("操作"),
          label: tr(zhLabel),
          hint: act,
          keywords: `${zhLabel} ${kw}`,
          run: () => {
            if (!btn.disabled) btn.click();
          },
        });
      }
    }
    const traineeToggle = document.getElementById("traineeRunToggle");
    if (traineeToggle) {
      items.push({
        group: tr("操作"),
        label: tr("切换接收状态"),
        hint: "Receive",
        keywords: "receive sync start stop trainee 接收 启动 停止",
        run: () => traineeToggle.click(),
      });
    }
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
    // 4. 14 套视觉风格一键切换（附 3 色色卡预览）
    if (typeof UI_THEME_PRESETS !== "undefined" && Array.isArray(UI_THEME_PRESETS)) {
      UI_THEME_PRESETS.forEach((preset) => {
        const label = typeof t === "function" ? t(`theme.${preset.id}`) : preset.label;
        items.push({
          group: tr("风格"),
          label,
          hint: preset.id,
          swatches: UX_THEME_SWATCHES[preset.id] || null,
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
      li.append(badge, title);
      if (Array.isArray(item.swatches) && item.swatches.length) {
        const sw = document.createElement("span");
        sw.className = "ux-palette-swatches";
        item.swatches.forEach((hex) => {
          const dot = document.createElement("span");
          dot.className = "ux-theme-swatch-dot";
          dot.style.background = hex;
          sw.appendChild(dot);
        });
        li.appendChild(sw);
      }
      const hint = document.createElement("span");
      hint.className = "ux-palette-hint";
      hint.textContent = item.hint || "";
      li.appendChild(hint);
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
    let sidebarMode = "docked";
    try {
      const savedMode = localStorage.getItem("polarSidebarMode");
      if (savedMode === "overlay" || savedMode === "docked") sidebarMode = savedMode;
    } catch (_e) {}
    let isHidden = Boolean(saved.hidden);
    try {
      const savedHidden = localStorage.getItem("polarSidebarHidden");
      if (savedHidden === "1") isHidden = true;
      else if (savedHidden === "0") isHidden = false;
    } catch (_e) {}

    const { splitter, toggleBtn: hideBtn } = createColSplitterElement("left", () => {
      isHidden = !isHidden;
      applySidebarState(true);
    });
    splitter.classList.add("is-sidebar-splitter");

    // 悬浮隐藏时的最左缘 6px 感应热区（鼠标贴近自动滑出，离开平滑收起）
    let hoverCloseTimer = null;
    let edgeSensor = document.getElementById("uxSidebarHoverEdge");
    if (!edgeSensor) {
      edgeSensor = document.createElement("div");
      edgeSensor.id = "uxSidebarHoverEdge";
      edgeSensor.className = "ux-sidebar-edge-sensor";
      edgeSensor.setAttribute("aria-hidden", "true");
      document.body.appendChild(edgeSensor);
    }

    const setHoverPeek = (open) => {
      clearTimeout(hoverCloseTimer);
      if (open) {
        if (sidebarMode === "overlay" && isHidden) {
          document.documentElement.dataset.sidebarHoverOpen = "true";
        }
      } else {
        hoverCloseTimer = setTimeout(() => {
          delete document.documentElement.dataset.sidebarHoverOpen;
        }, 200);
      }
    };
    edgeSensor.addEventListener("mouseenter", () => setHoverPeek(true));
    sidebar.addEventListener("mouseenter", () => {
      if (sidebarMode === "overlay" && isHidden) setHoverPeek(true);
    });
    sidebar.addEventListener("mouseleave", () => {
      if (sidebarMode === "overlay" && isHidden) setHoverPeek(false);
    });

    // 左栏底部追加极简「内嵌 / 悬浮」模式切换按钮与「隐藏左栏」按钮
    const sidebarFooter = sidebar.querySelector(".app-sidebar-footer");
    let modeBtn = document.getElementById("uxSidebarModeBtn");
    let footerHideBtn = document.getElementById("uxSidebarHideBtn");
    if (sidebarFooter && !modeBtn) {
      const ctrlRow = document.createElement("div");
      ctrlRow.className = "ux-sidebar-footer-controls";

      modeBtn = document.createElement("button");
      modeBtn.id = "uxSidebarModeBtn";
      modeBtn.type = "button";
      modeBtn.className = "ux-sidebar-mini-btn";
      modeBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg><span class="nav-label"></span>';
      modeBtn.addEventListener("click", () => {
        setSidebarMode(sidebarMode === "overlay" ? "docked" : "overlay", true);
      });

      footerHideBtn = document.createElement("button");
      footerHideBtn.id = "uxSidebarHideBtn";
      footerHideBtn.type = "button";
      footerHideBtn.className = "ux-sidebar-mini-btn";
      footerHideBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg><span class="nav-label" data-ux-zh="隐藏左栏"></span>';
      footerHideBtn.addEventListener("click", () => {
        setSidebarHidden(true, true);
      });

      ctrlRow.append(modeBtn, footerHideBtn);
      sidebarFooter.prepend(ctrlRow);
    }

    function syncSidebarControlsUi() {
      const isOverlay = sidebarMode === "overlay";
      const topBtn = document.getElementById("uxSidebarToggleBtn");
      if (topBtn) {
        const label = tr(isHidden ? "显示左栏" : "隐藏左栏");
        topBtn.title = `${label} (${tr(isOverlay ? "悬浮" : "内嵌")})`;
        topBtn.setAttribute("aria-label", label);
        topBtn.setAttribute("aria-pressed", isHidden ? "false" : "true");
        topBtn.classList.toggle("is-sidebar-hidden", isHidden);
        topBtn.classList.toggle("is-sidebar-overlay", isOverlay);
      }
      if (modeBtn) {
        const modeText = tr(isOverlay ? "悬浮" : "内嵌");
        modeBtn.title = `${tr("切换左栏模式")} · ${modeText}`;
        modeBtn.setAttribute("aria-label", modeBtn.title);
        modeBtn.classList.toggle("is-active", isOverlay);
        const lbl = modeBtn.querySelector(".nav-label");
        if (lbl) lbl.textContent = modeText;
      }
      if (footerHideBtn) {
        const hideTxt = tr("隐藏左栏");
        footerHideBtn.title = hideTxt;
        footerHideBtn.setAttribute("aria-label", hideTxt);
        const lbl = footerHideBtn.querySelector(".nav-label");
        if (lbl) lbl.textContent = hideTxt;
      }
      document.querySelectorAll("[data-ux-sidebar-mode]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.uxSidebarMode === sidebarMode);
      });
      const dispHideBtn = document.getElementById("uxDisplaySidebarHideBtn");
      if (dispHideBtn) {
        dispHideBtn.textContent = tr(isHidden ? "显示左栏" : "隐藏左栏");
        dispHideBtn.classList.toggle("is-active", isHidden);
      }
    }

    function applySidebarState(persist = false) {
      document.documentElement.style.setProperty("--app-sidebar-width", `${Math.round(expandedWidth)}px`);
      document.documentElement.dataset.sidebarMode = sidebarMode;
      document.documentElement.dataset.sidebarHidden = isHidden ? "true" : "false";
      if (sidebarMode === "overlay") {
        // 悬浮模式下始终展开完整文字标签，不以窄图标态悬浮
        if (document.documentElement.dataset.sidebarCollapsed === "true") {
          applyCollapsed(false, false);
        }
      }
      if (!isHidden) {
        delete document.documentElement.dataset.sidebarHoverOpen;
      }
      updateSplitterToggleVisual(splitter, hideBtn, "left", isHidden);
      syncSidebarControlsUi();
      if (persist) {
        writeHorizontalSplitEntry("__appSidebar", { size: Math.round(expandedWidth), hidden: isHidden });
        try {
          localStorage.setItem("polarSidebarMode", sidebarMode);
          localStorage.setItem("polarSidebarHidden", isHidden ? "1" : "0");
        } catch (_e) {}
      }
      setTimeout(dispatchLayoutResize, 60);
    }

    function setSidebarMode(nextMode, persist = true) {
      if (nextMode !== "docked" && nextMode !== "overlay") return;
      sidebarMode = nextMode;
      if (sidebarMode === "overlay") {
        delete document.documentElement.dataset.sidebarHoverOpen;
      }
      applySidebarState(persist);
    }

    function setSidebarHidden(nextHidden, persist = true) {
      isHidden = Boolean(nextHidden);
      if (isHidden) {
        delete document.documentElement.dataset.sidebarHoverOpen;
      }
      applySidebarState(persist);
    }

    window.__polarSidebarControl = {
      getState: () => ({ mode: sidebarMode, hidden: isHidden }),
      setMode: (mode) => setSidebarMode(mode, true),
      setHidden: (hidden) => setSidebarHidden(hidden, true),
      toggleHidden: () => setSidebarHidden(!isHidden, true),
      syncUi: () => syncSidebarControlsUi(),
    };

    // 悬浮模式展开时：点击工作区空白处、点击菜单项切页或按 Esc 自动隐藏
    sidebar.querySelectorAll(".page-nav button[data-nav-page]").forEach((navBtn) => {
      navBtn.addEventListener("click", () => {
        if (sidebarMode === "overlay") {
          setSidebarHidden(true, true);
        }
      });
    });
    document.addEventListener("click", (event) => {
      if (sidebarMode !== "overlay" || isHidden) return;
      const target = event.target;
      if (!(target instanceof Node) || !target.isConnected) return;
      if (sidebar.contains(target)) return;
      const topToggle = document.getElementById("uxSidebarToggleBtn");
      if (topToggle && topToggle.contains(target)) return;
      const displayHub = document.getElementById("uxDisplayHub");
      if (displayHub && displayHub.contains(target)) return;
      setSidebarHidden(true, true);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && sidebarMode === "overlay" && !isHidden) {
        setSidebarHidden(true, true);
      }
    });

    sidebar.addEventListener("ux-sidebar-sync", () => {
      isHidden = document.documentElement.dataset.sidebarHidden === "true";
      updateSplitterToggleVisual(splitter, hideBtn, "left", isHidden);
      syncSidebarControlsUi();
      writeHorizontalSplitEntry("__appSidebar", { size: Math.round(expandedWidth), hidden: isHidden });
      try {
        localStorage.setItem("polarSidebarHidden", isHidden ? "1" : "0");
      } catch (_e) {}
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

  /* ==========================================================================
   * 2026-11-27 双端全维度交互、可视化与运行效率增强模块
   * 覆盖：14 风格色卡预览与日/夜快切、标签滚轮步进、通用 CSV/PNG 导出与曲线框选缩放、
   *       主页 KPI+Sparkline+进度条+卡片穿透、接线图快搜/Minimap/图例/热力/默认选中、
   *       顶栏越限 Top-3 摘要与实时性能可观测胶囊。
   * ========================================================================== */

  const UX_THEME_SWATCHES = Object.freeze({
    "minimalist-light": ["#f8fafc", "#ffffff", "#2563eb"],
    "arctic-frost": ["#f0f6fb", "#ffffff", "#0284c7"],
    "warm-paper": ["#f6f2e9", "#fffdf8", "#15803d"],
    "slate-daylight": ["#edf1f5", "#fafbfd", "#1d4ed8"],
    "bento-grid": ["#f5f5f7", "#ffffff", "#0071e3"],
    editorial: ["#faf9f6", "#ffffff", "#9f1239"],
    "precision-dark": ["#0b0f19", "#111827", "#38bdf8"],
    "ocean-slate": ["#071422", "#0d2036", "#38bdf8"],
    "nord-dark": ["#242933", "#2e3440", "#88c0d0"],
    "industrial-amber": ["#121110", "#1c1a18", "#f59e0b"],
    glassmorphism: ["#0f172a", "#1e293b", "#60a5fa"],
    "sci-fi-cyan": ["#040812", "#081121", "#00e5ff"],
    "sci-fi-purple": ["#090614", "#120c24", "#c084fc"],
    "sci-fi-matrix": ["#040d08", "#081810", "#00e676"],
  });

  const UX_THEME_GROUPS = Object.freeze([
    {
      labelKey: "theme.group.light",
      fallback: "浅色风格",
      ids: ["minimalist-light", "arctic-frost", "warm-paper", "slate-daylight", "bento-grid", "editorial"],
    },
    {
      labelKey: "theme.group.dark",
      fallback: "深色工程",
      ids: ["precision-dark", "ocean-slate", "nord-dark", "industrial-amber", "glassmorphism"],
    },
    {
      labelKey: "theme.group.scifi",
      fallback: "科幻战情",
      ids: ["sci-fi-cyan", "sci-fi-purple", "sci-fi-matrix"],
    },
  ]);

  const LAST_LIGHT_THEME_KEY = "polarLastLightTheme";
  const LAST_DARK_THEME_KEY = "polarLastDarkTheme";

  function rememberThemeByScheme(themeId) {
    const scheme = document.documentElement.dataset.colorScheme === "dark" ? "dark" : "light";
    try {
      localStorage.setItem(scheme === "dark" ? LAST_DARK_THEME_KEY : LAST_LIGHT_THEME_KEY, themeId);
    } catch (_e) {}
  }

  /**
   * 顶栏一键在最近使用的浅色/深色主题间切换
   */
  function toggleLightDarkTheme() {
    const isDark = document.documentElement.dataset.colorScheme === "dark";
    let target = isDark ? "minimalist-light" : "ocean-slate";
    try {
      const stored = localStorage.getItem(isDark ? LAST_LIGHT_THEME_KEY : LAST_DARK_THEME_KEY);
      if (stored && UX_THEME_SWATCHES[stored]) target = stored;
    } catch (_e) {}
    if (typeof applyUiTheme === "function") {
      applyUiTheme(target, { persist: true, notify: true, redraw: true });
    } else {
      const sel = document.getElementById("themeSelector");
      if (sel) {
        sel.value = target;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    syncThemeQuickButtons();
    syncTopbarHubReadouts();
    renderDisplayHubSwatches(document.getElementById("uxDisplayHubSwatches"));
  }

  let themePopoverEl = null;

  function renderThemeSwatchDots(themeId) {
    const colors = UX_THEME_SWATCHES[themeId] || UX_THEME_SWATCHES["minimalist-light"];
    return `<span class="ux-theme-swatches">${colors
      .map((c) => `<span class="ux-theme-swatch-dot" style="background:${c}"></span>`)
      .join("")}</span>`;
  }

  function syncThemeQuickButtons() {
    const currentId = document.documentElement.dataset.theme || "minimalist-light";
    const isDark = document.documentElement.dataset.colorScheme === "dark";
    rememberThemeByScheme(currentId);
    const swatchBtn = document.getElementById("uxThemeSwatchBtn");
    if (swatchBtn) {
      swatchBtn.innerHTML = renderThemeSwatchDots(currentId);
    }
    const toggleBtn = document.getElementById("uxDayNightToggleBtn");
    if (toggleBtn) {
      toggleBtn.innerHTML = isDark
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
    }
    if (themePopoverEl && !themePopoverEl.hidden) {
      themePopoverEl.querySelectorAll(".ux-theme-card").forEach((card) => {
        card.classList.toggle("is-active", card.dataset.themeId === currentId);
      });
    }
  }

  function openOrToggleThemePopover(anchorBtn) {
    if (!themePopoverEl) {
      themePopoverEl = document.createElement("div");
      themePopoverEl.id = "uxThemeSwatchPopover";
      themePopoverEl.className = "ux-theme-popover";
      themePopoverEl.hidden = true;
      document.body.appendChild(themePopoverEl);
      document.addEventListener("click", (event) => {
        if (themePopoverEl.hidden) return;
        const target = event.target;
        if (target instanceof Node && (themePopoverEl.contains(target) || anchorBtn.contains(target))) return;
        themePopoverEl.hidden = true;
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && themePopoverEl && !themePopoverEl.hidden) {
          themePopoverEl.hidden = true;
        }
      });
    }
    if (!themePopoverEl.hidden) {
      themePopoverEl.hidden = true;
      return;
    }
    const currentId = document.documentElement.dataset.theme || "minimalist-light";
    const groupsHtml = UX_THEME_GROUPS.map((g) => {
      const groupTitle = typeof t === "function" ? t(g.labelKey) : tr(g.fallback);
      const cardsHtml = g.ids
        .map((id) => {
          const name = typeof t === "function" ? t(`theme.${id}`) : id;
          const activeCls = id === currentId ? " is-active" : "";
          return `<button type="button" class="ux-theme-card${activeCls}" data-theme-id="${id}"><span>${name}</span>${renderThemeSwatchDots(id)}</button>`;
        })
        .join("");
      return `<div class="ux-theme-group-title">${groupTitle}</div><div class="ux-theme-grid">${cardsHtml}</div>`;
    }).join("");
    themePopoverEl.innerHTML = `
      <div class="ux-theme-popover-head">
        <strong>${tr("视觉风格预览")} (14)</strong>
        <button type="button" class="compact-action-btn" data-ux-theme-close>${tr("关闭")}</button>
      </div>
      ${groupsHtml}
    `;
    themePopoverEl.querySelector("[data-ux-theme-close]")?.addEventListener("click", () => {
      themePopoverEl.hidden = true;
    });
    themePopoverEl.querySelectorAll(".ux-theme-card").forEach((card) => {
      card.addEventListener("click", () => {
        const nextId = card.dataset.themeId;
        if (nextId && typeof applyUiTheme === "function") {
          applyUiTheme(nextId, { persist: true, notify: true, redraw: true });
        } else if (nextId) {
          const sel = document.getElementById("themeSelector");
          if (sel) {
            sel.value = nextId;
            sel.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
        syncThemeQuickButtons();
        themePopoverEl.hidden = true;
      });
    });
    const rect = anchorBtn.getBoundingClientRect();
    themePopoverEl.hidden = false;
    const popWidth = themePopoverEl.offsetWidth || 420;
    const left = Math.max(8, Math.min(window.innerWidth - popWidth - 8, rect.right - popWidth));
    themePopoverEl.style.top = `${Math.round(rect.bottom + 6)}px`;
    themePopoverEl.style.left = `${Math.round(left)}px`;
  }

  function enhanceTopbarThemeQuickControls() {
    const switcher = document.querySelector(".theme-switcher");
    if (!switcher || document.getElementById("uxThemeSwatchBtn")) return;
    const swatchBtn = document.createElement("button");
    swatchBtn.id = "uxThemeSwatchBtn";
    swatchBtn.type = "button";
    swatchBtn.className = "ux-theme-quick-btn";
    swatchBtn.title = tr("风格色卡");
    swatchBtn.setAttribute("aria-label", tr("风格色卡"));
    swatchBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openOrToggleThemePopover(swatchBtn);
    });

    const toggleBtn = document.createElement("button");
    toggleBtn.id = "uxDayNightToggleBtn";
    toggleBtn.type = "button";
    toggleBtn.className = "ux-theme-quick-btn";
    toggleBtn.title = tr("切换日/夜风格");
    toggleBtn.setAttribute("aria-label", tr("切换日/夜风格"));
    toggleBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggleLightDarkTheme();
    });

    switcher.parentElement?.insertBefore(swatchBtn, switcher);
    switcher.parentElement?.insertBefore(toggleBtn, swatchBtn);
    const themeSel = document.getElementById("themeSelector");
    themeSel?.addEventListener("change", () => setTimeout(syncThemeQuickButtons, 0));
    syncThemeQuickButtons();
    syncTopbarHubReadouts();
    renderDisplayHubSwatches(document.getElementById("uxDisplayHubSwatches"));
  }

  /**
   * 2. .model-param-tabs 鼠标滚轮横滚 + 左右紧凑步进按钮 + 激活项自动居中
   */
  function enhanceHorizontalTabsScroll() {
    const modelParamWrap = document.getElementById("modelParamTable");
    if (modelParamWrap && modelParamWrap.dataset.uxTabsObserverBound !== "true" && typeof MutationObserver === "function") {
      modelParamWrap.dataset.uxTabsObserverBound = "true";
      let tabsSyncRaf = 0;
      const tabsObserver = new MutationObserver(() => {
        if (tabsSyncRaf) return;
        tabsSyncRaf = requestAnimationFrame(() => {
          tabsSyncRaf = 0;
          enhanceHorizontalTabsScroll();
        });
      });
      tabsObserver.observe(modelParamWrap, { childList: true, subtree: true });
    }
    document.querySelectorAll(".model-param-tabs").forEach((tabs) => {
      if (tabs.dataset.uxWheelScrollBound === "true") return;
      tabs.dataset.uxWheelScrollBound = "true";
      const parent = tabs.parentElement;
      if (!parent) return;
      const shell = document.createElement("div");
      shell.className = "ux-tabs-scroll-shell";
      const leftBtn = document.createElement("button");
      leftBtn.type = "button";
      leftBtn.className = "ux-tabs-step-btn";
      leftBtn.textContent = "‹";
      leftBtn.title = tr("向左滚动分类标签");
      leftBtn.setAttribute("aria-label", tr("向左滚动分类标签"));
      const rightBtn = document.createElement("button");
      rightBtn.type = "button";
      rightBtn.className = "ux-tabs-step-btn";
      rightBtn.textContent = "›";
      rightBtn.title = tr("向右滚动分类标签");
      rightBtn.setAttribute("aria-label", tr("向右滚动分类标签"));

      parent.insertBefore(shell, tabs);
      shell.append(leftBtn, tabs, rightBtn);

      const syncStepButtons = () => {
        const overflow = tabs.scrollWidth > tabs.clientWidth + 4;
        leftBtn.hidden = !overflow;
        rightBtn.hidden = !overflow;
        if (overflow) {
          leftBtn.disabled = tabs.scrollLeft <= 2;
          rightBtn.disabled = tabs.scrollLeft + tabs.clientWidth >= tabs.scrollWidth - 2;
        }
      };

      tabs.addEventListener(
        "wheel",
        (event) => {
          if (tabs.scrollWidth <= tabs.clientWidth + 2) return;
          const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
          if (!delta) return;
          event.preventDefault();
          tabs.scrollLeft += delta * 1.15;
          syncStepButtons();
        },
        { passive: false },
      );

      leftBtn.addEventListener("click", () => {
        tabs.scrollBy({ left: -240, behavior: "smooth" });
        setTimeout(syncStepButtons, 220);
      });
      rightBtn.addEventListener("click", () => {
        tabs.scrollBy({ left: 240, behavior: "smooth" });
        setTimeout(syncStepButtons, 220);
      });
      tabs.addEventListener("scroll", syncStepButtons, { passive: true });
      tabs.addEventListener("click", (event) => {
        const tabBtn = event.target instanceof Element ? event.target.closest("button") : null;
        if (tabBtn && typeof tabBtn.scrollIntoView === "function") {
          setTimeout(() => {
            tabBtn.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
            syncStepButtons();
          }, 30);
        }
      });
      if (typeof ResizeObserver === "function") {
        new ResizeObserver(syncStepButtons).observe(tabs);
      }
      if (typeof MutationObserver === "function") {
        new MutationObserver(syncStepButtons).observe(tabs, { childList: true });
      }
      syncStepButtons();
    });
  }

  /**
   * 3. 通用表格导出 CSV（覆盖模型参数、控制指令、运行日志及 IEC104 四遥点表）
   */
  function csvCellEscape(value) {
    const str = String(value ?? "").replace(/\r?\n/g, " ").trim();
    return /[",]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  }

  function triggerBlobDownload(filename, blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportTableElementToCsv(table, prefix = "export") {
    if (!table) return false;
    const rows = [];
    const headerCells = Array.from(table.querySelectorAll("thead tr:last-child th"));
    const keepIndexes = [];
    const headerRow = [];
    headerCells.forEach((th, idx) => {
      if (th.hidden || th.style.display === "none") return;
      const label = (th.textContent || "").replace(/[▲▼]/g, "").trim();
      if (label === "操作" || label === "Actions" || label === "Действия") return;
      keepIndexes.push(idx);
      headerRow.push(csvCellEscape(label));
    });
    if (headerRow.length) rows.push(headerRow.join(","));

    const bodyRows = Array.from(table.querySelectorAll("tbody tr")).filter(
      (trEl) => !trEl.hidden && trEl.style.display !== "none" && !trEl.classList.contains("virtual-spacer-row"),
    );
    for (const trEl of bodyRows) {
      const cells = Array.from(trEl.children);
      if (!cells.length || (cells.length === 1 && cells[0].colSpan > 1)) continue;
      const out = (keepIndexes.length ? keepIndexes : cells.map((_, i) => i)).map((idx) => {
        const cell = cells[idx];
        if (!cell) return "";
        const field = cell.querySelector("input, select");
        if (field) {
          if (field.tagName === "SELECT") {
            return csvCellEscape(field.options?.[field.selectedIndex]?.text || field.value);
          }
          if (field.type === "checkbox") return field.checked ? "1" : "0";
          return csvCellEscape(field.value);
        }
        return csvCellEscape(cell.textContent || "");
      });
      rows.push(out.join(","));
    }
    if (rows.length <= 1) {
      if (typeof showUiToast === "function") showUiToast(tr("无数据可导出"), "warn", 1800);
      return false;
    }
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const csvText = `\uFEFF${rows.join("\r\n")}`;
    triggerBlobDownload(`${prefix}-${ts}.csv`, new Blob([csvText], { type: "text/csv;charset=utf-8;" }));
    if (typeof showUiToast === "function") showUiToast(`${tr("已导出 CSV")} (${rows.length - 1})`, "ok", 1800);
    return true;
  }

  function enhanceGenericTableCsvExports() {
    const targets = [
      { page: "model", panelSel: ".model-param-panel", tableSel: "table", prefix: "model-params" },
      { page: "runtime", panelSel: ".panel", tableSel: "table", prefix: "runtime-commands" },
      { page: "commands", panelSel: ".panel", tableSel: "table", prefix: "trainee-commands" },
      { page: "logs", panelSel: ".panel", tableSel: "table", prefix: "runtime-logs" },
      { page: "history", panelSel: ".panel", tableSel: "table", prefix: "trainee-logs" },
      { page: "scada104", panelSel: ".scada104-card, .panel", tableSel: "#scada104PointsTable, table", prefix: "iec104-points" },
    ];
    for (const cfg of targets) {
      const section = document.querySelector(`.page-section[data-page="${cfg.page}"]`);
      if (!section) continue;
      section.querySelectorAll(cfg.panelSel).forEach((panel) => {
        const table = panel.querySelector(cfg.tableSel);
        const actions = panel.querySelector(".panel-actions, .table-filter-bar, .card-actions");
        if (!table || !actions || actions.querySelector(".ux-generic-csv-btn")) return;
        // 避免与已有 CSV 导出按钮重复
        if (actions.querySelector('[id*="Csv"], [id*="csv"]')) return;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "compact-action-btn ux-generic-csv-btn";
        btn.textContent = tr("导出 CSV");
        btn.addEventListener("click", () => {
          const liveTable = panel.querySelector(cfg.tableSel) || table;
          exportTableElementToCsv(liveTable, cfg.prefix);
        });
        actions.appendChild(btn);
      });
    }
  }

  /**
   * 4. 曲线图画布：导出高清 PNG + 导出 CSV + Shift 框选/Ctrl 滚轮局部缩放与双击复原
   */
  function exportCanvasToPng(canvas, prefix = "curve") {
    if (!canvas || !canvas.width || !canvas.height) {
      if (typeof showUiToast === "function") showUiToast(tr("无数据可导出"), "warn", 1800);
      return false;
    }
    const out = document.createElement("canvas");
    out.width = canvas.width;
    out.height = canvas.height;
    const ctx = out.getContext("2d");
    if (!ctx) return false;
    const palette = typeof chartThemePalette === "function" ? chartThemePalette() : null;
    ctx.fillStyle = palette?.bg || getComputedStyle(document.documentElement).getPropertyValue("--surface") || "#ffffff";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(canvas, 0, 0);
    const dataUrl = out.toDataURL("image/png");
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = `${prefix}-${ts}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    if (typeof showUiToast === "function") showUiToast(tr("已导出 PNG"), "ok", 1800);
    return true;
  }

  function exportVisibleChartPng() {
    const activePage = document.querySelector(".page-section.is-active") || document;
    const canvas = Array.from(activePage.querySelectorAll("canvas")).find(
      (c) => !c.classList.contains("ux-overview-sparkline") && !c.classList.contains("ux-diagram-minimap-canvas") && c.offsetWidth > 120,
    );
    return exportCanvasToPng(canvas, canvas?.id || "chart");
  }

  function exportCurveSeriesCsv(canvasId) {
    if (typeof state === "undefined" || !state) return false;
    const rows = [];
    if ((canvasId === "curveChart" || canvasId === "curveEditorChart") && state.curveSeries) {
      const keys = Array.isArray(state.selectedCurveKeys) && state.selectedCurveKeys.length
        ? state.selectedCurveKeys
        : Object.keys(state.curveSeries).slice(0, 4);
      const lists = keys.map((k) => (Array.isArray(state.curveSeries[k]) ? state.curveSeries[k] : []));
      const maxLen = Math.max(0, ...lists.map((a) => a.length));
      if (!maxLen) return false;
      rows.push(["index", ...keys.map(csvCellEscape)].join(","));
      for (let i = 0; i < maxLen; i += 1) {
        rows.push([i, ...lists.map((arr) => (arr[i] ?? ""))].join(","));
      }
    } else if (canvasId === "curveDisplayChart" && typeof curveDisplaySeriesMap === "function") {
      const map = curveDisplaySeriesMap() || {};
      const keys = Array.isArray(state.selectedCurveDisplayKeys) && state.selectedCurveDisplayKeys.length
        ? state.selectedCurveDisplayKeys
        : Object.keys(map).slice(0, 4);
      const lists = keys.map((k) => (Array.isArray(map[k]) ? map[k] : []));
      const maxLen = Math.max(0, ...lists.map((a) => a.length));
      if (!maxLen) return false;
      rows.push(["index", ...keys.map(csvCellEscape)].join(","));
      for (let i = 0; i < maxLen; i += 1) {
        rows.push([i, ...lists.map((arr) => (arr[i]?.value ?? arr[i] ?? ""))].join(","));
      }
    } else if ((canvasId === "runtimeTraceChart" || canvasId === "commandTraceChart") && Array.isArray(state.runtimeTraceHistory || state.commandTraceHistory)) {
      const h = Array.isArray(state.runtimeTraceHistory) ? state.runtimeTraceHistory : (state.commandTraceHistory || []);
      if (!h.length) return false;
      rows.push("time,value");
      h.forEach((pt) => rows.push(`${csvCellEscape(pt.label || pt.sim_time || pt.t || "")},${pt.value ?? ""}`));
    } else if (canvasId === "measurementTraceChart" && Array.isArray(state.measurementTraceHistory)) {
      const h = state.measurementTraceHistory;
      if (!h.length) return false;
      rows.push("time,meas,truth");
      h.forEach((pt) => rows.push(`${csvCellEscape(pt.label || pt.sim_time || pt.t || "")},${pt.meas ?? pt.value ?? ""},${pt.truth ?? ""}`));
    } else {
      return false;
    }
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    triggerBlobDownload(`${canvasId}-${ts}.csv`, new Blob([`\uFEFF${rows.join("\r\n")}`], { type: "text/csv;charset=utf-8;" }));
    if (typeof showUiToast === "function") showUiToast(`${tr("已导出 CSV")} (${rows.length - 1})`, "ok", 1800);
    return true;
  }

  function enhanceCurveCanvases() {
    const canvasIds = [
      "curveEditorChart",
      "curveChart",
      "curveDisplayChart",
      "runtimeTraceChart",
      "commandTraceChart",
      "measurementTraceChart",
      "renewableTrendChart",
    ];
    canvasIds.forEach((id) => {
      const canvas = document.getElementById(id);
      const host = canvas?.parentElement;
      if (!canvas || !host || host.dataset.uxChartToolsBound === "true") return;
      host.dataset.uxChartToolsBound = "true";
      host.classList.add("ux-chart-stage-host");
      host.style.overflow = "hidden";

      const tools = document.createElement("div");
      tools.className = "ux-chart-tools";
      tools.innerHTML = `
        <button type="button" class="compact-action-btn" data-ux-chart-act="reset" hidden title="${tr("重置缩放")}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg></button>
        <button type="button" class="compact-action-btn" data-ux-chart-act="csv" title="${tr("导出 CSV")}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg><span>CSV</span></button>
        <button type="button" class="compact-action-btn" data-ux-chart-act="png" title="${tr("导出 PNG")}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="m21 15-5-5-6 6"/></svg><span>PNG</span></button>
      `;
      const zoomBadge = document.createElement("div");
      zoomBadge.className = "ux-chart-zoom-stats";
      zoomBadge.hidden = true;

      // 优先将导出/重置工具条流式嵌入所属面板的标题控制栏末尾，彻底杜绝遮挡图例或曲线
      const panel = host.closest(".renewable-trend-panel, .panel, section");
      const inlineSlot = panel?.querySelector(
        ".renewable-trend-head-meta, .panel-head .panel-actions, .curve-toolbar, .panel-head",
      );
      if (inlineSlot && !inlineSlot.querySelector(".ux-chart-tools")) {
        tools.classList.add("is-inline");
        inlineSlot.appendChild(tools);
      } else {
        host.appendChild(tools);
      }
      host.appendChild(zoomBadge);

      // 若容器内包含水平图例条，绑定滚轮横向滚动提升浏览效率
      const legendBar = host.querySelector(".renewable-trend-inline-legend");
      if (legendBar && legendBar.dataset.uxWheelBound !== "true") {
        legendBar.dataset.uxWheelBound = "true";
        legendBar.addEventListener(
          "wheel",
          (ev) => {
            if (legendBar.scrollWidth <= legendBar.clientWidth + 2) return;
            if (Math.abs(ev.deltaY) >= Math.abs(ev.deltaX)) {
              ev.preventDefault();
              legendBar.scrollLeft += ev.deltaY;
            }
          },
          { passive: false },
        );
      }

      let zoomStart = 0;
      let zoomEnd = 1;
      let brushEl = null;
      let brushOriginX = 0;

      const resetBtn = tools.querySelector('[data-ux-chart-act="reset"]');
      const applyCanvasZoom = (s, e) => {
        zoomStart = Math.max(0, Math.min(0.95, s));
        zoomEnd = Math.max(zoomStart + 0.05, Math.min(1, e));
        const span = zoomEnd - zoomStart;
        const zoomed = span < 0.99;
        if (!zoomed) {
          canvas.style.transform = "";
          canvas.style.transformOrigin = "";
          if (resetBtn) resetBtn.hidden = true;
          zoomBadge.hidden = true;
          return;
        }
        const scaleX = Math.min(12, 1 / span);
        const shiftPct = -(zoomStart * 100);
        canvas.style.transformOrigin = "0 50%";
        canvas.style.transform = `scaleX(${scaleX.toFixed(3)}) translateX(${shiftPct.toFixed(2)}%)`;
        if (resetBtn) resetBtn.hidden = false;
        zoomBadge.hidden = false;
        zoomBadge.textContent = `${tr("缩放区间")} ${(zoomStart * 100).toFixed(0)}%–${(zoomEnd * 100).toFixed(0)}% (${scaleX.toFixed(1)}x)`;
      };

      tools.addEventListener("click", (event) => {
        const btn = event.target instanceof Element ? event.target.closest("[data-ux-chart-act]") : null;
        if (!btn) return;
        const act = btn.dataset.uxChartAct;
        if (act === "png") exportCanvasToPng(canvas, id);
        else if (act === "csv") {
          if (!exportCurveSeriesCsv(id) && typeof showUiToast === "function") {
            showUiToast(tr("无数据可导出"), "warn", 1800);
          }
        } else if (act === "reset") {
          applyCanvasZoom(0, 1);
        }
      });

      // Shift + 左键拖拽框选局部放大，不干扰教员端原曲线拖拽编辑
      host.addEventListener(
        "pointerdown",
        (event) => {
          if (!event.shiftKey || event.button !== 0) return;
          const rect = host.getBoundingClientRect();
          if (rect.width <= 10) return;
          event.preventDefault();
          event.stopPropagation();
          brushOriginX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
          brushEl = document.createElement("div");
          brushEl.className = "ux-chart-brush";
          brushEl.style.left = `${brushOriginX}px`;
          brushEl.style.width = "0px";
          host.appendChild(brushEl);

          const onMove = (ev) => {
            if (!brushEl) return;
            const curX = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
            const left = Math.min(brushOriginX, curX);
            const width = Math.abs(curX - brushOriginX);
            brushEl.style.left = `${left}px`;
            brushEl.style.width = `${width}px`;
          };
          const onUp = (ev) => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            if (!brushEl) return;
            const curX = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
            const left = Math.min(brushOriginX, curX);
            const right = Math.max(brushOriginX, curX);
            brushEl.remove();
            brushEl = null;
            if (right - left >= 16) {
              const curSpan = zoomEnd - zoomStart;
              const nextS = zoomStart + (left / rect.width) * curSpan;
              const nextE = zoomStart + (right / rect.width) * curSpan;
              applyCanvasZoom(nextS, nextE);
            }
          };
          window.addEventListener("pointermove", onMove);
          window.addEventListener("pointerup", onUp);
        },
        true,
      );

      // Ctrl + 滚轮缩放，双击重置
      host.addEventListener(
        "wheel",
        (event) => {
          if (!event.ctrlKey) return;
          event.preventDefault();
          const rect = host.getBoundingClientRect();
          const ratio = rect.width > 0 ? Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) : 0.5;
          const curSpan = zoomEnd - zoomStart;
          const factor = event.deltaY < 0 ? 0.72 : 1.38;
          const nextSpan = Math.max(0.08, Math.min(1, curSpan * factor));
          const anchor = zoomStart + ratio * curSpan;
          let nextS = anchor - ratio * nextSpan;
          let nextE = nextS + nextSpan;
          if (nextS < 0) {
            nextE -= nextS;
            nextS = 0;
          }
          if (nextE > 1) {
            nextS = Math.max(0, nextS - (nextE - 1));
            nextE = 1;
          }
          applyCanvasZoom(nextS, nextE);
        },
        { passive: false },
      );

      host.addEventListener("dblclick", () => {
        if (zoomEnd - zoomStart < 0.99) applyCanvasZoom(0, 1);
      });
      canvas.title = canvas.title || tr("Shift+框选放大 / 双击重置");
    });
  }

  /**
   * 5. 主页 Overview：紧凑微电网实时 KPI + 近 60 步 Sparkline + 能量流卡片微型进度条 + 点击穿透
   */
  const overviewSparkHistory = [];
  const OVERVIEW_SPARK_MAX = 60;
  let lastOverviewSig = "";

  const OVERVIEW_GROUP_PENETRATION_MAP = Object.freeze({
    dcWind: "DCWindGen",
    acWind: "ACWindGen",
    dcSolar: "DCPVGen",
    acSolar: "ACPVGen",
    dcStorage: "DCStorageGen",
    acStorage: "ACStorageGen",
    dcLoad: "DCLoad",
    acLoad: "ACLoad",
    diesel: "ACDieselGen",
    electrolyzer: "ACE2Hydro",
    fuelCell: "Hydro2DcE",
    hydrogenStorage: "HydroStorage",
  });

  function ensureOverviewLiveEnhancements() {
    const energyPanel = document.querySelector('.page-section[data-page="overview"] .overview-energy-panel');
    if (!energyPanel) return;
    if (!energyPanel.querySelector(".ux-overview-live-strip")) {
      const strip = document.createElement("div");
      strip.className = "ux-overview-live-strip";
      strip.innerHTML = `
        <div class="ux-overview-kpi-group">
          <div class="ux-overview-kpi"><span data-ux-zh="绿电占比"></span><strong id="uxKpiGreenShare">--</strong></div>
          <div class="ux-overview-kpi"><span data-ux-zh="总发电"></span><strong id="uxKpiTotalGen">--</strong></div>
          <div class="ux-overview-kpi"><span data-ux-zh="总负荷"></span><strong id="uxKpiTotalLoad">--</strong></div>
          <div class="ux-overview-kpi"><span data-ux-zh="母线电压"></span><strong id="uxKpiBusVoltage">--</strong></div>
          <div class="ux-overview-kpi"><span data-ux-zh="综合 SOC"></span><strong id="uxKpiAvgSoc">--</strong></div>
          <div class="ux-overview-kpi"><span data-ux-zh="储氢余量"></span><strong id="uxKpiHydrogen">--</strong></div>
        </div>
        <div class="ux-overview-sparkline-wrap">
          <span class="ux-overview-sparkline-legend">
            <span><i class="ux-spark-dot" style="background:var(--green)"></i><em data-ux-zh="绿电出力" style="font-style:normal"></em></span>
            <span><i class="ux-spark-dot" style="background:var(--teal)"></i><em data-ux-zh="净负荷" style="font-style:normal"></em></span>
          </span>
          <canvas id="uxOverviewSparkline" class="ux-overview-sparkline" width="264" height="48"></canvas>
        </div>
      `;
      energyPanel.prepend(strip);
      syncDynamicUxI18n(strip);
    }

    // 为能量流卡片挂载底部微型进度条与点击穿透事件
    energyPanel.querySelectorAll("[data-overview-group]").forEach((groupEl) => {
      const groupKey = groupEl.dataset.overviewGroup || "";
      const card = groupEl.querySelector(".energy-device-card");
      if (!card) return;
      if (!card.querySelector(".ux-energy-meter")) {
        const meter = document.createElement("div");
        meter.className = "ux-energy-meter";
        meter.innerHTML = '<div class="ux-energy-meter-fill"></div>';
        card.appendChild(meter);
      }
      if (card.dataset.uxPenetrationBound !== "true" && OVERVIEW_GROUP_PENETRATION_MAP[groupKey]) {
        card.dataset.uxPenetrationBound = "true";
        card.classList.add("ux-card-clickable");
        card.title = tr("点击查看同类量测（Alt+点击查看控制）");
        card.addEventListener("click", (event) => {
          const targetKeyword = OVERVIEW_GROUP_PENETRATION_MAP[groupKey];
          if (event.altKey) jumpToDeviceCommands(targetKeyword);
          else jumpToDeviceMeasurements(targetKeyword);
        });
      }
    });
  }

  function extractLiveOverviewMetrics() {
    const snap = typeof state !== "undefined" ? (state.snapshot || state.localSnapshot || null) : null;
    const overviewSection = document.querySelector('.page-section[data-page="overview"]');

    let renewableKw = 0;
    let dieselKw = 0;
    let loadKw = 0;
    let minPu = Infinity;
    let maxPu = -Infinity;
    const socList = [];
    const h2List = [];
    const violations = [];

    // 1. 优先从页面已由核心业务模块精准聚合的能量流卡片读取发电 / 负荷 / 储能 SOC / 储氢余量，保证与下方卡片 100% 一致
    if (overviewSection) {
      const readGroupPower = (key) => {
        const el = overviewSection.querySelector(`[data-overview-group="${key}"]`);
        if (!el || el.hidden) return 0;
        const val = parseNumericReading(el.querySelector("[data-overview-power]")?.textContent);
        return Number.isFinite(val) ? val : 0;
      };
      const dcWind = Math.max(0, readGroupPower("dcWind"));
      const acWind = Math.max(0, readGroupPower("acWind"));
      const dcSolar = Math.max(0, readGroupPower("dcSolar"));
      const acSolar = Math.max(0, readGroupPower("acSolar"));
      renewableKw = dcWind + acWind + dcSolar + acSolar;
      dieselKw = Math.max(0, readGroupPower("diesel"));
      const dcLoad = Math.abs(readGroupPower("dcLoad"));
      const acLoad = Math.abs(readGroupPower("acLoad"));
      const elecLoad = Math.max(0, readGroupPower("electrolyzer"));
      loadKw = dcLoad + acLoad + elecLoad;

      ["dcStorage", "acStorage", "dcGridFormingStorage", "acGridFormingStorage"].forEach((key) => {
        const el = overviewSection.querySelector(`[data-overview-group="${key}"]`);
        if (!el || el.hidden) return;
        const txt = `${el.querySelector("[data-overview-soc]")?.textContent || ""} ${el.querySelector("[data-overview-meta]")?.textContent || ""}`;
        const m = txt.match(/SOC\s*(\d+(?:\.\d+)?)\s*%/i);
        if (m) socList.push(Number(m[1]));
      });

      const h2El = overviewSection.querySelector('[data-overview-group="hydrogenStorage"]');
      if (h2El && !h2El.hidden) {
        const socVal = parseNumericReading(h2El.querySelector("[data-overview-soc]")?.textContent);
        const presVal = parseNumericReading(h2El.querySelector("[data-overview-gas-pressure]")?.textContent);
        if (Number.isFinite(socVal)) h2List.push(socVal);
        else if (Number.isFinite(presVal)) h2List.push(presVal);
      }
    }

    // 2. 从真实快照 measurements 数组或 devices 补充母线电压极值（p.u.）与越限节点列表
    if (snap) {
      const measRows = Array.isArray(snap.measurements)
        ? snap.measurements
        : (Array.isArray(snap.scada_measurements) ? snap.scada_measurements : []);
      for (let i = 0; i < measRows.length; i += 1) {
        const row = measRows[i];
        if (!row || typeof row !== "object") continue;
        const mKey = String(row.key || row.meas_type || row.field || row.name || "").toLowerCase();
        const devName = String(row.dev_name || row.device || row.name || "");
        const devType = String(row.dev_type || row.type || "");
        const val = Number(row.value ?? row.meas ?? row.val ?? row.v);
        if (!Number.isFinite(val)) continue;
        if ((/(?:^|_)(?:v_pu|u_pu|vm_pu|voltage_pu|u_mag)(?:$|_)/.test(mKey) || (/node/i.test(devType) && /(?:^|\.)v$|u_pu|v_pu/.test(mKey))) && val > 0.1 && val < 2.5) {
          if (val < minPu) minPu = val;
          if (val > maxPu) maxPu = val;
          if (val < 0.93 || val > 1.07) {
            violations.push({ name: devName || devType, score: Math.abs(val - 1), text: `${val.toFixed(3)} p.u.` });
          }
        }
        if (/loading|load_ratio/.test(mKey)) {
          const pct = val <= 2 ? val * 100 : val;
          if (pct >= 85) {
            violations.push({ name: devName || devType, score: pct / 100, text: `${pct.toFixed(0)}%` });
          }
        }
      }

      // 兼容结构化设备数组
      const devices = Array.isArray(snap.devices) ? snap.devices : [];
      for (let i = 0; i < devices.length; i += 1) {
        const d = devices[i];
        if (!d || typeof d !== "object") continue;
        const type = String(d.dev_type || d.type || "");
        const name = String(d.name || d.dev_name || "");
        const m = d.measurements || d.meas || d.state || d;
        const vpu = Number(m.v_pu ?? m.u_pu ?? m.vm_pu ?? d.v_pu);
        if (Number.isFinite(vpu) && vpu > 0.1 && vpu < 2.5) {
          if (vpu < minPu) minPu = vpu;
          if (vpu > maxPu) maxPu = vpu;
          if (vpu < 0.93 || vpu > 1.07) {
            violations.push({ name: name || type, score: Math.abs(vpu - 1), text: `${vpu.toFixed(3)} p.u.` });
          }
        }
      }
    }

    const totalGen = renewableKw + dieselKw;
    const greenShare = loadKw > 1e-4
      ? Math.max(0, Math.min(100, ((loadKw - dieselKw) / loadKw) * 100))
      : (totalGen > 1e-4 ? Math.min(100, (renewableKw / totalGen) * 100) : null);
    const avgSoc = socList.length ? socList.reduce((a, b) => a + b, 0) / socList.length : null;
    const avgH2 = h2List.length ? h2List.reduce((a, b) => a + b, 0) / h2List.length : null;
    violations.sort((a, b) => b.score - a.score);
    return {
      step: snap?.clock?.step_count ?? snap?.step_count ?? snap?.sim_time ?? document.getElementById("simTime")?.textContent ?? "",
      renewableKw,
      totalGen,
      loadKw,
      greenShare,
      minPu: Number.isFinite(minPu) ? minPu : null,
      maxPu: Number.isFinite(maxPu) ? maxPu : null,
      avgSoc,
      avgH2,
      violations: violations.slice(0, 3),
    };
  }

  function parseNumericReading(textVal) {
    const m = String(textVal || "").match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : NaN;
  }

  function drawOverviewSparkline() {
    const canvas = document.getElementById("uxOverviewSparkline");
    if (!canvas || !overviewSparkHistory.length) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const styles = getComputedStyle(document.documentElement);
    const greenColor = styles.getPropertyValue("--green").trim() || "#0d9488";
    const tealColor = styles.getPropertyValue("--teal").trim() || "#2563eb";
    const maxVal = Math.max(
      1,
      ...overviewSparkHistory.map((pt) => Math.max(pt.green, pt.load)),
    );
    const drawLine = (key, color) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      overviewSparkHistory.forEach((pt, idx) => {
        const x = overviewSparkHistory.length === 1 ? w / 2 : (idx / (overviewSparkHistory.length - 1)) * (w - 8) + 4;
        const y = h - 5 - (Math.max(0, pt[key]) / maxVal) * (h - 10);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    };
    drawLine("load", tealColor);
    drawLine("green", greenColor);
  }

  function updateOverviewLiveStripAndMeters(metrics) {
    const overviewSection = document.querySelector('.page-section[data-page="overview"]');
    if (!overviewSection || !overviewSection.classList.contains("is-active")) return;
    ensureOverviewLiveEnhancements();

    if (metrics) {
      const greenEl = document.getElementById("uxKpiGreenShare");
      const genEl = document.getElementById("uxKpiTotalGen");
      const loadEl = document.getElementById("uxKpiTotalLoad");
      const busEl = document.getElementById("uxKpiBusVoltage");
      const socEl = document.getElementById("uxKpiAvgSoc");
      const h2El = document.getElementById("uxKpiHydrogen");

      if (greenEl) {
        greenEl.textContent = metrics.greenShare == null ? "—" : `${metrics.greenShare.toFixed(1)}%`;
        greenEl.className = metrics.greenShare != null && metrics.greenShare >= 60 ? "is-ok" : "";
      }
      if (genEl) genEl.textContent = `${metrics.totalGen.toFixed(1)} kW`;
      if (loadEl) loadEl.textContent = `${metrics.loadKw.toFixed(1)} kW`;
      if (busEl) {
        if (metrics.minPu == null) {
          busEl.textContent = "—";
          busEl.className = "";
        } else {
          busEl.textContent = `${metrics.minPu.toFixed(3)}–${metrics.maxPu.toFixed(3)} p.u.`;
          busEl.className = metrics.minPu < 0.93 || metrics.maxPu > 1.07 ? "is-danger" : (metrics.minPu < 0.95 || metrics.maxPu > 1.05 ? "is-warn" : "is-ok");
        }
      }
      if (socEl) {
        socEl.textContent = metrics.avgSoc == null ? "—" : `${metrics.avgSoc.toFixed(1)}%`;
        socEl.className = metrics.avgSoc != null ? (metrics.avgSoc < 20 ? "is-danger" : metrics.avgSoc < 35 ? "is-warn" : "is-ok") : "";
      }
      if (h2El) {
        h2El.textContent = metrics.avgH2 == null ? "—" : (metrics.avgH2 <= 100 ? `${metrics.avgH2.toFixed(1)}%` : `${metrics.avgH2.toFixed(1)}`);
      }
      const sig = `${metrics.step}|${metrics.totalGen.toFixed(1)}|${metrics.loadKw.toFixed(1)}`;
      if (sig !== lastOverviewSig) {
        lastOverviewSig = sig;
        overviewSparkHistory.push({ green: metrics.renewableKw, load: metrics.loadKw });
        if (overviewSparkHistory.length > OVERVIEW_SPARK_MAX) overviewSparkHistory.shift();
      }
      drawOverviewSparkline();
    }

    // 同步能量流卡片底部微型进度条
    overviewSection.querySelectorAll("[data-overview-group]").forEach((groupEl) => {
      if (groupEl.hidden) return;
      const fill = groupEl.querySelector(".ux-energy-meter-fill");
      if (!fill) return;
      const socTxt = groupEl.querySelector("[data-overview-soc]")?.textContent || groupEl.querySelector("[data-overview-meta]")?.textContent || "";
      const socMatch = socTxt.match(/SOC\s*(\d+(?:\.\d+)?)\s*%/i) || (groupEl.querySelector("[data-overview-soc]") ? socTxt.match(/(\d+(?:\.\d+)?)/) : null);
      let pct = NaN;
      if (socMatch) {
        pct = Number(socMatch[1]);
      } else {
        const curP = Math.abs(parseNumericReading(groupEl.querySelector("[data-overview-power]")?.textContent));
        const maxP = Math.abs(parseNumericReading(groupEl.querySelector("[data-overview-max-available]")?.textContent));
        const targetP = Math.abs(parseNumericReading(groupEl.querySelector("[data-overview-target]")?.textContent));
        const denom = Math.max(maxP || 0, targetP || 0, 1);
        if (Number.isFinite(curP)) pct = Math.min(100, (curP / denom) * 100);
      }
      if (!Number.isFinite(pct)) pct = 0;
      const clamped = Math.max(0, Math.min(100, pct));
      fill.style.width = `${clamped.toFixed(1)}%`;
      fill.classList.remove("is-ok", "is-warn", "is-danger");
      if (socMatch) {
        fill.classList.add(clamped < 20 ? "is-danger" : clamped < 35 ? "is-warn" : "is-ok");
      } else if (clamped >= 92) {
        fill.classList.add("is-danger");
      } else if (clamped >= 78) {
        fill.classList.add("is-warn");
      } else if (clamped > 0) {
        fill.classList.add("is-ok");
      }
    });
  }

  /**
   * 6. 接线图增强：设备快搜框 + 右下角可拖拽 Minimap + 紧凑图例 + 负载热力色与越限脉冲 + 首次默认选中
   */
  let lastDiagramHeatSig = "";

  function renderDiagramMinimap(canvasHost, minimapCanvas) {
    const svg = canvasHost.querySelector("svg");
    if (!svg || !minimapCanvas) return;
    const ctx = minimapCanvas.getContext("2d");
    if (!ctx) return;
    const w = minimapCanvas.width;
    const h = minimapCanvas.height;
    ctx.clearRect(0, 0, w, h);

    const vb = svg.viewBox?.baseVal;
    const svgW = vb && vb.width > 0 ? vb.width : (svg.clientWidth || 1000);
    const svgH = vb && vb.height > 0 ? vb.height : (svg.clientHeight || 600);
    const vbX = vb ? vb.x : 0;
    const vbY = vb ? vb.y : 0;

    const styles = getComputedStyle(document.documentElement);
    const nodeColor = styles.getPropertyValue("--muted").trim() || "#64748b";
    const accentColor = styles.getPropertyValue("--teal").trim() || "#2563eb";
    const dangerColor = styles.getPropertyValue("--red").trim() || "#dc2626";

    const scale = Math.min((w - 10) / svgW, (h - 10) / svgH);
    const ox = (w - svgW * scale) / 2;
    const oy = (h - svgH * scale) / 2;

    const nodes = svg.querySelectorAll("[data-device-name], [data-dev-name], [id]");
    let drawn = 0;
    for (let i = 0; i < nodes.length && drawn < 260; i += 1) {
      const el = nodes[i];
      if (typeof el.getBBox !== "function") continue;
      const tag = String(el.tagName || "").toLowerCase();
      if (tag === "defs" || tag === "symbol" || tag === "clippath") continue;
      if (!el.dataset?.deviceName && !el.dataset?.devName && tag !== "g") continue;
      let box;
      try {
        box = el.getBBox();
      } catch (_e) {
        continue;
      }
      if (!box || (box.width <= 0 && box.height <= 0)) continue;
      const rx = ox + (box.x - vbX) * scale;
      const ry = oy + (box.y - vbY) * scale;
      const rw = Math.max(2, box.width * scale);
      const rh = Math.max(2, box.height * scale);
      ctx.fillStyle = el.classList.contains("ux-diagram-heat-danger") ? dangerColor : nodeColor;
      ctx.globalAlpha = el.classList.contains("ux-diagram-heat-danger") ? 0.9 : 0.45;
      ctx.fillRect(rx, ry, rw, rh);
      drawn += 1;
    }

    // 绘制当前画布可见视口框
    ctx.globalAlpha = 1;
    const hostRect = canvasHost.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    if (svgRect.width > 10 && svgRect.height > 10) {
      const visLeft = Math.max(0, (hostRect.left - svgRect.left) / svgRect.width);
      const visTop = Math.max(0, (hostRect.top - svgRect.top) / svgRect.height);
      const visW = Math.min(1, hostRect.width / svgRect.width);
      const visH = Math.min(1, hostRect.height / svgRect.height);
      ctx.strokeStyle = accentColor;
      ctx.lineWidth = 2;
      ctx.strokeRect(
        ox + visLeft * svgW * scale,
        oy + visTop * svgH * scale,
        Math.max(8, visW * svgW * scale),
        Math.max(6, visH * svgH * scale),
      );
    }
  }

  function enhanceDiagramHudAndMinimap() {
    const canvasHost = document.getElementById("modelDiagramCanvas");
    if (!canvasHost) return;
    const stage = canvasHost.parentElement || canvasHost;
    if (getComputedStyle(stage).position === "static") {
      stage.style.position = "relative";
    }
    if (!stage.querySelector(".ux-diagram-hud")) {
      const hud = document.createElement("div");
      hud.className = "ux-diagram-hud";
      hud.innerHTML = `
        <div class="ux-diagram-search-wrap">
          <input type="search" class="ux-diagram-search-input" placeholder="${tr("搜索接线图设备…")}" aria-label="${tr("搜索接线图设备…")}" />
          <ul class="ux-diagram-search-results" hidden></ul>
        </div>
      `;
      stage.appendChild(hud);

      const input = hud.querySelector(".ux-diagram-search-input");
      const list = hud.querySelector(".ux-diagram-search-results");
      if (input && list) {
        const updateSearch = () => {
          const q = String(input.value || "").trim().toLowerCase();
          if (!q) {
            list.hidden = true;
            return;
          }
          const matches = getCurrentSnapshotDevices()
            .map((d) => ({ name: String(d?.name || d?.dev_name || "").trim(), type: String(d?.dev_type || d?.type || "") }))
            .filter((d) => d.name && `${d.name} ${d.type}`.toLowerCase().includes(q))
            .slice(0, 12);
          list.replaceChildren();
          if (!matches.length) {
            list.hidden = true;
            return;
          }
          matches.forEach((m, idx) => {
            const li = document.createElement("li");
            if (idx === 0) li.classList.add("is-active");
            li.innerHTML = `<span>${m.name}</span><small>${m.type}</small>`;
            li.addEventListener("click", () => {
              if (typeof window.focusDiagramDeviceByName === "function") {
                window.focusDiagramDeviceByName(canvasHost, m.name);
              }
              list.hidden = true;
            });
            list.appendChild(li);
          });
          list.hidden = false;
        };
        input.addEventListener("input", updateSearch);
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            const first = list.querySelector("li");
            if (first) first.click();
          } else if (event.key === "Escape") {
            list.hidden = true;
            input.blur();
          }
        });
        document.addEventListener("click", (event) => {
          if (event.target instanceof Node && !hud.contains(event.target)) list.hidden = true;
        });
      }
    }

    if (!stage.querySelector(".ux-diagram-legend")) {
      const legend = document.createElement("div");
      legend.className = "ux-diagram-legend";
      legend.innerHTML = `
        <span class="ux-diagram-legend-item"><i class="ux-spark-dot" style="background:var(--teal)"></i>${tr("电/氢流")}</span>
        <span class="ux-diagram-legend-item"><i class="ux-spark-dot" style="background:var(--green)"></i>${tr("正常")}</span>
        <span class="ux-diagram-legend-item"><i class="ux-spark-dot" style="background:var(--amber)"></i>${tr("重载")}</span>
        <span class="ux-diagram-legend-item"><i class="ux-spark-dot" style="background:var(--red)"></i>${tr("越限")}</span>
      `;
      stage.appendChild(legend);
    }

    if (!stage.querySelector(".ux-diagram-minimap")) {
      const mini = document.createElement("div");
      mini.className = "ux-diagram-minimap";
      mini.innerHTML = `
        <button type="button" class="ux-diagram-minimap-toggle" title="${tr("收起缩略图")}">${tr("缩略图")}</button>
        <canvas class="ux-diagram-minimap-canvas" width="312" height="200"></canvas>
      `;
      stage.appendChild(mini);
      const toggleBtn = mini.querySelector(".ux-diagram-minimap-toggle");
      const miniCanvas = mini.querySelector(".ux-diagram-minimap-canvas");
      if (toggleBtn) {
        toggleBtn.addEventListener("click", (event) => {
          event.stopPropagation();
          const collapsed = mini.classList.toggle("is-collapsed");
          toggleBtn.title = collapsed ? tr("展开缩略图") : tr("收起缩略图");
        });
      }
      if (miniCanvas) {
        miniCanvas.addEventListener("click", (event) => {
          const svg = canvasHost.querySelector("svg");
          if (!svg) return;
          const rect = miniCanvas.getBoundingClientRect();
          const rx = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
          const ry = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
          if (canvasHost.scrollWidth > canvasHost.clientWidth) {
            canvasHost.scrollLeft = rx * canvasHost.scrollWidth - canvasHost.clientWidth / 2;
          }
          if (canvasHost.scrollHeight > canvasHost.clientHeight) {
            canvasHost.scrollTop = ry * canvasHost.scrollHeight - canvasHost.clientHeight / 2;
          }
          renderDiagramMinimap(canvasHost, miniCanvas);
        });
      }
    }
  }

  function updateDiagramLiveEnhancements(metrics) {
    const diagSection = document.querySelector('.page-section[data-page="diagram"]');
    if (!diagSection || !diagSection.classList.contains("is-active")) return;
    enhanceDiagramHudAndMinimap();
    const canvasHost = document.getElementById("modelDiagramCanvas");
    const svg = canvasHost?.querySelector("svg");
    if (!canvasHost || !svg) return;

    // 首次进入且无选中对象时，自动选中首条越限设备或首条主力电源/母线（对齐最新 Skill 4.3）
    if (!canvasHost.dataset.selectedDeviceName && canvasHost.dataset.uxAutoSelectedOnce !== "true") {
      const devices = getCurrentSnapshotDevices();
      const firstViolation = metrics?.violations?.[0]?.name || "";
      const fallbackDev = devices.find((d) => /Wind|PV|Storage|Diesel|Node/i.test(String(d?.dev_type || d?.type || "")))?.name
        || devices[0]?.name
        || "";
      const pick = firstViolation || fallbackDev;
      if (pick) {
        canvasHost.dataset.uxAutoSelectedOnce = "true";
        canvasHost.dataset.selectedDeviceName = pick;
        canvasHost.dispatchEvent(new CustomEvent("ux-diagram-selection", { detail: { name: pick } }));
      }
    }

    // 支路负载热力着色与越限脉冲（按步号签名跳过无变化帧）
    const sig = String(metrics?.step ?? "");
    if (sig && sig !== lastDiagramHeatSig) {
      lastDiagramHeatSig = sig;
      const dangerSet = new Set();
      const warnSet = new Set();
      getCurrentSnapshotDevices().forEach((d) => {
        const name = String(d?.name || d?.dev_name || "").trim();
        if (!name) return;
        const m = d.measurements || d.meas || d.state || d;
        const vpu = Number(m.v_pu ?? m.u_pu ?? m.vm_pu ?? d.v_pu);
        const lr = Number(m.loading_percent ?? m.load_ratio ?? d.loading_percent);
        const pct = Number.isFinite(lr) ? (lr <= 2 ? lr * 100 : lr) : NaN;
        if ((Number.isFinite(vpu) && (vpu < 0.93 || vpu > 1.07)) || (Number.isFinite(pct) && pct >= 95)) {
          dangerSet.add(name);
        } else if ((Number.isFinite(vpu) && (vpu < 0.95 || vpu > 1.05)) || (Number.isFinite(pct) && pct >= 80)) {
          warnSet.add(name);
        }
      });
      svg.querySelectorAll("[data-device-name], [data-dev-name]").forEach((el) => {
        const name = el.dataset.deviceName || el.dataset.devName || "";
        el.classList.toggle("ux-diagram-heat-danger", dangerSet.has(name));
        el.classList.toggle("ux-diagram-heat-warn", !dangerSet.has(name) && warnSet.has(name));
      });
    }

    const miniCanvas = canvasHost.parentElement?.querySelector(".ux-diagram-minimap:not(.is-collapsed) .ux-diagram-minimap-canvas");
    if (miniCanvas) renderDiagramMinimap(canvasHost, miniCanvas);
  }

  /**
   * 7. 实时性能延迟可观测胶囊 & 顶栏越限 Top-3 摘要浮层
   */
  const perfStats = {
    lastLatencyMs: 0,
    maxLatencyMs: 0,
    samples: 0,
    errors: 0,
  };

  function installFetchLatencyProbe() {
    if (typeof window.fetch !== "function" || window.__polarFetchProbeInstalled) return;
    window.__polarFetchProbeInstalled = true;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function wrappedPolarFetch(input, init) {
      const url = typeof input === "string" ? input : String(input?.url || "");
      const track = /\/api\/(?:snapshot|trainee\/ui-frame|measurements\/delta|simulator104\/status)/.test(url);
      if (!track) return nativeFetch(input, init);
      const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
      return nativeFetch(input, init)
        .then((resp) => {
          const dt = Math.round((typeof performance !== "undefined" ? performance.now() : Date.now()) - t0);
          perfStats.lastLatencyMs = dt;
          perfStats.maxLatencyMs = Math.max(perfStats.maxLatencyMs, dt);
          perfStats.samples += 1;
          if (!resp.ok) perfStats.errors += 1;
          updatePerfPillDisplay();
          return resp;
        })
        .catch((err) => {
          perfStats.errors += 1;
          updatePerfPillDisplay();
          throw err;
        });
    };
  }

  function updatePerfPillDisplay() {
    const pill = document.getElementById("uxPerfTelemetryPill");
    if (!pill) return;
    const dot = pill.querySelector(".ux-perf-dot");
    const textEl = pill.querySelector(".ux-perf-text");
    const ms = perfStats.lastLatencyMs;
    if (textEl) textEl.textContent = perfStats.samples ? `${ms}ms` : "—";
    if (dot) {
      dot.classList.remove("is-warn", "is-danger");
      if (perfStats.errors > 0 && ms > 800) dot.classList.add("is-danger");
      else if (ms > 300) dot.classList.add("is-warn");
    }
    pill.title = `${tr("查看性能状态")} · ${ms}ms (max ${perfStats.maxLatencyMs}ms, req ${perfStats.samples}, err ${perfStats.errors})`;
    syncTopbarHubReadouts();
  }

  function ensurePerfPillAndAlertPopover() {
    const utilityGroup = document.querySelector(".topbar-utility-group");
    if (utilityGroup && !document.getElementById("uxPerfTelemetryPill")) {
      const pill = document.createElement("button");
      pill.id = "uxPerfTelemetryPill";
      pill.type = "button";
      pill.className = "ux-perf-pill";
      pill.title = tr("查看性能状态");
      pill.innerHTML = '<span class="ux-perf-dot" aria-hidden="true"></span><span class="ux-perf-text" data-i18n-skip="true">—</span>';
      pill.addEventListener("click", () => {
        if (typeof showUiToast === "function") {
          showUiToast(`API ${perfStats.lastLatencyMs}ms / max ${perfStats.maxLatencyMs}ms / req ${perfStats.samples} / err ${perfStats.errors}`, "info", 2600);
        }
      });
      utilityGroup.prepend(pill);
    }

    const alertBadge = document.getElementById("topbarAlertBadge");
    if (alertBadge && alertBadge.dataset.uxAlertPopoverBound !== "true") {
      alertBadge.dataset.uxAlertPopoverBound = "true";
      const pop = document.createElement("div");
      pop.id = "uxAlertTop3Popover";
      pop.className = "ux-alert-summary-popover";
      pop.hidden = true;
      document.body.appendChild(pop);

      const showTop3 = () => {
        const metrics = extractLiveOverviewMetrics();
        const items = metrics?.violations || [];
        if (!items.length) return;
        pop.innerHTML = `
          <div class="ux-alert-summary-head">
            <span>${tr("越限 Top-3")}</span>
            <button type="button" class="compact-action-btn" data-close-alert-pop>${tr("关闭")}</button>
          </div>
          <ul class="ux-alert-summary-list">
            ${items.map((it) => `<li class="ux-alert-summary-item" data-jump-dev="${it.name}"><strong>${it.name}</strong><span>${it.text}</span></li>`).join("")}
          </ul>
        `;
        pop.querySelector("[data-close-alert-pop]")?.addEventListener("click", () => {
          pop.hidden = true;
        });
        pop.querySelectorAll("[data-jump-dev]").forEach((li) => {
          li.addEventListener("click", () => {
            pop.hidden = true;
            locateDeviceOnDiagram(li.dataset.jumpDev);
          });
        });
        const rect = alertBadge.getBoundingClientRect();
        pop.hidden = false;
        pop.style.top = `${Math.round(rect.bottom + 6)}px`;
        pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 320, rect.right - 310))}px`;
      };
      alertBadge.addEventListener("mouseenter", showTop3);
      document.addEventListener("click", (event) => {
        if (!pop.hidden && event.target instanceof Node && !pop.contains(event.target) && !alertBadge.contains(event.target)) {
          pop.hidden = true;
        }
      });
    }
  }

  let liveEnhanceTimerId = null;

  /**
   * 8. 动态注入节点三语同步 + 双端顶栏极简三胶囊聚合架构（模型管理 / 时钟管理 / 显示管理）
   */
  function syncDynamicUxI18n(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-ux-zh]").forEach((el) => {
      const zh = el.dataset.uxZh || "";
      if (!zh) return;
      el.textContent = tr(zh);
    });
    const swatchContainer = document.getElementById("uxDisplayHubSwatches");
    if (swatchContainer) renderDisplayHubSwatches(swatchContainer, true);
  }

  function renderDisplayHubSwatches(container, forceRebuild = false) {
    if (!container) return;
    const currentId = document.documentElement.dataset.theme || "minimalist-light";
    if (!forceRebuild && container.dataset.uxSwatchesBuilt === "true") {
      container.querySelectorAll(".ux-theme-card").forEach((card) => {
        card.classList.toggle("is-active", card.dataset.themeId === currentId);
      });
      return;
    }
    container.dataset.uxSwatchesBuilt = "true";
    container.innerHTML = UX_THEME_GROUPS.map((g) => {
      const groupTitle = typeof t === "function" ? t(g.labelKey) : tr(g.fallback);
      const cardsHtml = g.ids
        .map((id) => {
          const name = typeof t === "function" ? t(`theme.${id}`) : id;
          const activeCls = id === currentId ? " is-active" : "";
          return `<button type="button" class="ux-theme-card${activeCls}" data-theme-id="${id}"><span>${name}</span>${renderThemeSwatchDots(id)}</button>`;
        })
        .join("");
      return `<div class="ux-theme-group-title">${groupTitle}</div><div class="ux-theme-grid">${cardsHtml}</div>`;
    }).join("");
    container.querySelectorAll(".ux-theme-card").forEach((card) => {
      card.addEventListener("click", () => {
        const nextId = card.dataset.themeId;
        if (!nextId) return;
        if (typeof applyUiTheme === "function") {
          applyUiTheme(nextId, { persist: true, notify: true, redraw: true });
        } else {
          const sel = document.getElementById("themeSelector");
          if (sel) {
            sel.value = nextId;
            sel.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
        syncThemeQuickButtons();
        syncTopbarHubReadouts();
        renderDisplayHubSwatches(container, false);
      });
    });
  }

  const topbarHubInstances = [];

  function closeAllTopbarHubs(exceptHub = null) {
    topbarHubInstances.forEach((hub) => {
      if (hub === exceptHub) return;
      hub.classList.remove("is-open", "is-pinned");
      const trig = hub.querySelector(".ux-hub-trigger");
      trig?.setAttribute("aria-expanded", "false");
      const active = document.activeElement;
      if (active && hub.contains(active) && typeof active.blur === "function") {
        active.blur();
      }
    });
  }

  function bindHubHoverAndPin(hub, trigger) {
    if (!hub || !trigger) return;
    topbarHubInstances.push(hub);
    let closeTimer = null;
    const openHub = (pin = false) => {
      clearTimeout(closeTimer);
      closeAllTopbarHubs(hub);
      hub.classList.add("is-open");
      if (pin) hub.classList.add("is-pinned");
      trigger.setAttribute("aria-expanded", "true");
    };
    const scheduleClose = () => {
      clearTimeout(closeTimer);
      closeTimer = setTimeout(() => {
        if (hub.classList.contains("is-pinned")) return;
        const active = document.activeElement;
        if (active && hub.contains(active) && (active.tagName === "SELECT" || active.tagName === "INPUT")) return;
        hub.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");
      }, 260);
    };
    hub.addEventListener("mouseenter", () => openHub(false));
    hub.addEventListener("mouseleave", scheduleClose);
    const popover = hub.querySelector(".ux-hub-popover");
    popover?.addEventListener("pointerdown", () => {
      // 用户在悬浮面板内开始点击/下拉选择时自动锁定面板，避免展开原生下拉列表时触发 mouseleave 误关
      openHub(true);
    });
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (hub.classList.contains("is-open") && hub.classList.contains("is-pinned")) {
        hub.classList.remove("is-open", "is-pinned");
        trigger.setAttribute("aria-expanded", "false");
      } else {
        openHub(true);
      }
    });
  }

  function syncTopbarHubReadouts() {
    const isTrainee = Boolean(document.getElementById("traineeRunToggle"));
    // 1. 模型胶囊当前值同步
    const modelSel = document.getElementById("modelSelector");
    const activeModelSpan = document.getElementById("activeModelName");
    const modelName = (
      modelSel?.options?.[modelSel.selectedIndex]?.text
      || activeModelSpan?.textContent
      || "—"
    ).trim();
    const modelPrimary = document.getElementById("uxModelHubName");
    if (modelPrimary) modelPrimary.textContent = modelName || "—";
    const crestModel = document.getElementById("uxCrestModel");
    if (crestModel) crestModel.textContent = modelName || "—";

    const modelSub = document.getElementById("uxModelHubSub");
    const modelDot = document.getElementById("uxModelHubDot");
    if (isTrainee) {
      const connText = (document.getElementById("connectionText")?.textContent || "").trim();
      const connDot = document.getElementById("connectionDot");
      if (modelSub) modelSub.textContent = connText || "—";
      if (modelDot) {
        const cls = connDot?.className || "";
        const st = connDot?.dataset?.state || "";
        if (/connected|ok|running/i.test(cls + st) || /已连接|接收中|Connected/i.test(connText)) {
          modelDot.dataset.state = "connected";
        } else if (/error|fail|disconnect|中断|失败/i.test(cls + st + connText)) {
          modelDot.dataset.state = "error";
        } else if (/重连|等待|连接中|Connecting|Reconnect/i.test(connText)) {
          modelDot.dataset.state = "warn";
        } else {
          modelDot.dataset.state = "stopped";
        }
      }
    } else {
      const modeSel = document.getElementById("simulationModeSelector");
      const modeTxt = (modeSel?.options?.[modeSel.selectedIndex]?.text || "").trim();
      const svcStateEl = document.getElementById("modelServiceState");
      const svcState = svcStateEl?.dataset?.state || "";
      const svcTxt = (svcStateEl?.textContent || "").trim();
      if (modelSub) modelSub.textContent = modeTxt || svcTxt || "—";
      if (modelDot) {
        modelDot.dataset.state = svcState === "running" ? "running" : (svcState === "error" ? "error" : "stopped");
      }
    }

    // 2. 时钟胶囊当前值同步
    const simTimeEl = document.getElementById("simTime");
    const clockTimeEl = document.getElementById("uxClockHubTime");
    if (clockTimeEl && simTimeEl) {
      clockTimeEl.textContent = (simTimeEl.textContent || "00:00:00").trim();
    }
    const speedSrc = document.getElementById("overviewClockSpeed") || document.getElementById("simSpeed");
    const clockSpeedEl = document.getElementById("uxClockHubSpeed");
    if (clockSpeedEl && speedSrc) {
      clockSpeedEl.textContent = (speedSrc.textContent || "x1").trim();
    }
    const clockDot = document.getElementById("uxClockHubDot");
    if (clockDot) {
      const rawClockState = (
        document.getElementById("topbarClockControls")?.dataset?.clockState
        || document.getElementById("simState")?.textContent
        || ""
      ).trim().toLowerCase();
      clockDot.dataset.state = rawClockState === "running" ? "running" : (rawClockState === "paused" ? "paused" : "stopped");
    }

    // 3. 显示胶囊当前值同步（主题 3 色点 + 语言简码 + 接口延迟）
    const curTheme = document.documentElement.dataset.theme || "minimalist-light";
    const swatchSlot = document.getElementById("uxDisplayHubSwatchDots");
    if (swatchSlot) swatchSlot.innerHTML = renderThemeSwatchDots(curTheme);
    const curLang = document.documentElement.lang || "zh-CN";
    const langCodeMap = { "zh-CN": "中", "en-US": "EN", "ru-RU": "RU" };
    const langShortEl = document.getElementById("uxDisplayHubLang");
    if (langShortEl) langShortEl.textContent = langCodeMap[curLang] || "中";
    const perfShortEl = document.getElementById("uxDisplayHubPerf");
    if (perfShortEl) perfShortEl.textContent = perfStats.samples ? `${perfStats.lastLatencyMs}ms` : "—";
    const perfDotEl = document.getElementById("uxDisplayHubPerfDot");
    if (perfDotEl) {
      perfDotEl.classList.remove("is-warn", "is-danger");
      if (perfStats.errors > 0 && perfStats.lastLatencyMs > 800) perfDotEl.classList.add("is-danger");
      else if (perfStats.lastLatencyMs > 300) perfDotEl.classList.add("is-warn");
    }
  }

  function initCompactTopbarHubs() {
    const topbar = document.querySelector("header.topbar");
    if (!topbar || topbar.dataset.uxHubCollapsed === "true") return;
    if (!document.getElementById("themeSelector") || !document.getElementById("langSelector")) return;
    topbar.dataset.uxHubCollapsed = "true";
    topbar.classList.add("ux-topbar-compact");

    const isTrainee = Boolean(document.getElementById("traineeRunToggle"));

    // 顶栏最左侧注入常驻极简「左栏显隐」按钮（内嵌与悬浮模式通用，一键隐藏或呼出左栏）
    const brandEl = topbar.querySelector(".brand");
    if (brandEl && !document.getElementById("uxSidebarToggleBtn")) {
      const sbToggle = document.createElement("button");
      sbToggle.id = "uxSidebarToggleBtn";
      sbToggle.type = "button";
      sbToggle.className = "ux-sidebar-topbar-btn";
      sbToggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>';
      sbToggle.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        window.__polarSidebarControl?.toggleHidden();
      });
      brandEl.prepend(sbToggle);
    }

    const hubsWrap = document.createElement("div");
    hubsWrap.className = "ux-topbar-hubs";

    // 按需告警徽章紧邻三胶囊左侧
    const alertBadge = document.getElementById("topbarAlertBadge");
    if (alertBadge) hubsWrap.appendChild(alertBadge);

    const chevronSvg = '<svg class="ux-hub-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>';

    // ---------------- 分块 ①：模型管理胶囊 ----------------
    const modelHub = document.createElement("div");
    modelHub.id = "uxModelHub";
    modelHub.className = "ux-hub";
    const modelTrigger = document.createElement("button");
    modelTrigger.id = "uxModelHubTrigger";
    modelTrigger.type = "button";
    modelTrigger.className = "ux-hub-trigger";
    modelTrigger.setAttribute("aria-haspopup", "true");
    modelTrigger.setAttribute("aria-expanded", "false");
    modelTrigger.innerHTML = `
      <span id="uxModelHubDot" class="ux-hub-dot" data-state="stopped" aria-hidden="true"></span>
      <span id="uxModelHubName" class="ux-hub-primary">—</span>
      <span class="ux-hub-sep" aria-hidden="true">·</span>
      <span id="uxModelHubSub" class="ux-hub-sub">—</span>
      ${chevronSvg}
    `;
    const modelPop = document.createElement("div");
    modelPop.id = "uxModelHubPopover";
    modelPop.className = "ux-hub-popover";

    const modelHead = document.createElement("div");
    modelHead.className = "ux-hub-popover-head";
    const modelTitle = document.createElement("span");
    modelTitle.className = "ux-hub-popover-title";
    modelTitle.dataset.uxZh = isTrainee ? "模型与接收" : "模型与运行";
    const modelMeta = document.createElement("span");
    modelMeta.className = "ux-hub-popover-meta";
    modelHead.append(modelTitle, modelMeta);
    modelPop.appendChild(modelHead);

    const modelSwitcher = document.querySelector(".model-switcher");
    if (modelSwitcher) {
      const row1 = document.createElement("div");
      row1.className = "ux-hub-row";
      const lbl1 = document.createElement("span");
      lbl1.className = "ux-hub-row-label";
      lbl1.dataset.uxZh = "当前模型";
      row1.append(lbl1, modelSwitcher);
      modelPop.appendChild(row1);
    }

    if (isTrainee) {
      const diagBtn = document.getElementById("openTraineeDiagnosticsBtn");
      if (diagBtn) {
        const diagP = diagBtn.closest("p");
        modelMeta.appendChild(diagBtn);
        if (diagP && !diagP.textContent?.trim()) diagP.remove();
      }
      const actions = document.createElement("div");
      actions.className = "ux-hub-actions";
      const runToggle = document.getElementById("traineeRunToggle");
      const initBtn = document.getElementById("modelInitializeButton");
      const mgmtBtn = document.getElementById("modelManagementButton");
      if (runToggle) actions.appendChild(runToggle);
      if (initBtn) actions.appendChild(initBtn);
      if (mgmtBtn) actions.appendChild(mgmtBtn);
      modelPop.appendChild(actions);
    } else {
      const svcState = document.getElementById("modelServiceState");
      if (svcState) modelMeta.appendChild(svcState);
      const modeSwitcher = document.querySelector(".simulation-mode-switcher");
      if (modeSwitcher) {
        const row2 = document.createElement("div");
        row2.className = "ux-hub-row";
        const lbl2 = document.createElement("span");
        lbl2.className = "ux-hub-row-label";
        lbl2.dataset.uxZh = "仿真模式";
        row2.append(lbl2, modeSwitcher);
        modelPop.appendChild(row2);
      }
      const actions = document.createElement("div");
      actions.className = "ux-hub-actions";
      const svcToggle = document.getElementById("modelServiceToggle");
      const mgmtBtn = document.getElementById("modelManagementButton");
      const linkBtn = document.getElementById("traineeLinkButton");
      if (svcToggle) actions.appendChild(svcToggle);
      if (mgmtBtn) actions.appendChild(mgmtBtn);
      if (linkBtn) actions.appendChild(linkBtn);
      modelPop.appendChild(actions);
    }
    modelHub.append(modelTrigger, modelPop);
    bindHubHoverAndPin(modelHub, modelTrigger);
    hubsWrap.appendChild(modelHub);

    // 清理旧的空 .model-toolbar 容器
    const oldModelToolbar = topbar.querySelector(".model-toolbar");
    if (oldModelToolbar) oldModelToolbar.classList.add("ux-hub-hidden-slot");

    // ---------------- 分块 ②：时钟管理胶囊 ----------------
    const clockHub = document.createElement("div");
    clockHub.id = "uxClockHub";
    clockHub.className = "ux-hub";
    const clockTrigger = document.createElement("button");
    clockTrigger.id = "uxClockHubTrigger";
    clockTrigger.type = "button";
    clockTrigger.className = "ux-hub-trigger";
    clockTrigger.setAttribute("aria-haspopup", "true");
    clockTrigger.setAttribute("aria-expanded", "false");
    clockTrigger.innerHTML = `
      <span id="uxClockHubDot" class="ux-hub-dot" data-state="stopped" aria-hidden="true"></span>
      <span id="uxClockHubTime" class="ux-hub-primary ux-hub-mono">00:00:00</span>
      <span class="ux-hub-sep" aria-hidden="true">·</span>
      <span id="uxClockHubSpeed" class="ux-hub-sub ux-hub-mono">x1</span>
      ${isTrainee ? "" : chevronSvg}
    `;
    clockHub.appendChild(clockTrigger);

    const oldClockStrip = topbar.querySelector(".clock-strip");
    if (oldClockStrip) oldClockStrip.classList.add("ux-hub-hidden-slot");

    const topbarClockControls = document.getElementById("topbarClockControls");
    const clockPopover = document.getElementById("clockControlPopover");
    if (!isTrainee && clockPopover) {
      const clockPop = document.createElement("div");
      clockPop.id = "uxClockHubPopover";
      clockPop.className = "ux-hub-popover";
      clockPop.appendChild(clockPopover);
      clockHub.appendChild(clockPop);
      if (topbarClockControls) topbarClockControls.classList.add("ux-hub-hidden-slot");
      bindHubHoverAndPin(clockHub, clockTrigger);
    }
    hubsWrap.appendChild(clockHub);

    // ---------------- 分块 ③：显示管理胶囊 ----------------
    const displayHub = document.createElement("div");
    displayHub.id = "uxDisplayHub";
    displayHub.className = "ux-hub";
    const displayTrigger = document.createElement("button");
    displayTrigger.id = "uxDisplayHubTrigger";
    displayTrigger.type = "button";
    displayTrigger.className = "ux-hub-trigger";
    displayTrigger.setAttribute("aria-haspopup", "true");
    displayTrigger.setAttribute("aria-expanded", "false");
    displayTrigger.innerHTML = `
      <span id="uxDisplayHubSwatchDots">${renderThemeSwatchDots(document.documentElement.dataset.theme || "minimalist-light")}</span>
      <span class="ux-hub-sep" aria-hidden="true">·</span>
      <span id="uxDisplayHubLang" class="ux-hub-primary">中</span>
      <span class="ux-hub-sep" aria-hidden="true">·</span>
      <span id="uxDisplayHubPerfDot" class="ux-perf-dot" aria-hidden="true"></span>
      <span id="uxDisplayHubPerf" class="ux-hub-sub ux-hub-mono">—</span>
      ${chevronSvg}
    `;

    const displayPop = document.createElement("div");
    displayPop.id = "uxDisplayHubPopover";
    displayPop.className = "ux-hub-popover ux-hub-display-popover";

    const displayHead = document.createElement("div");
    displayHead.className = "ux-hub-popover-head";
    const displayTitle = document.createElement("span");
    displayTitle.className = "ux-hub-popover-title";
    displayTitle.dataset.uxZh = "显示与工具";
    displayHead.appendChild(displayTitle);
    const perfPill = document.getElementById("uxPerfTelemetryPill");
    if (perfPill) displayHead.appendChild(perfPill);
    displayPop.appendChild(displayHead);

    const quickBar = document.createElement("div");
    quickBar.className = "ux-hub-quick-bar";
    const cmdBtn = document.getElementById("uxCommandPaletteButton");
    if (cmdBtn) quickBar.appendChild(cmdBtn);
    const dayNightBtn = document.getElementById("uxDayNightToggleBtn");
    if (dayNightBtn) {
      dayNightBtn.classList.add("compact-action-btn");
      quickBar.appendChild(dayNightBtn);
    }
    // 保留独立的旧色卡按钮隐藏（色卡已直接内嵌在显示管理面板中，一跳直达）
    const oldSwatchBtn = document.getElementById("uxThemeSwatchBtn");
    if (oldSwatchBtn) oldSwatchBtn.classList.add("ux-hub-hidden-slot");
    displayPop.appendChild(quickBar);

    const langSwitcher = document.querySelector(".lang-switcher");
    if (langSwitcher) {
      const langRow = document.createElement("div");
      langRow.className = "ux-hub-row";
      langRow.appendChild(langSwitcher);
      displayPop.appendChild(langRow);
    }
    const themeSwitcher = document.querySelector(".theme-switcher");
    if (themeSwitcher) {
      const themeRow = document.createElement("div");
      themeRow.className = "ux-hub-row";
      themeRow.appendChild(themeSwitcher);
      displayPop.appendChild(themeRow);
    }

    // 左栏模式（内嵌 / 悬浮）与显隐控制行
    const sidebarRow = document.createElement("div");
    sidebarRow.className = "ux-hub-row ux-sidebar-mode-row";
    sidebarRow.innerHTML = `
      <span class="ux-hub-row-label" data-ux-zh="左栏"></span>
      <div class="ux-sidebar-mode-seg" role="group" aria-label="左栏模式">
        <button type="button" data-ux-sidebar-mode="docked"><span data-ux-zh="内嵌"></span></button>
        <button type="button" data-ux-sidebar-mode="overlay"><span data-ux-zh="悬浮"></span></button>
      </div>
      <button id="uxDisplaySidebarHideBtn" type="button" class="compact-action-btn ux-sidebar-disp-hide"></button>
    `;
    sidebarRow.querySelectorAll("[data-ux-sidebar-mode]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        window.__polarSidebarControl?.setMode(btn.dataset.uxSidebarMode);
      });
    });
    sidebarRow.querySelector("#uxDisplaySidebarHideBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      window.__polarSidebarControl?.toggleHidden();
    });
    displayPop.appendChild(sidebarRow);

    const swatchesBox = document.createElement("div");
    swatchesBox.id = "uxDisplayHubSwatches";
    swatchesBox.className = "ux-hub-display-swatches";
    renderDisplayHubSwatches(swatchesBox);
    displayPop.appendChild(swatchesBox);

    displayHub.append(displayTrigger, displayPop);
    bindHubHoverAndPin(displayHub, displayTrigger);
    hubsWrap.appendChild(displayHub);

    const oldUtility = topbar.querySelector(".topbar-utility-group");
    if (oldUtility) oldUtility.classList.add("ux-hub-hidden-slot");

    // 全站共享中央梯形主桥徽标（从大屏提升至顶栏，各页面共享）
    const crestWrap = document.createElement("div");
    crestWrap.id = "uxTopbarCrest";
    crestWrap.className = "ux-topbar-crest";
    const crestTitleZh = isTrainee ? "极地微电网智能调控大屏" : "极地微电网仿真主控大屏";
    crestWrap.innerHTML = `
      <div class="ux-crest-plate">
        <span class="ux-crest-wing left" aria-hidden="true"></span>
        <span id="uxCrestTitle" class="ux-crest-title" data-ux-zh="${crestTitleZh}"></span>
        <span id="uxCrestModel" class="ux-crest-model">—</span>
        <span class="ux-crest-wing right" aria-hidden="true"></span>
      </div>
    `;
    topbar.appendChild(crestWrap);

    // 全站共享「沉浸全屏」极简按钮（位于右侧胶囊区末尾，所有页面可用）
    const immBtn = document.createElement("button");
    immBtn.id = "scImmersiveToggle";
    immBtn.type = "button";
    immBtn.className = "ux-topbar-immersive-btn";
    immBtn.dataset.uxTitleZh = "沉浸全屏";
    immBtn.title = tr("沉浸全屏");
    immBtn.setAttribute("aria-label", tr("沉浸全屏"));
    immBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
    immBtn.addEventListener("click", () => {
      const active = document.documentElement.dataset.scadaImmersive === "true";
      if (active) {
        delete document.documentElement.dataset.scadaImmersive;
        immBtn.classList.remove("is-active");
      } else {
        document.documentElement.dataset.scadaImmersive = "true";
        immBtn.classList.add("is-active");
      }
      window.dispatchEvent(new Event("resize"));
    });
    hubsWrap.appendChild(immBtn);

    topbar.appendChild(hubsWrap);

    // 全局点击外部或 Esc 收起悬浮面板（兼容内部按钮点击后自刷新导致原 SVG target 脱离 DOM 的场景）
    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (target.isConnected === false) return;
      const path = typeof event.composedPath === "function" ? event.composedPath() : null;
      if (topbarHubInstances.some((h) => h.contains(target) || (path && path.includes(h)))) return;
      closeAllTopbarHubs();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeAllTopbarHubs();
    });

    // 监听语言、主题、模型与仿真模式切换，实时刷新胶囊读数与动态标签
    document.getElementById("langSelector")?.addEventListener("change", () => {
      setTimeout(() => {
        syncDynamicUxI18n(document);
        syncTopbarHubReadouts();
        window.__polarSidebarControl?.syncUi();
      }, 20);
    });
    document.getElementById("themeSelector")?.addEventListener("change", () => {
      setTimeout(() => {
        syncTopbarHubReadouts();
        renderDisplayHubSwatches(swatchesBox);
      }, 10);
    });
    document.getElementById("modelSelector")?.addEventListener("change", () => setTimeout(syncTopbarHubReadouts, 20));
    document.getElementById("simulationModeSelector")?.addEventListener("change", () => setTimeout(syncTopbarHubReadouts, 20));

    // 对仿真时钟、倍率与连接态节点建立零延迟观察，避免 1.2s 轮询造成胶囊显示滞后
    if (typeof MutationObserver === "function") {
      let readoutSyncRaf = 0;
      const scheduleReadoutSync = () => {
        if (readoutSyncRaf) return;
        readoutSyncRaf = requestAnimationFrame(() => {
          readoutSyncRaf = 0;
          syncTopbarHubReadouts();
        });
      };
      const clockObs = new MutationObserver(scheduleReadoutSync);
      ["simTime", "simSpeed", "overviewClockSpeed", "simState", "connectionText", "modelServiceState", "activeModelName"].forEach((id) => {
        const node = document.getElementById(id);
        if (node) clockObs.observe(node, { childList: true, characterData: true, subtree: true, attributes: true });
      });
    }

    syncDynamicUxI18n(topbar);
    syncTopbarHubReadouts();
    window.__polarSidebarControl?.syncUi();
    window.__syncUxI18n = () => {
      syncDynamicUxI18n(document);
      syncTopbarHubReadouts();
      window.__polarSidebarControl?.syncUi();
    };
  }

  function runActivePageEnhancementTick() {
    if (document.hidden) return;
    syncTopbarHubReadouts();
    ensureOverviewLiveEnhancements();
    enhanceHorizontalTabsScroll();
    enhanceGenericTableCsvExports();
    enhanceCurveCanvases();
    const metrics = extractLiveOverviewMetrics();
    updateOverviewLiveStripAndMeters(metrics);
    updateDiagramLiveEnhancements(metrics);
  }

  /**
   * 顶栏注入轻量 Ctrl+K 快捷入口按钮、全局快捷键与导航进度条监听
   */
  function initGlobalShortcutsAndChrome() {
    installFetchLatencyProbe();
    initSharedSidebarToggle();
    enhanceTopbarThemeQuickControls();
    ensurePerfPillAndAlertPopover();
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
    initCompactTopbarHubs();
    enhanceAllHorizontalSplitters();
    enhanceHorizontalTabsScroll();
    enhanceTableFilterClearButtons();
    enhanceGenericTableCsvExports();
    enhanceCurveCanvases();
    enhanceDiagramSelectionActions();
    ensureOverviewLiveEnhancements();
    enhanceDiagramHudAndMinimap();

    const pageMain = document.querySelector(".page-main");
    if (pageMain && typeof MutationObserver === "function") {
      let splitSyncRaf = 0;
      const splitObserver = new MutationObserver(() => {
        if (splitSyncRaf) return;
        splitSyncRaf = requestAnimationFrame(() => {
          splitSyncRaf = 0;
          enhanceAllHorizontalSplitters();
          enhanceHorizontalTabsScroll();
          enhanceTableFilterClearButtons();
          enhanceGenericTableCsvExports();
          enhanceCurveCanvases();
          enhanceDiagramSelectionActions();
          runActivePageEnhancementTick();
        });
      });
      splitObserver.observe(pageMain, { childList: true });
    }

    document.querySelectorAll(".page-nav button[data-nav-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        flashTopProgress();
        setTimeout(runActivePageEnhancementTick, 80);
      });
    });
    const modelSel = document.getElementById("modelSelector");
    modelSel?.addEventListener("change", () => {
      flashTopProgress();
      overviewSparkHistory.length = 0;
      lastOverviewSig = "";
      lastDiagramHeatSig = "";
      const canvasHost = document.getElementById("modelDiagramCanvas");
      if (canvasHost) delete canvasHost.dataset.uxAutoSelectedOnce;
    });

    if (!liveEnhanceTimerId) {
      liveEnhanceTimerId = setInterval(runActivePageEnhancementTick, 1200);
      runActivePageEnhancementTick();
    }

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
