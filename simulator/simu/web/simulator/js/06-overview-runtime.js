// 教员端前端模块：总览能流布局、分栏缩放、运行日志与设备控制。

function overviewClamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function overviewLoadFlowColor(greenPowerShare) {
  const percent = overviewClamp(Number(greenPowerShare), 0, 100);
  if (!Number.isFinite(percent)) return "#4978c4";
  const hue = 2 + percent * 1.18;
  return `hsl(${hue.toFixed(1)}, 62%, 42%)`;
}

function overviewFlowStyle(powerValue, maxPower) {
  const power = overviewFlowPowerValue(powerValue);
  const base = Math.max(1, overviewFlowPowerValue(maxPower));
  const active = power > 1e-6;
  const ratio = active ? overviewClamp(Math.sqrt(power / base), 0, 1) : 0;
  const thickness = active ? 2 + ratio * 6 : 2;
  const headSize = active ? 8 + ratio * 9 : 8;
  const headHalf = active ? 5 + ratio * 5 : 5;
  const opacity = active ? 0.58 + ratio * 0.34 : 0.24;
  const duration = active ? 1.4 - ratio * 0.42 : 1.4;
  return {
    active,
    thickness: `${thickness.toFixed(2)}px`,
    headSize: `${headSize.toFixed(2)}px`,
    headHalf: `${headHalf.toFixed(2)}px`,
    opacity: opacity.toFixed(2),
    duration: `${duration.toFixed(2)}s`,
  };
}

function setOverviewFlowVisualElement(element, powerValue, maxPower, color) {
  if (!element) return;
  const visual = overviewFlowStyle(powerValue, maxPower);
  element.dataset.flowActive = visual.active ? "true" : "false";
  element.style.setProperty("--flow-color", color);
  element.style.setProperty("--flow-thickness", visual.thickness);
  element.style.setProperty("--flow-head-size", visual.headSize);
  element.style.setProperty("--flow-head-half", visual.headHalf);
  element.style.setProperty("--flow-opacity", visual.opacity);
  element.style.setProperty("--flow-duration", visual.duration);
}

function setOverviewFlowVisual(id, powerValue, maxPower, color) {
  setOverviewFlowVisualElement($(id), powerValue, maxPower, color);
}

function overviewFlowGroupMeta(group) {
  const status = OVERVIEW_FLOW_STATUS_LABELS[group.status] || "待量测";
  const count = `${group.onlineCount}/${group.totalCount} 台`;
  if (["fuelCell", "electrolyzer", "hydrogenStorage"].includes(group.category)) {
    return `${status} · 数量 ${count}`;
  }
  if (group.category !== "storage") return `${status} · ${count}`;
  const soc = Number.isFinite(group.soc) ? `${formatOverviewNumber(group.soc)}%` : "--";
  return `${status} · SOC ${soc} · ${count}`;
}

function overviewHydrogenActiveTarget(group) {
  const mode = String(group.controlMode || "").trim().toUpperCase();
  if (mode === "FLOW") {
    return {
      label: group.category === "fuelCell" ? "耗气目标" : "产气目标",
      value: overviewGasFlowText(group.targetGasFlow),
    };
  }
  if (["P", "PQ"].includes(mode)) {
    return {
      label: group.category === "fuelCell" ? "发电目标" : "耗电目标",
      value: overviewPowerText(group.targetPower),
    };
  }
  return { label: "有效目标", value: "--" };
}

function renderOverviewFlowGroups(power) {
  const groups = power.flowGroups || {};
  const visibleGroups = OVERVIEW_FLOW_GROUP_DEFINITIONS
    .map((definition) => groups[definition.key])
    .filter((group) => group?.present);
  const maxPower = Math.max(1, ...visibleGroups.map((group) => overviewFlowPowerValue(group.power)));
  const { greenPowerShare } = overviewGreenMetrics(power);

  OVERVIEW_FLOW_GROUP_DEFINITIONS.forEach((definition) => {
    const group = groups[definition.key] || { present: false };
    const node = document.querySelector(`[data-overview-group="${definition.key}"]`);
    const wrapper = document.querySelector(`[data-overview-group-wrapper="${definition.key}"]`);
    if (!node) return;
    node.hidden = !group.present;
    if (wrapper) wrapper.hidden = !group.present;
    if (!group.present) return;
    node.dataset.flowDirection = group.flowDirection;
    node.dataset.operatingState = group.status;
    const powerNode = node.querySelector("[data-overview-power]");
    const targetNode = node.querySelector("[data-overview-target]");
    const maxAvailableNode = node.querySelector("[data-overview-max-available]");
    const gasFlowNode = node.querySelector("[data-overview-gas-flow]");
    const targetGasFlowNode = node.querySelector("[data-overview-target-gas-flow]");
    const gasPressureNode = node.querySelector("[data-overview-gas-pressure]");
    const socNode = node.querySelector("[data-overview-soc]");
    const metaNode = node.querySelector("[data-overview-meta]");
    const countNode = node.querySelector("[data-overview-count]");
    const activeTargetLabelNode = node.querySelector("[data-overview-active-target-label]");
    const activeTargetNode = node.querySelector("[data-overview-active-target]");
    if (powerNode) powerNode.textContent = overviewPowerText(group.power);
    if (targetNode) targetNode.textContent = overviewPowerText(group.targetPower);
    if (maxAvailableNode) maxAvailableNode.textContent = overviewPowerText(group.maxAvailablePower);
    if (gasFlowNode) gasFlowNode.textContent = overviewGasFlowText(group.gasFlow);
    if (targetGasFlowNode) targetGasFlowNode.textContent = overviewGasFlowText(group.targetGasFlow);
    if (gasPressureNode) gasPressureNode.textContent = overviewGasPressureText(group.gasPressure);
    if (socNode) socNode.textContent = overviewPercentText(group.soc);
    if (metaNode) metaNode.textContent = overviewFlowGroupMeta(group);
    if (countNode) countNode.textContent = `${group.onlineCount}/${group.totalCount} 台`;
    const activeTarget = ["fuelCell", "electrolyzer"].includes(definition.key)
      ? overviewHydrogenActiveTarget(group)
      : null;
    if (activeTargetLabelNode) activeTargetLabelNode.textContent = activeTarget?.label || "有效目标";
    if (activeTargetNode) activeTargetNode.textContent = activeTarget?.value || "--";
    const tooltipParts = [
      node.querySelector("span")?.textContent || "设备",
      `当前 ${overviewPowerText(group.power)}`,
    ];
    if (activeTarget) tooltipParts.push(`${activeTarget.label} ${activeTarget.value}`);
    else tooltipParts.push(`目标 ${overviewPowerText(group.targetPower)}`);
    if (["dcWind", "dcSolar", "acWind", "acSolar"].includes(definition.key)) {
      tooltipParts.push(`最大可发 ${overviewPowerText(group.maxAvailablePower)}`);
    }
    if (["fuelCell", "electrolyzer"].includes(definition.key)) {
      tooltipParts.push(`气流实时 ${overviewGasFlowText(group.gasFlow)}`);
    }
    if (definition.key === "hydrogenStorage") {
      tooltipParts.push(`气流量 ${overviewGasFlowText(group.gasFlow)}`);
      tooltipParts.push(`储气压力 ${overviewGasPressureText(group.gasPressure)}`);
      tooltipParts.push(`SOC ${overviewPercentText(group.soc)}`);
    }
    tooltipParts.push(overviewFlowGroupMeta(group));
    node.title = tooltipParts.join(" · ");
    const flowPower = group.flowDirection === "idle" ? 0 : group.power;
    const color = definition.category === "load" ? overviewLoadFlowColor(greenPowerShare) : definition.color;
    setOverviewFlowVisualElement(node, flowPower, maxPower, color);
    if (wrapper) {
      wrapper.dataset.storageFlow = group.status === "discharge" ? "discharge" : group.status === "charge" ? "charge" : "idle";
      wrapper.dataset.operatingState = group.status;
      setOverviewFlowVisualElement(wrapper, flowPower, maxPower, color);
    }
  });

  document.querySelectorAll("[data-overview-region]").forEach((region) => {
    if (region.id === "overviewGridFormingStack") return;
    const regionKey = region.dataset.overviewRegion;
    region.hidden = !visibleGroups.some((group) => group.region === regionKey);
  });
  const formingStack = $("overviewGridFormingStack");
  if (formingStack) formingStack.hidden = !visibleGroups.some((group) => group.region === "forming");

  const hydrogenLinkState = (name, group, value, maxValue, direction, color, present) => {
    const link = document.querySelector(`[data-hydrogen-link="${name}"]`);
    if (!link) return;
    link.hidden = !present;
    link.dataset.flowDirection = direction;
    setOverviewFlowVisualElement(link, value, maxValue, color);
  };
  const fuelCellGroup = groups.fuelCell;
  const hydrogenStorageGroup = groups.hydrogenStorage;
  const electrolyzerGroup = groups.electrolyzer;
  const maxHydrogenPower = Math.max(
    1,
    overviewFlowPowerValue(fuelCellGroup?.power),
    overviewFlowPowerValue(electrolyzerGroup?.power),
  );
  const maxHydrogenFlow = Math.max(
    1,
    overviewFlowPowerValue(fuelCellGroup?.gasFlow),
    overviewFlowPowerValue(electrolyzerGroup?.gasFlow),
    overviewFlowPowerValue(hydrogenStorageGroup?.gasFlow),
  );
  hydrogenLinkState(
    "fuel-cell-electric",
    fuelCellGroup,
    fuelCellGroup?.power,
    maxHydrogenPower,
    Number(fuelCellGroup?.power) >= 0 ? "left" : "right",
    "#16856a",
    Boolean(fuelCellGroup?.present),
  );
  hydrogenLinkState(
    "fuel-cell-gas",
    fuelCellGroup,
    fuelCellGroup?.gasFlow,
    maxHydrogenFlow,
    Number(fuelCellGroup?.gasFlow) >= 0 ? "left" : "right",
    "#287ea0",
    Boolean(fuelCellGroup?.present && hydrogenStorageGroup?.present),
  );
  hydrogenLinkState(
    "electrolyzer-gas",
    electrolyzerGroup,
    electrolyzerGroup?.gasFlow,
    maxHydrogenFlow,
    Number(electrolyzerGroup?.gasFlow) >= 0 ? "left" : "right",
    "#287ea0",
    Boolean(electrolyzerGroup?.present && hydrogenStorageGroup?.present),
  );
  hydrogenLinkState(
    "electrolyzer-electric",
    electrolyzerGroup,
    electrolyzerGroup?.power,
    maxHydrogenPower,
    Number(electrolyzerGroup?.power) >= 0 ? "left" : "right",
    "#b56a22",
    Boolean(electrolyzerGroup?.present),
  );

  const converterGroup = groups.acdcConverter;
  const aggregateTrunkPower = visibleGroups
    .filter((group) => !["load", "converter", "electrolyzer", "hydrogenStorage"].includes(group.category))
    .reduce((total, group) => total + overviewFlowPowerValue(group.power), 0);
  const trunkPower = converterGroup?.present && Number.isFinite(converterGroup.power)
    ? converterGroup.power
    : aggregateTrunkPower;
  const trunk = $("overviewEnergyMainTrunk");
  if (trunk) trunk.dataset.flowDirection = converterGroup?.flowDirection || "toAc";
  setOverviewFlowVisual("overviewEnergyMainTrunk", trunkPower, maxPower, "#2f9e62");
}

function renderEnergyFlowVisuals(power) {
  renderOverviewFlowGroups(power);
}

function setOverviewText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function overviewBottomHeightBounds() {
  const dashboard = document.querySelector(".overview-dashboard");
  const dashboardHeight = dashboard?.getBoundingClientRect().height || 0;
  const dashboardStyle = dashboard ? getComputedStyle(dashboard) : null;
  const mainGrid = document.querySelector(".overview-main-grid");
  const statusHeight = document.querySelector(".overview-status-panel")?.getBoundingClientRect().height || 68;
  const splitterHeight = $("overviewBottomSplitter")?.getBoundingClientRect().height || 10;
  const mainMinHeight = Number.parseFloat(mainGrid ? getComputedStyle(mainGrid).minHeight : "") || 180;
  const rowGap = Number.parseFloat(dashboardStyle?.rowGap || dashboardStyle?.gap || "") || 12;
  const reservedHeight = statusHeight + mainMinHeight + splitterHeight + rowGap * 3;
  const dynamicMax = dashboardHeight > 0 ? dashboardHeight - reservedHeight : OVERVIEW_BOTTOM_MAX_HEIGHT;
  const maxHeight = Math.max(
    OVERVIEW_BOTTOM_MIN_HEIGHT,
    Math.min(OVERVIEW_BOTTOM_MAX_HEIGHT, dynamicMax),
  );
  return { min: OVERVIEW_BOTTOM_MIN_HEIGHT, max: maxHeight };
}

function applyOverviewBottomHeight(value, persist = false) {
  const bounds = overviewBottomHeightBounds();
  const numericValue = Number(value);
  const nextHeight = Math.round(clamp(
    Number.isFinite(numericValue) ? numericValue : OVERVIEW_BOTTOM_DEFAULT_HEIGHT,
    bounds.min,
    bounds.max,
  ));
  state.overviewBottomHeight = nextHeight;
  const dashboard = document.querySelector(".overview-dashboard");
  if (dashboard) dashboard.style.setProperty("--overview-bottom-height", `${nextHeight}px`);
  const splitter = $("overviewBottomSplitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    splitter.setAttribute("aria-valuenow", String(nextHeight));
    splitter.setAttribute("aria-valuetext", `${nextHeight}px`);
  }
  if (persist) localStorage.setItem(OVERVIEW_BOTTOM_HEIGHT_KEY, String(nextHeight));
}

function beginOverviewBottomSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = $("overviewBottomSplitter");
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (!splitter || !bottomGrid) return;
  event.preventDefault();
  const currentHeight = bottomGrid.getBoundingClientRect().height || state.overviewBottomHeight;
  state.overviewBottomSplitDrag = {
    pointerId: event.pointerId,
    startY: event.clientY,
    startHeight: currentHeight,
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-overview-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or cancelled pointer events do not always have capturable pointers.
    }
  }
}

function handleOverviewBottomSplitterDrag(event) {
  const drag = state.overviewBottomSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  applyOverviewBottomHeight(drag.startHeight - (event.clientY - drag.startY));
}

function finishOverviewBottomSplitterDrag(event) {
  const drag = state.overviewBottomSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = $("overviewBottomSplitter");
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be gone if the pointer left the window.
      }
    }
  }
  document.body.classList.remove("is-overview-splitter-dragging");
  state.overviewBottomSplitDrag = null;
  applyOverviewBottomHeight(state.overviewBottomHeight, true);
}

function handleOverviewBottomSplitterKeydown(event) {
  let nextHeight = null;
  if (event.key === "ArrowUp") nextHeight = state.overviewBottomHeight + 16;
  if (event.key === "ArrowDown") nextHeight = state.overviewBottomHeight - 16;
  if (event.key === "PageUp") nextHeight = state.overviewBottomHeight + 48;
  if (event.key === "PageDown") nextHeight = state.overviewBottomHeight - 48;
  if (event.key === "Home") nextHeight = OVERVIEW_BOTTOM_MIN_HEIGHT;
  if (event.key === "End") nextHeight = overviewBottomHeightBounds().max;
  if (nextHeight === null) return;
  event.preventDefault();
  applyOverviewBottomHeight(nextHeight, true);
}

function initOverviewBottomSplitter() {
  const splitter = $("overviewBottomSplitter");
  if (!splitter) return;
  if (splitter.dataset.splitterReady === "true") return;
  splitter.dataset.splitterReady = "true";
  applyOverviewBottomHeight(state.overviewBottomHeight);
  splitter.addEventListener("pointerdown", beginOverviewBottomSplitterDrag);
  splitter.addEventListener("keydown", handleOverviewBottomSplitterKeydown);
  window.addEventListener("pointermove", handleOverviewBottomSplitterDrag);
  window.addEventListener("pointerup", finishOverviewBottomSplitterDrag);
  window.addEventListener("pointercancel", finishOverviewBottomSplitterDrag);
  window.addEventListener("resize", () => applyOverviewBottomHeight(state.overviewBottomHeight, true));
}

function overviewBottomColumnRatioBounds() {
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  const splitter = $("overviewBottomColumnSplitter");
  const gridWidth = bottomGrid?.getBoundingClientRect().width || 0;
  const splitterWidth = splitter?.getBoundingClientRect().width || 12;
  const contentWidth = Math.max(0, gridWidth - splitterWidth);
  if (contentWidth < OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX * 2) {
    return { min: 0, max: 100, contentWidth };
  }
  const minRatio = (OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX / contentWidth) * 100;
  return { min: minRatio, max: 100 - minRatio, contentWidth };
}

function applyOverviewBottomColumnRatio(ratio, persist = false) {
  const numericRatio = Number(ratio);
  const requestedRatio = Number.isFinite(numericRatio) ? numericRatio : OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO;
  const bounds = overviewBottomColumnRatioBounds();
  const nextRatio = Number(clamp(requestedRatio, bounds.min, bounds.max).toFixed(2));
  state.overviewBottomColumnRatio = nextRatio;
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (bottomGrid) {
    bottomGrid.style.setProperty("--overview-bottom-left-ratio", `${nextRatio}fr`);
    bottomGrid.style.setProperty("--overview-bottom-right-ratio", `${Number((100 - nextRatio).toFixed(2))}fr`);
  }
  const splitter = $("overviewBottomColumnSplitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", bounds.min.toFixed(2));
    splitter.setAttribute("aria-valuemax", bounds.max.toFixed(2));
    splitter.setAttribute("aria-valuenow", String(nextRatio));
    splitter.setAttribute("aria-valuetext", `左侧 ${nextRatio.toFixed(2)}%，右侧 ${(100 - nextRatio).toFixed(2)}%`);
  }
  if (persist) localStorage.setItem(OVERVIEW_BOTTOM_COLUMN_RATIO_KEY, String(nextRatio));
}

function beginOverviewBottomColumnSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = $("overviewBottomColumnSplitter");
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (!splitter || !bottomGrid) return;
  const bounds = overviewBottomColumnRatioBounds();
  if (bounds.contentWidth <= 0) return;
  event.preventDefault();
  state.overviewBottomColumnSplitDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startRatio: state.overviewBottomColumnRatio,
    contentWidth: bounds.contentWidth,
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-overview-column-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or cancelled pointer events do not always have capturable pointers.
    }
  }
}

function handleOverviewBottomColumnSplitterDrag(event) {
  const drag = state.overviewBottomColumnSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  const deltaRatio = ((event.clientX - drag.startX) / drag.contentWidth) * 100;
  applyOverviewBottomColumnRatio(drag.startRatio + deltaRatio);
}

function finishOverviewBottomColumnSplitterDrag(event) {
  const drag = state.overviewBottomColumnSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = $("overviewBottomColumnSplitter");
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be gone if the pointer left the window.
      }
    }
  }
  document.body.classList.remove("is-overview-column-splitter-dragging");
  state.overviewBottomColumnSplitDrag = null;
  applyOverviewBottomColumnRatio(state.overviewBottomColumnRatio, true);
}

function handleOverviewBottomColumnSplitterKeydown(event) {
  const bounds = overviewBottomColumnRatioBounds();
  let nextRatio = null;
  if (event.key === "ArrowLeft") nextRatio = state.overviewBottomColumnRatio - 2;
  if (event.key === "ArrowRight") nextRatio = state.overviewBottomColumnRatio + 2;
  if (event.key === "PageUp") nextRatio = state.overviewBottomColumnRatio - 8;
  if (event.key === "PageDown") nextRatio = state.overviewBottomColumnRatio + 8;
  if (event.key === "Home") nextRatio = bounds.min;
  if (event.key === "End") nextRatio = bounds.max;
  if (nextRatio === null) return;
  event.preventDefault();
  applyOverviewBottomColumnRatio(nextRatio, true);
}

function initOverviewBottomColumnSplitter() {
  const splitter = $("overviewBottomColumnSplitter");
  if (!splitter) return;
  if (splitter.dataset.splitterReady === "true") return;
  splitter.dataset.splitterReady = "true";
  applyOverviewBottomColumnRatio(state.overviewBottomColumnRatio);
  splitter.addEventListener("pointerdown", beginOverviewBottomColumnSplitterDrag);
  splitter.addEventListener("keydown", handleOverviewBottomColumnSplitterKeydown);
  window.addEventListener("pointermove", handleOverviewBottomColumnSplitterDrag);
  window.addEventListener("pointerup", finishOverviewBottomColumnSplitterDrag);
  window.addEventListener("pointercancel", finishOverviewBottomColumnSplitterDrag);
  window.addEventListener("resize", () => applyOverviewBottomColumnRatio(overviewInitialBottomColumnRatio()));
}

function verticalSplitDefaultRatio(splitId) {
  return VERTICAL_SPLIT_DEFAULTS[splitId] || VERTICAL_SPLIT_DEFAULT_RATIO;
}

function verticalSplitContainer(splitId) {
  return Array.from(document.querySelectorAll("[data-vertical-split]"))
    .find((container) => container.dataset.verticalSplit === splitId) || null;
}

function verticalSplitBounds(container) {
  if (!container) return { min: 20, max: 80 };
  const rect = container.getBoundingClientRect();
  const splitter = container.querySelector("[data-vertical-splitter]");
  const splitterHeight = splitter?.getBoundingClientRect().height || 10;
  const availableHeight = rect.height > 0 ? rect.height - splitterHeight : 0;
  if (availableHeight <= 0) return { min: 20, max: 80 };
  const minTop = Number(container.dataset.verticalSplitMinTop) || VERTICAL_SPLIT_MIN_TOP_PX;
  const minBottom = Number(container.dataset.verticalSplitMinBottom) || VERTICAL_SPLIT_MIN_BOTTOM_PX;
  const minRatio = clamp((minTop / availableHeight) * 100, 8, 88);
  const maxRatio = clamp(100 - (minBottom / availableHeight) * 100, 12, 92);
  if (minRatio <= maxRatio) return { min: minRatio, max: maxRatio };
  const centerRatio = clamp(50, 8, 92);
  return { min: centerRatio, max: centerRatio };
}

function applyVerticalSplit(splitId, ratio, persist = false, redraw = false) {
  const container = verticalSplitContainer(splitId);
  if (!container) return;
  const bounds = verticalSplitBounds(container);
  const numericRatio = Number(ratio);
  const nextRatio = Math.round(clamp(
    Number.isFinite(numericRatio) ? numericRatio : verticalSplitDefaultRatio(splitId),
    bounds.min,
    bounds.max,
  ) * 10) / 10;
  state.verticalSplitRatios[splitId] = nextRatio;
  container.style.setProperty("--vertical-split-top", `${nextRatio}%`);
  const splitter = container.querySelector(`[data-vertical-splitter="${splitId}"]`);
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    splitter.setAttribute("aria-valuenow", String(nextRatio));
    splitter.setAttribute("aria-valuetext", `${nextRatio}%`);
  }
  if (persist) localStorage.setItem(VERTICAL_SPLIT_STORAGE_KEY, JSON.stringify(state.verticalSplitRatios));
  if (redraw) redrawVerticalSplitContent(splitId);
}

function redrawVerticalSplitContent(splitId) {
  requestAnimationFrame(() => {
    if (splitId === "simulator-curves") drawCurves();
    if (splitId === "simulator-runtime") drawRuntimeTraceChart();
    if (splitId === "simulator-measurements") drawMeasurementTraceChart();
  });
}

function beginVerticalSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = event.currentTarget;
  const splitId = splitter?.dataset.verticalSplitter || "";
  const container = verticalSplitContainer(splitId);
  if (!splitter || !container) return;
  event.preventDefault();
  const containerRect = container.getBoundingClientRect();
  const splitterRect = splitter.getBoundingClientRect();
  state.verticalSplitDrag = {
    splitId,
    pointerId: event.pointerId,
    startY: event.clientY,
    startTopPx: splitterRect.top - containerRect.top,
    availableHeight: Math.max(1, containerRect.height - splitterRect.height),
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-vertical-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Pointer capture can fail for synthetic events during tests.
    }
  }
}

function handleVerticalSplitterDrag(event) {
  const drag = state.verticalSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  const nextTopPx = drag.startTopPx + (event.clientY - drag.startY);
  applyVerticalSplit(drag.splitId, (nextTopPx / drag.availableHeight) * 100, false, true);
}

function finishVerticalSplitterDrag(event) {
  const drag = state.verticalSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = document.querySelector(`[data-vertical-splitter="${drag.splitId}"]`);
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be released.
      }
    }
  }
  document.body.classList.remove("is-vertical-splitter-dragging");
  state.verticalSplitDrag = null;
  applyVerticalSplit(drag.splitId, state.verticalSplitRatios[drag.splitId], true, true);
}

function handleVerticalSplitterKeydown(event) {
  const splitId = event.currentTarget?.dataset.verticalSplitter || "";
  const currentRatio = state.verticalSplitRatios[splitId] || verticalSplitDefaultRatio(splitId);
  const bounds = verticalSplitBounds(verticalSplitContainer(splitId));
  let nextRatio = null;
  if (event.key === "ArrowUp") nextRatio = currentRatio - 2;
  if (event.key === "ArrowDown") nextRatio = currentRatio + 2;
  if (event.key === "PageUp") nextRatio = currentRatio - 8;
  if (event.key === "PageDown") nextRatio = currentRatio + 8;
  if (event.key === "Home") nextRatio = bounds.min;
  if (event.key === "End") nextRatio = bounds.max;
  if (nextRatio === null) return;
  event.preventDefault();
  applyVerticalSplit(splitId, nextRatio, true, true);
}

function initVerticalSplitters() {
  document.querySelectorAll("[data-vertical-splitter]").forEach((splitter) => {
    const splitId = splitter.dataset.verticalSplitter || "";
    if (!splitId) return;
    applyVerticalSplit(splitId, state.verticalSplitRatios[splitId] || verticalSplitDefaultRatio(splitId));
    if (splitter.dataset.verticalSplitterReady === "true") return;
    splitter.dataset.verticalSplitterReady = "true";
    splitter.addEventListener("pointerdown", beginVerticalSplitterDrag);
    splitter.addEventListener("keydown", handleVerticalSplitterKeydown);
    splitter.addEventListener("dblclick", () => {
      applyVerticalSplit(splitId, verticalSplitDefaultRatio(splitId), true, true);
    });
  });
  if (document.body.dataset.verticalSplitterResizeReady === "true") return;
  document.body.dataset.verticalSplitterResizeReady = "true";
  window.addEventListener("pointermove", handleVerticalSplitterDrag);
  window.addEventListener("pointerup", finishVerticalSplitterDrag);
  window.addEventListener("pointercancel", finishVerticalSplitterDrag);
  window.addEventListener("resize", () => {
    document.querySelectorAll("[data-vertical-split]").forEach((container) => {
      const splitId = container.dataset.verticalSplit || "";
      applyVerticalSplit(splitId, state.verticalSplitRatios[splitId], true, true);
    });
  });
}

function renderOverviewEvents(snapshot) {
  const container = $("commandInbox");
  if (!container) return;
  const logs = (state.runtimeLogs.length ? state.runtimeLogs : [...(snapshot.runtime_logs || [])].reverse()).slice(0, 8);
  const renderKey = logs.length
    ? logs.map((item) => `${item.seq ?? ""}:${item.simu_time || item.sim_time || ""}:${item.type || ""}:${item.result || ""}`).join("|")
    : "__empty__";
  if (container.dataset.eventsKey === renderKey) return;
  container.dataset.eventsKey = renderKey;
  if (logs.length) {
    container.innerHTML = logs.map((item) => `
      <div class="overview-event-item is-clickable-row" data-overview-event-jump="logs" title="点击查看运行日志">
        <time>${escapeHtml(item.simu_time || item.sim_time || "--")}</time>
        <strong>${escapeHtml(item.type || "运行")}</strong>
        <span title="${escapeHtml(logDetailText(item))}">${escapeHtml(item.result || logDetailText(item) || "完成")}</span>
      </div>
    `).join("");
    return;
  }
  container.innerHTML = '<div class="overview-event-item"><time>--</time><strong>系统</strong><span>等待启动仿真</span></div>';
}

function activeRuntimeCommandKeySet(snapshot = state.snapshot || {}) {
  const keys = new Set();
  displayedCommandHistory(snapshot).forEach((entry) => {
    const normalized = entry.normalized || {};
    const payload = entry.payload || {};
    const runItems = normalized.run_status || payload.run_status || payload.runStatus || [];
    const setItems = normalized.set_values || payload.set_values || payload.setValues || payload.setpoints || [];
    if (Array.isArray(runItems)) {
      runItems.forEach((item) => {
        if (!item?.dev_type || !item?.dev_name) return;
        if (item.run_stat !== undefined && item.run_stat !== "") {
          keys.add(["remote_control", item.dev_type, item.dev_name, "run_stat"].join("|"));
        }
        if (Object.prototype.hasOwnProperty.call(item, "status")) {
          keys.add(["remote_control", item.dev_type, item.dev_name, "status"].join("|"));
        }
      });
    }
    if (Array.isArray(setItems)) {
      setItems.forEach((item) => {
        if (!item?.dev_type || !item?.dev_name || !item?.set_type) return;
        keys.add(["remote_adjustment", item.dev_type, item.dev_name, item.set_type].join("|"));
      });
    }
  });
  return keys;
}

function overviewActiveRuntimeCommandRows(snapshot = state.snapshot || {}) {
  const activeKeys = activeRuntimeCommandKeySet(snapshot);
  if (!activeKeys.size) return [];
  const measurements = snapshot.measurements || {};
  const context = runtimeCommandBuildContext(snapshot, measurements);
  return runtimeCommandRowsForDevices(controlDefinitionDevices(snapshot), measurements, context)
    .filter((row) => {
      return activeKeys.has(runtimeCommandTraceKey(row)) && commandTimeInfoAvailable(row.receive_time);
    });
}

function renderOverviewActiveCommands(snapshot) {
  const container = $("overviewActiveCommandTable");
  const summary = $("overviewActiveCommandSummary");
  if (!container) return [];
  const rows = overviewActiveRuntimeCommandRows(snapshot);
  if (summary) summary.textContent = `${rows.length} 条有效/排队指令`;
  const renderKey = rows.length
    ? rows.map((row) => [
      runtimeCommandTraceKey(row),
      row.receive_time?.wall_time || "",
      row.receive_time?.simu_time || "",
      runtimeCommandTableValueText(row, "control"),
      runtimeCommandTableValueText(row, "real"),
      runtimeCommandTableValueText(row, "scada"),
      row.process_status || "",
    ].join(":")).join("|")
    : "__empty__";
  if (container.dataset.activeCmdKey === renderKey) return rows;
  container.dataset.activeCmdKey = renderKey;
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前无有效或排队的遥控/遥调指令</div>';
    return rows;
  }
  container.innerHTML = `
    <table class="overview-command-table">
      <thead>
        <tr>
          <th>本机时刻</th>
          <th>设备</th>
          <th>指令项</th>
          <th class="numeric-cell">控制指令</th>
          <th>仿真时刻</th>
          <th>处理状态</th>
          <th class="numeric-cell">实时值</th>
          <th class="numeric-cell">量测值</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr
            class="is-clickable-row"
            data-overview-cmd-device="${escapeHtml(row.device?.dev_name || "")}"
            data-overview-cmd-tab="${escapeHtml(row.command_kind || "remote_control")}"
            title="${escapeHtml(runtimeCommandTraceLabel(row))}"
          >
            <td class="mono-cell">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
            <td>${escapeHtml(row.device?.dev_name || "--")}</td>
            <td>${escapeHtml(row.command || "--")} <small class="command-set-type">${escapeHtml(row.set_type || "")}</small></td>
            <td class="numeric-cell">${escapeHtml(runtimeCommandTableValueText(row, "control"))}</td>
            <td class="mono-cell">${escapeHtml(row.receive_time?.simu_time || "--")}</td>
            <td>${runtimeCommandLiveCellHtml(row, "process")}</td>
            <td class="numeric-cell">${escapeHtml(runtimeCommandTableValueText(row, "real"))}</td>
            <td class="numeric-cell">${escapeHtml(runtimeCommandTableValueText(row, "scada"))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  return rows;
}

function renderOverviewDashboard(snapshot) {
  const clock = snapshot.clock || {};
  const stateLabels = { running: "运行中", paused: "已暂停", stopped: "已停止" };
  const boundary = overviewCurveBoundary(snapshot);
  const power = parsePowerFlowOverview(snapshot);
  const devices = snapshot.devices || [];
  const onlineDevices = devices.filter((device) => Number(device.run_stat ?? 1) !== 0).length;
  const totalMeasurements = Number(snapshot.summary?.scada_count || 0);
  const validMeasurements = Number(snapshot.summary?.valid_scada_count || 0);
  const result = snapshot.result || {};
  const activeOverviewCommands = renderOverviewActiveCommands(snapshot);
  const stateDot = $("overviewStateDot");
  setOverviewText("overviewState", stateLabels[clock.state] || clock.state || "未知");
  if (stateDot) {
    stateDot.classList.toggle("is-running", clock.state === "running");
    stateDot.classList.toggle("is-paused", clock.state === "paused");
  }
  setOverviewText("overviewModel", snapshot.model?.name || snapshot.model?.id || "--");
  renderOverviewServiceLink(snapshot);
  const overviewMode = snapshot.curve_boundary?.mode || snapshot.curves?.mode || state.curveMode;
  setOverviewText("overviewMode", simulationModeLabel(overviewMode));
  const effectiveStepSeconds = Number(
    clock.effective_step_seconds
      ?? snapshot.system_parameters?.effective_step_seconds
      ?? ((clock.step_seconds ?? 1) * (clock.speed ?? 1)),
  );
  setOverviewText("overviewStep", formatClockDuration(effectiveStepSeconds));
  setOverviewText("metricScada", validMeasurements);
  setOverviewText("overviewMeasurementTotal", totalMeasurements);
  setOverviewText("metricCommands", snapshot.summary?.command_count || 0);
  setOverviewText("metricAlarms", snapshot.summary?.alarm_count || 0);
  setOverviewText("overviewBoundaryTime", formatSimulationClock(clock));
  setOverviewText("overviewWindSpeed", hasOverviewNumber(boundary.point.wind_speed_mps) ? `${formatOverviewNumber(boundary.point.wind_speed_mps)} m/s` : "--");
  setOverviewText("overviewIrradiance", hasOverviewNumber(boundary.point.solar_irradiance_w_m2) ? `${formatOverviewNumber(boundary.point.solar_irradiance_w_m2)} W/m²` : "--");
  setOverviewText("overviewTemperature", hasOverviewNumber(boundary.point.air_temp_c) ? `${formatOverviewNumber(boundary.point.air_temp_c)} ℃` : "--");
  setOverviewText("overviewLoadBoundary", overviewPowerText(boundary.loadTotal));
  setOverviewText("overviewOnlineDevices", `${onlineDevices}/${devices.length} 台`);
  setOverviewText("overviewActiveCommands", `${activeOverviewCommands.length} 条`);
  const { greenPower, greenPowerShare } = overviewGreenMetrics(power);
  setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderOverviewFlowGroups(power);
  setOverviewText("overviewCommandCount", `${activeOverviewCommands.length} 条控制指令`);
  renderOverviewEvents(snapshot);
}

function renderActiveSimulatorPage(snapshot = state.snapshot, force = false) {
  const activePage = currentPageName();
  if (activePage !== "diagram") {
    hideDiagramTooltip(state.pageSections?.diagram?.querySelector?.("#modelDiagramCanvas") || null);
  }
  if (activePage === "overview") {
    if (snapshot) renderOverviewDashboard(snapshot);
    initOverviewBottomSplitter();
    initOverviewBottomColumnSplitter();
    return;
  }
  if (activePage === "model") {
    syncModelSubtabDom();
    if (state.activeModelSubtab === "manual-changes") {
      renderManualDefinitionChanges();
      const activeDefinitionRevision = Number(snapshot?.static_meta?.definitions?.revision) || 0;
      if (
        (
          state.manualDefinitionChangesLoadedModelId !== state.activeModelId
          || (activeDefinitionRevision && activeDefinitionRevision !== state.manualDefinitionChangesRevision)
        )
        && !state.manualDefinitionChangesLoading
        && !state.manualDefinitionChangesResetting
        && !state.manualDefinitionChangesRetrying
      ) {
        loadManualDefinitionChanges();
      }
      return;
    }
    if (state.activeModelSubtab === "faults") {
      syncFaultSubtabDom();
      if (typeof renderActiveFaultSubtab === "function") renderActiveFaultSubtab(force);
      return;
    }
    renderGridModelPage();
    return;
  }
  if (activePage === "diagram") {
    renderModelDiagramPage(snapshot);
    return;
  }
  if (activePage === "curves") {
    resizeCurveCanvas();
    renderCurveEditor(force);
    return;
  }
  if (activePage === "faults") {
    renderFaults(force);
    return;
  }
  if (activePage === "modes") {
    renderModes(force);
    return;
  }
  if (activePage === "parameters") {
    renderSystemParameters(snapshot);
    renderWebRuntimeSettings();
    if (state.webRuntimeLoadedModelId !== state.activeModelId && !state.webRuntimeLoading) {
      loadWebRuntimeSettings();
    }
    return;
  }
  if (activePage === "manual-changes") {
    renderManualDefinitionChanges();
    const activeDefinitionRevision = Number(snapshot?.static_meta?.definitions?.revision) || 0;
    if (
      (
        state.manualDefinitionChangesLoadedModelId !== state.activeModelId
        || (activeDefinitionRevision && activeDefinitionRevision !== state.manualDefinitionChangesRevision)
      )
      && !state.manualDefinitionChangesLoading
      && !state.manualDefinitionChangesResetting
      && !state.manualDefinitionChangesRetrying
    ) {
      loadManualDefinitionChanges();
    }
    return;
  }
  if (activePage === "runtime") {
    renderRuntimeMonitor(force);
    return;
  }
  if (activePage === "measurements") {
    renderMeasurementCompareTable();
    return;
  }
  if (activePage === "logs") {
    renderRuntimeLogs();
  }
}

function renderSnapshot(snapshot) {
  state.frontendDiagnostics.snapshotRenderCount += 1;
  // 仅在 activeModelId 尚未初始化时兜底，禁止用旧模型延迟快照反写当前选中模型。
  if (!state.activeModelId && snapshot.model?.id) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock);
  renderPowerFlowFailureAlert(snapshot);
  state.systemParameters = snapshotSystemParameters(snapshot || {});
  const runId = Number(snapshot.clock?.run_id ?? 0);
  const stepCount = Number(snapshot.clock?.step_count ?? 0);
  const traceLifecycleChanged = state.traceRunId !== null && (
    runId !== state.traceRunId
    || (state.traceStepCount !== null && stepCount < state.traceStepCount)
  );
  if (traceLifecycleChanged) {
    state.runtimeTraceHistory = [];
    resetChartPeriodOffsets("runtimeTrace");
    state.lastRuntimeTraceKey = "";
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
  }
  state.traceRunId = runId;
  state.traceStepCount = stepCount;
  if (snapshot.curves && state.curvesLoadedModelId !== state.activeModelId) {
    loadCurvesFromSnapshot(snapshot.curves, state.activeModelId);
  } else if (snapshot.curve_boundary?.mode) {
    const boundaryMode = CURVE_MODES[snapshot.curve_boundary.mode] ? snapshot.curve_boundary.mode : "day";
    const preserveCurveDraft = shouldPreserveCurveDraft();
    if (!preserveCurveDraft) {
      state.curveMode = boundaryMode;
      state.curvePersistedMode = boundaryMode;
      localStorage.setItem("polarSimulatorCurveMode", boundaryMode);
    }
    state.curveSummary = {
      ...(state.curveSummary || {}),
      mode: boundaryMode,
      time_step_minutes: Number(snapshot.curve_boundary.time_step_minutes) || curveStepMinutes(boundaryMode),
      point_count: Number(snapshot.curve_boundary.point_count) || curvePointCount(boundaryMode),
    };
    if (!curveSummaryHasCatalog(state.curveSummary)) state.curveSummaryLoadedModelId = "";
  }
  const solverInfo = $("solverInfo");
  if (solverInfo) solverInfo.textContent = snapshot.result.solver_info || "待运行";
  if (Array.isArray(snapshot.runtime_logs)) appendRuntimeLog(snapshot);
  appendRuntimeTrace(snapshot);
  appendMeasurementTrace(snapshot);
  if (!state.settingsLoaded && snapshot.settings !== undefined) {
    state.deviceFaults = [...(snapshot.settings?.device_faults || [])];
    state.measurementFaults = [...(snapshot.settings?.measurement_faults || [])];
    state.settingsLoaded = true;
    updateModelHubBadges();
  }
  const activePage = currentPageName();
  if ((activePage === "model" && state.activeModelSubtab === "faults") || activePage === "modes" || !state.modes.length) {
    state.modes = syncModesFromDevices(snapshot.devices || [], [
      ...(snapshot.settings?.modes || []),
      ...state.modes,
    ]);
  }
  renderActiveSimulatorPage(snapshot);
  if (activePage === "measurements") {
    ensureSelectedMeasurementHistory();
  }
}

function appendRuntimeLog(snapshot) {
  const backendLogs = snapshot.runtime_logs;
  if (Array.isArray(backendLogs)) {
    mergeRuntimeLogItems(backendLogs, {
      reset: true,
      latestSeq: backendLogs.reduce((maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0), 0),
    });
    return;
  }
  const clock = snapshot.clock || {};
  const result = snapshot.result || {};
  const summary = snapshot.summary || {};
  const signature = [
    clock.state,
    clock.time,
    clock.speed,
    result.solver_info,
    result.updated,
    result.missing,
    result.overlay_updates,
    summary.scada_count,
    summary.command_count,
    summary.alarm_count,
  ].join("|");
  if (signature === state.lastRuntimeLogKey) return;
  state.lastRuntimeLogKey = signature;
  state.runtimeLogSeq += 1;
  state.runtimeLogs.unshift(normalizeRuntimeLog({
    seq: state.runtimeLogSeq,
    wall_time: runtimeLogTime(),
    simu_time: clock.time || "--",
    type: "仿真状态",
    target: "潮流计算 / SCADA",
    result: clock.state || "--",
    level: result.missing ? "warn" : "info",
    detail: [
      `速度 x${clock.speed ?? "--"}`,
      `求解器 ${result.solver_info || "待运行"}`,
      `量测 ${summary.scada_count ?? 0} 条，命令 ${summary.command_count ?? 0} 条，告警 ${summary.alarm_count ?? 0} 条`,
      `更新 ${result.updated ?? 0} 条，缺失 ${result.missing ?? 0} 条，叠加修正 ${result.overlay_updates ?? 0} 条`,
    ],
  }));
  state.runtimeLogs = state.runtimeLogs.slice(
    0,
    Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit"))),
  );
}

function normalizeRuntimeLog(item, fallbackSeq = 0) {
  const detail = item.detail ?? [
    item.solver_info ? `求解器 ${item.solver_info}` : "",
    item.scada_count !== undefined ? `量测 ${item.scada_count}` : "",
    item.command_count !== undefined ? `命令 ${item.command_count}` : "",
    item.alarm_count !== undefined ? `告警 ${item.alarm_count}` : "",
    item.updated !== undefined || item.missing !== undefined ? `更新/缺失 ${item.updated ?? 0}/${item.missing ?? 0}` : "",
  ].filter(Boolean);
  return {
    seq: item.seq ?? fallbackSeq,
    wall_time: item.wall_time || item.record_time || "",
    simu_time: item.simu_time || item.sim_time || item.time || "--",
    type: item.type || (item.state ? "仿真状态" : ""),
    target: item.target || (item.solver_info ? "潮流计算 / SCADA" : ""),
    result: item.result || item.state || "",
    detail,
    level: item.level || (item.missing ? "warn" : "info"),
  };
}

function runtimeLogColgroupHtml() {
  return `<colgroup>${state.runtimeLogColumnWidths.map((width) => `<col style="width:${Math.round(width)}px">`).join("")}</colgroup>`;
}

function applyRuntimeLogColumnWidths(table, widths = state.runtimeLogColumnWidths) {
  if (!table) return;
  const normalized = widths.map((value, index) => Math.max(
    RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
    Number(value) || RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[index],
  ));
  state.runtimeLogColumnWidths = normalized;
  table.querySelectorAll("colgroup col").forEach((column, index) => {
    if (normalized[index] !== undefined) column.style.width = `${Math.round(normalized[index])}px`;
  });
  table.style.width = `${Math.round(normalized.reduce((total, width) => total + width, 0))}px`;
  table.style.minWidth = "100%";
}

function enableRuntimeLogColumnResizing(table) {
  if (!table || table.dataset.columnResizeReady === "true") return;
  table.dataset.columnResizeReady = "true";
  applyRuntimeLogColumnWidths(table);
  const headers = Array.from(table.querySelectorAll("thead th"));
  headers.forEach((header, columnIndex) => {
    const handle = document.createElement("span");
    handle.className = "table-column-resize-handle";
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", `调整${header.textContent.trim()}列宽`);
    handle.title = "拖动调整列宽，双击恢复默认宽度";
    handle.tabIndex = 0;
    const restoreDefault = () => {
      state.runtimeLogColumnWidths[columnIndex] = RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[columnIndex];
      applyRuntimeLogColumnWidths(table);
      localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
    };
    handle.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      restoreDefault();
    });
    handle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const step = event.shiftKey ? 24 : 8;
      state.runtimeLogColumnWidths[columnIndex] = Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[columnIndex],
        state.runtimeLogColumnWidths[columnIndex] + (event.key === "ArrowRight" ? step : -step),
      );
      applyRuntimeLogColumnWidths(table);
      localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
    });
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      state.runtimeLogColumnWidths = headers.map((item, index) => Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
        Math.round(item.getBoundingClientRect().width),
      ));
      applyRuntimeLogColumnWidths(table);
      const startX = event.clientX;
      const startWidth = state.runtimeLogColumnWidths[columnIndex];
      document.body.classList.add("is-resizing-table-column");
      handle.setPointerCapture?.(event.pointerId);
      const move = (moveEvent) => {
        state.runtimeLogColumnWidths[columnIndex] = Math.max(
          RUNTIME_LOG_COLUMN_MIN_WIDTHS[columnIndex],
          Math.round(startWidth + moveEvent.clientX - startX),
        );
        applyRuntimeLogColumnWidths(table);
      };
      const finish = () => {
        document.body.classList.remove("is-resizing-table-column");
        localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    });
    header.appendChild(handle);
  });
}

function renderRuntimeLogs() {
  const container = $("runtimeLogTable");
  if (!container) return;
  syncRuntimeLogTypeFilter();
  const allLogs = filteredRuntimeLogs();
  const logs = pagedRuntimeLogs(allLogs);
  renderRuntimeLogPager(allLogs);
  const filterOn = state.runtimeLogTypeFilter !== "all"
    || Boolean(String(state.runtimeLogKeywordFilter || "").trim())
    || Boolean(state.runtimeLogOnlyAlert);
  const clearFilterBtn = $("clearRuntimeLogFilters");
  if (clearFilterBtn) clearFilterBtn.hidden = !filterOn;
  const totalLogs = !filterOn
    ? Math.max(state.runtimeLogs.length, Number(state.runtimeLogTotal) || 0)
    : state.runtimeLogs.length;
  $("runtimeLogSummary").textContent = !filterOn
    ? `已加载 ${state.runtimeLogs.length}/${totalLogs} 条`
    : `${allLogs.length}/${state.runtimeLogs.length} 条`;
  const renderKey = [
    allLogs.length,
    state.runtimeLogPage,
    state.runtimeLogSelectedSeq,
    state.runtimeLogTypeFilter,
    state.runtimeLogKeywordFilter || "",
    Boolean(state.runtimeLogOnlyAlert),
    logs.map((item) => `${item.seq}:${item.level}`).join(","),
  ].join("|");
  if (container.dataset.runtimeLogRenderKey === renderKey) {
    return;
  }
  container.dataset.runtimeLogRenderKey = renderKey;
  if (!allLogs.length) {
    container.innerHTML = '<div class="empty-state">暂无运行日志</div>';
    return;
  }
  container.innerHTML = `
    <table class="runtime-log-table runtime-log-table-resizable">
      ${runtimeLogColgroupHtml()}
      <thead>
        <tr>
          <th>本机时刻</th>
          <th>仿真时刻</th>
          <th>类型</th>
          <th>对象</th>
          <th>结果</th>
          <th>概要</th>
        </tr>
      </thead>
      <tbody>
        ${logs.map((item) => `
          <tr
            class="runtime-log-row is-${escapeHtml(item.level || "info")}${(Number(item.seq) || 0) === state.runtimeLogSelectedSeq ? " is-selected" : ""}"
            data-runtime-log-seq="${escapeHtml(item.seq)}"
            tabindex="0"
            aria-selected="${(Number(item.seq) || 0) === state.runtimeLogSelectedSeq ? "true" : "false"}"
            aria-label="日志 ${escapeHtml(item.seq)}，双击查看详细信息"
          >
            <td class="mono-cell">${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time)}</td>
            <td>${escapeHtml(item.type)}</td>
            <td>${escapeHtml(item.target)}</td>
            <td>${escapeHtml(item.result)}</td>
            <td class="runtime-log-detail" title="双击查看详细信息">${escapeHtml(runtimeLogSummaryText(item))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
  enableRuntimeLogColumnResizing(container.querySelector(".runtime-log-table-resizable"));
}

function definitionBlocks(kind, snapshot = state.snapshot || {}) {
  return snapshot.definitions?.[kind] || {};
}

function definedModelDevices(snapshot = state.snapshot || {}) {
  const blocks = definitionBlocks("model", snapshot);
  return Object.entries(blocks).flatMap(([blockName, block]) => {
    const headers = Array.isArray(block.headers) ? block.headers : [];
    return (block.rows || []).map((row, index) => {
      const raw = {};
      headers.forEach((header) => {
        raw[header] = row?.[header] ?? "";
      });
      const idx = raw.idx ?? row?.idx ?? index + 1;
      const definedName = raw.name || raw.dev_name || "";
      const name = definedName || (idx !== "" ? `${blockName}_${idx}` : `${blockName}_${index + 1}`);
      return {
        dev_type: blockName,
        dev_name: String(name || `${blockName}_${index + 1}`),
        idx,
        raw,
        __headers: headers,
        __definition_index: index,
      };
    });
  });
}

function gridModelDevices() {
  return definedModelDevices();
}

function gridModelFilterMatches(dev, filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" }) {
  return deviceFilterMatches(dev, filter);
}

function filteredGridModelDevices(devices = gridModelDevices()) {
  return devices.filter((dev) => gridModelFilterMatches(dev));
}

function gridModelFilterLabel(filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" }) {
  return deviceFilterLabel(filter);
}

function formatModelParamValue(value, field = "") {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (diagramDefinitionRatioField(field)) return diagramDefinitionDisplayValue(field, value);
  return String(value);
}

function modelDeviceIndexValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.POSITIVE_INFINITY;
}

function compareModelRowsByIndex(left, right) {
  const indexCompare = modelDeviceIndexValue(left.idx ?? left.raw?.idx) - modelDeviceIndexValue(right.idx ?? right.raw?.idx);
  if (indexCompare) return indexCompare;
  return String(left.name || left.dev_name || "").localeCompare(String(right.name || right.dev_name || ""));
}

function modelAttributeRecordForDevice(dev) {
  const raw = dev.raw || {};
  const headers = Array.isArray(dev.__headers) ? dev.__headers : Object.keys(raw);
  const record = {
    dev_type: dev.dev_type || "--",
    dev_name: dev.dev_name || "--",
    idx: formatModelParamValue(raw.idx ?? dev.idx),
    name: formatModelParamValue(raw.name || dev.dev_name),
    __headers: headers,
  };
  headers.forEach((key) => {
    if (["idx", "name", "dev_name", "dev_type"].includes(key)) return;
    record[key] = formatModelParamValue(raw[key], key);
  });
  return record;
}

function modelAttributeLabel(key) {
  const labels = {
    idx: "idx",
    name: "名称",
  };
  return labels[key] || key;
}

function modelAttributeColumns(records) {
  const fixed = ["idx", "name"];
  const seen = new Set([...fixed, "dev_type", "dev_name", "__headers"]);
  const keys = [];
  const appendKey = (key) => {
    if (!key || seen.has(key)) return;
    if (!records.some((record) => record[key] !== undefined && record[key] !== "--")) return;
    seen.add(key);
    keys.push(key);
  };
  records.forEach((record) => {
    (record.__headers || Object.keys(record)).forEach(appendKey);
  });
  return [...fixed, ...keys].map((key) => ({ key, label: modelAttributeLabel(key) }));
}

function groupedModelAttributeRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const devType = record.dev_type || "未分类";
    const rows = groups.get(devType) || [];
    rows.push(record);
    groups.set(devType, rows);
  });
  return Array.from(groups.entries())
    .map(([devType, rows]) => [
      devType,
      rows.sort(compareModelRowsByIndex),
    ])
    .sort(([left], [right]) => String(left).localeCompare(String(right)));
}

function renderModelAttributeTable(rows) {
  const columns = modelAttributeColumns(rows);
  return `
    <table class="model-param-table">
      <thead>
        <tr>
          ${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            ${columns.map((column) => `<td class="attr-value">${escapeHtml(row[column.key] ?? "--")}</td>`).join("")}
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renderGridModelDeviceTree() {
  const container = $("modelDeviceTree");
  if (!container) return;
  const devices = gridModelDevices();
  const filter = state.modelDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices).map(([devType, items]) => [
    devType,
    [...items].sort(compareModelRowsByIndex),
  ]);
  const treeResult = filterDeviceTreeGroups(groupEntries, "model");
  $("modelTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-model-tree-type="all"
      data-model-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("model", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
          data-model-tree-type="${escapeHtml(devType)}"
          data-model-tree-name=""
          ${deviceTreeTypeAttrs("model", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => {
            const idx = formatModelParamValue(dev.idx ?? dev.raw?.idx);
            return `
            <button
              type="button"
              class="tree-node tree-child model-tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-model-tree-type="${escapeHtml(dev.dev_type)}"
              data-model-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span class="model-tree-idx">${escapeHtml(idx)}</span>
              <span class="model-tree-name">${escapeHtml(dev.dev_name)}</span>
            </button>
          `;
          }).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function runtimeLogTypes() {
  return Array.from(new Set(state.runtimeLogs.map((item) => String(item.type || "")).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncRuntimeLogTypeFilter() {
  const select = $("runtimeLogTypeFilter");
  if (!select) return;
  const types = runtimeLogTypes();
  if (state.runtimeLogTypeFilter !== "all" && !types.includes(state.runtimeLogTypeFilter)) {
    state.runtimeLogTypeFilter = "all";
  }
  const optionsKey = types.join("|");
  if (select.dataset.optionsKey !== optionsKey) {
    select.dataset.optionsKey = optionsKey;
    select.innerHTML = ["<option value=\"all\">全部类型</option>", ...types.map((type) => (
      `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`
    ))].join("");
  }
  if (select.value !== state.runtimeLogTypeFilter) {
    select.value = state.runtimeLogTypeFilter;
  }
}

function filteredRuntimeLogs() {
  const keyword = String(state.runtimeLogKeywordFilter || "").trim().toLowerCase();
  const onlyAlert = Boolean(state.runtimeLogOnlyAlert);
  return state.runtimeLogs.filter((item) => {
    if (state.runtimeLogTypeFilter !== "all" && item.type !== state.runtimeLogTypeFilter) return false;
    if (onlyAlert && !["warn", "warning", "error", "bad"].includes(String(item.level || "").toLowerCase())) {
      return false;
    }
    if (keyword) {
      const hay = `${item.type || ""} ${item.target || ""} ${item.result || ""} ${runtimeLogSummaryText(item)}`.toLowerCase();
      if (!hay.includes(keyword)) return false;
    }
    return true;
  });
}

function runtimeLogPageCount(logs = filteredRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const total = state.runtimeLogTypeFilter === "all"
    ? Math.max((logs || []).length, Number(state.runtimeLogTotal) || 0)
    : (logs || []).length;
  return Math.max(1, Math.ceil(total / pageSize));
}

function pagedRuntimeLogs(logs = filteredRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const pageCount = runtimeLogPageCount(logs);
  state.runtimeLogPage = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (state.runtimeLogPage - 1) * pageSize;
  return logs.slice(start, start + pageSize);
}

async function ensureRuntimeLogPageLoaded(page = state.runtimeLogPage) {
  if (state.runtimeLogTypeFilter !== "all") return;
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const neededRows = Math.max(0, Number(page) || 1) * pageSize;
  if (state.runtimeLogs.length >= neededRows) return;
  await fetchRuntimeLogHistoryPage(false);
}

function renderRuntimeLogPager(logs = filteredRuntimeLogs()) {
  const pager = $("runtimeLogPager");
  if (!pager) return;
  if (!logs.length) {
    pager.innerHTML = "";
    return;
  }
  const pageCount = runtimeLogPageCount(logs);
  const page = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (page - 1) * state.runtimeLogPageSize + 1;
  const total = state.runtimeLogTypeFilter === "all"
    ? Math.max(logs.length, Number(state.runtimeLogTotal) || 0)
    : logs.length;
  const end = Math.min(total, page * state.runtimeLogPageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${total} 条</span>
    <button type="button" data-runtime-log-page="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <strong>第 ${page} / ${pageCount} 页</strong>
    <button type="button" data-runtime-log-page="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

async function clearRuntimeLogs() {
  const confirmed = await confirmDangerousAction({
    title: "清空全部运行日志？",
    target: `当前已记录 ${state.runtimeLogs.length} 条日志`,
    message: "清空后历史运行记录将立即移除且不可恢复。",
    confirmLabel: "确认清空",
  });
  if (!confirmed) return;
  const button = $("clearRuntimeLogs");
  if (button) button.disabled = true;
  try {
    await api("/api/runtime-logs/clear", { method: "POST", body: "{}" });
    state.runtimeLogs = [];
    state.runtimeLogSeq = 0;
    state.runtimeLogSelectedSeq = 0;
    closeRuntimeLogDetailDialog();
    state.runtimeLogPage = 1;
    state.runtimeLogTypeFilter = "all";
    renderRuntimeLogs();
    showUiToast("已清空运行日志", "ok");
  } finally {
    if (button) button.disabled = false;
  }
}

function renderGridModelParamTable() {
  const container = $("modelParamTable");
  if (!container) return;
  const devices = gridModelDevices();
  const rev = state.snapshot?.static_meta?.definitions?.revision ?? state.snapshot?.definitions?.revision ?? 0;
  const filterKey = JSON.stringify(state.modelDeviceFilter || { dev_type: "all", dev_name: "" });
  const editSeq = Number(state.localDefinitionEditSeq || 0);
  const renderKey = `${state.activeModelId}|${rev}|${editSeq}|${devices.length}|${filterKey}|${state.activeModelParamTab}`;
  if (container.dataset.renderKey === renderKey && container.childElementCount > 0) {
    return;
  }
  const prevScrollEl = container.querySelector(".model-param-table-wrap, .model-param-tab-page");
  const prevScrollTop = prevScrollEl ? prevScrollEl.scrollTop : container.scrollTop;
  const prevScrollLeft = prevScrollEl ? prevScrollEl.scrollLeft : container.scrollLeft;
  const rows = filteredGridModelDevices(devices).map(modelAttributeRecordForDevice);
  const groups = groupedModelAttributeRecords(rows);
  const availableTabs = groups.map(([devType]) => devType);
  if (!availableTabs.includes(state.activeModelParamTab)) {
    state.activeModelParamTab = availableTabs[0] || "";
  }
  const activeGroup = groups.find(([devType]) => devType === state.activeModelParamTab) || groups[0];
  const activeColumnCount = activeGroup ? modelAttributeColumns(activeGroup[1]).length : 0;
  $("modelParamSummary").textContent = groups.length > 1
    ? `${gridModelFilterLabel()} · ${rows.length}/${devices.length} 台 · ${groups.length} 个分页`
    : `${gridModelFilterLabel()} · ${rows.length}/${devices.length} 台 · ${activeColumnCount} 列属性`;
  container.dataset.renderKey = `${state.activeModelId}|${rev}|${editSeq}|${devices.length}|${filterKey}|${state.activeModelParamTab}`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无电网模型数据</div>';
    return;
  }
  requestAnimationFrame(() => {
    const nextScrollEl = container.querySelector(".model-param-table-wrap, .model-param-tab-page") || container;
    if (prevScrollTop) nextScrollEl.scrollTop = prevScrollTop;
    if (prevScrollLeft) nextScrollEl.scrollLeft = prevScrollLeft;
  });
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无模型参数</div>';
    return;
  }
  const [activeType, activeRows] = activeGroup;
  container.innerHTML = `
    <div class="model-param-tabs" role="tablist" aria-label="设备类型参数表">
      ${groups.map(([devType, groupRows]) => `
        <button
          type="button"
          role="tab"
          class="model-param-tab ${devType === activeType ? "is-active" : ""}"
          data-model-param-tab="${escapeHtml(devType)}"
          aria-selected="${devType === activeType ? "true" : "false"}"
        >
          <span>${escapeHtml(devType)}</span>
          <strong>${groupRows.length}</strong>
        </button>
      `).join("")}
    </div>
    <section class="model-param-tab-page" role="tabpanel" data-model-param-page="${escapeHtml(activeType)}">
      ${renderModelAttributeTable(activeRows)}
    </section>
  `;
}

function renderGridModelPage() {
  renderGridModelDeviceTree();
  renderGridModelParamTable();
}

function setGridModelFilter(devType, devName = "", event = null, button = null) {
  state.modelDeviceFilter = updateDeviceTreeFilterSelection(
    "modelDeviceFilter",
    devType,
    devName,
    event,
    "model",
    button,
  );
  if (devType && devType !== "all" && !devName) state.activeModelParamTab = devType;
  renderGridModelPage();
}

function setModelParamTab(devType) {
  if (!devType || state.activeModelParamTab === devType) return;
  state.activeModelParamTab = devType;
  renderGridModelParamTable();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function definedControlRows(blockName, snapshot = state.snapshot || {}) {
  const block = definitionBlocks("control", snapshot)?.[blockName];
  const headers = Array.isArray(block?.headers) ? block.headers : [];
  return (block?.rows || []).map((row, index) => {
    const raw = {};
    headers.forEach((header) => {
      raw[header] = row?.[header] ?? "";
    });
    return {
      ...raw,
      dev_type: raw.dev_type ?? row?.dev_type ?? "",
      dev_name: raw.dev_name ?? raw.name ?? row?.dev_name ?? row?.name ?? "",
      idx: raw.idx ?? row?.idx ?? index + 1,
      __headers: headers,
      __control_block: blockName,
      __definition_index: index,
    };
  }).filter((row) => row.dev_type && row.dev_name);
}

function runtimeSnapshotDevice(devType, devName, snapshot = state.snapshot || {}) {
  return (snapshot.devices || []).find((dev) => dev.dev_type === devType && dev.dev_name === devName) || null;
}

function runtimeSnapshotDevicesByKey(snapshot = state.snapshot || {}) {
  const snapshotDevicesByKey = new Map();
  (snapshot.devices || []).forEach((dev) => {
    snapshotDevicesByKey.set(`${dev.dev_type || ""}|${dev.dev_name || ""}`, dev);
  });
  return snapshotDevicesByKey;
}

function runtimeControlDeviceFromRow(row, snapshot = state.snapshot || {}, context = null) {
  const live = context?.snapshotDevicesByKey?.get(`${row.dev_type || ""}|${row.dev_name || ""}`)
    || runtimeSnapshotDevice(row.dev_type, row.dev_name, snapshot)
    || {};
  return {
    ...live,
    dev_type: row.dev_type,
    dev_name: row.dev_name,
    idx: live.idx ?? live.raw?.idx ?? row.idx ?? "",
    run_stat: live.run_stat ?? row.run_stat ?? 1,
    status: live.status ?? row.status ?? 1,
    mode: live.mode ?? live.raw?.control_type ?? live.raw?.ctrl_mode ?? "",
    set_values: live.set_values || {},
    raw: live.raw || {},
  };
}

function controlDefinitionDevices(snapshot = state.snapshot || {}) {
  const rows = [
    ...definedControlRows("RunStat", snapshot),
    ...definedControlRows("CbOpenStat", snapshot),
    ...definedControlRows("SetValue", snapshot),
  ];
  const devices = new Map();
  rows.forEach((row) => {
    const key = `${row.dev_type}|${row.dev_name}`;
    const existing = devices.get(key) || runtimeControlDeviceFromRow(row, snapshot);
    existing.__control_rows = existing.__control_rows || [];
    existing.__control_rows.push(row);
    if (row.__control_block === "RunStat") existing.run_stat = existing.run_stat ?? row.run_stat;
    if (row.__control_block === "CbOpenStat") {
      existing.status = existing.closed_status_set
        ?? row.closed_status_set
        ?? existing.status
        ?? row.status;
    }
    if (row.__control_block === "SetValue" && row.set_type) {
      existing.set_values = { ...(existing.set_values || {}) };
      if (existing.set_values[row.set_type] === undefined) existing.set_values[row.set_type] = row.set_value;
    }
    devices.set(key, existing);
  });
  return Array.from(devices.values());
}

function runtimeDevices() {
  return controlDefinitionDevices();
}

function runtimeFilterMatches(dev, filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" }) {
  return deviceFilterMatches(dev, filter);
}

function filteredRuntimeDevices(devices = runtimeDevices()) {
  return devices.filter((dev) => runtimeFilterMatches(dev));
}

function runtimeControlMeta(dev) {
  const setValues = dev?.set_values || {};
  const raw = dev?.raw || {};
  const mode = String(dev?.mode || raw.control_type || raw.ctrl_mode || "").toUpperCase();
  const acControlType = String(raw.ac_control_type ?? dev?.ac_control_type ?? "").trim().toUpperCase();
  const dcControlType = String(raw.dc_control_type ?? dev?.dc_control_type ?? "").trim().toUpperCase();
  const usesDcPowerSetpoint = dcControlType === "P"
    || (dcControlType === "NONE" && (!acControlType || acControlType === "NONE"));
  const preferred = [];
  if (mode.includes("V")) preferred.push("v_set", "v_ac_set", "v_dc_set");
  if (mode.includes("Q")) preferred.push("q_set", "q_ac_set");
  if (usesDcPowerSetpoint || mode.includes("P") || mode.includes("H")) {
    preferred.push(
      ...(usesDcPowerSetpoint
        ? ["p_dc_set", "p_ac_set", "p_set", "pv0"]
        : ["p_ac_set", "p_dc_set", "p_set", "pv0"]),
    );
  }
  preferred.push(
    ...(usesDcPowerSetpoint
      ? ["p_dc_set", "p_ac_set", "p_set", "pv0"]
      : ["p_ac_set", "p_dc_set", "p_set", "pv0"]),
    "q_ac_set",
    "q_set",
    "qv0",
    "v_ac_set",
    "v_dc_set",
    "v_set",
    "i_set",
  );
  const candidates = Array.from(new Set(preferred));
  for (const key of candidates) {
    const value = numberOrNull(setValues[key] ?? raw[key]);
    if (value !== null) return runtimeMetaFromSetKey(key, value);
  }
  const soc = numberOrNull(dev?.soc_curr ?? raw.soc_curr ?? raw.soc);
  if (soc !== null) {
    return { key: "soc_curr", label: "soc_curr", kind: "SOC", unit: "%", value: soc };
  }
  return { key: "run_stat", label: "run_stat", kind: "STAT", unit: "", value: numberOrNull(dev?.run_stat) ?? 0 };
}

function runtimeMetaFromSetKey(key, value) {
  const lowerKey = String(key).toLowerCase();
  if (lowerKey.includes("soc")) return { key, label: key, kind: "SOC", unit: "%", value };
  if (lowerKey.startsWith("q") || lowerKey.includes("_q")) return { key, label: key, kind: "Q", unit: "kvar", value };
  if (lowerKey.startsWith("v") || lowerKey.includes("_v")) return { key, label: key, kind: "V", unit: "V", value };
  if (lowerKey.startsWith("i") || lowerKey.includes("_i")) return { key, label: key, kind: "I", unit: "A", value };
  if (lowerKey === "run_stat") return { key, label: key, kind: "STAT", unit: "", value };
  return { key, label: key, kind: "P", unit: "kW", value };
}

function runtimeSetpointLabel(key, kind) {
  return {
    p_ac_set: "ACP有功设定值",
    p_dc_set: "DCP有功设定值",
  }[String(key || "").trim().toLowerCase()] || `${kind}设定值`;
}

function runtimeMeasurementTypeCandidates(dev, setKey) {
  const key = String(setKey || "").trim().toLowerCase();
  if (!key) return [];
  const measurementKey = key.endsWith("_set") ? key.slice(0, -4) : key;
  const exactType = measurementKey.toUpperCase();
  const quantity = measurementKey.split("_", 1)[0].toUpperCase();
  const family = String(dev?.device_family || "").trim().toLowerCase();
  const domains = new Set((Array.isArray(dev?.terminal_domains) ? dev.terminal_domains : [])
    .map((value) => String(value || "").trim().toUpperCase())
    .filter(Boolean));
  const candidates = [];
  const add = (...types) => types.forEach((type) => {
    const normalized = String(type || "").trim().toUpperCase();
    if (normalized && !candidates.includes(normalized)) candidates.push(normalized);
  });

  if (measurementKey.includes("_")) add(exactType);
  if (measurementKey.includes("soc")) add("SOC");
  if (family === "generator") {
    add(`${quantity}_GEN`);
  } else if (family === "load") {
    add(`${quantity}_LOAD`);
  } else if (family === "converter" && domains.has("AC") && domains.has("DC")) {
    add(`${quantity}_AC`, `${quantity}_DC`);
  } else if (family === "converter") {
    add(`${quantity}_FROM`, `${quantity}_TO`);
  } else {
    add(
      `${quantity}_GEN`,
      `${quantity}_LOAD`,
      `${quantity}_AC`,
      `${quantity}_DC`,
      `${quantity}_FROM`,
      `${quantity}_TO`,
    );
  }
  add(exactType, quantity);
  return candidates;
}

function runtimeMeasTypeMatchesSetKey(measType, setKey, dev = null) {
  const type = String(measType || "").toUpperCase();
  const normalizedSetKey = String(setKey || "").trim().toUpperCase();
  if (!type || !normalizedSetKey) return false;
  if (!normalizedSetKey.endsWith("_SET")) return type === normalizedSetKey;
  return runtimeMeasurementTypeCandidates(dev, setKey).includes(type);
}

function groupRuntimeMeasurementRowsByDevice(rows = []) {
  const rowsByDevice = new Map();
  (rows || []).forEach((row) => {
    const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
    const deviceRows = rowsByDevice.get(key) || [];
    deviceRows.push(row);
    rowsByDevice.set(key, deviceRows);
  });
  return rowsByDevice;
}

function runtimeMeasurementRowsByDevice(measurements = state.snapshot?.measurements || {}) {
  return groupRuntimeMeasurementRowsByDevice(measurementCompareRows(measurements));
}

function runtimeMeasurementPair(dev, meta, measurements = state.snapshot?.measurements || {}, context = null) {
  const measurementRowsByDevice = context?.measurementRowsByDevice
    || groupRuntimeMeasurementRowsByDevice(measurementCompareRows(measurements));
  const rows = measurementRowsByDevice.get(`${dev.dev_type || ""}|${dev.dev_name || ""}`) || [];
  let best = {};
  for (const candidate of runtimeMeasurementTypeCandidates(dev, meta.key || meta.kind)) {
    best = rows.find((row) => runtimeMeasTypeMatchesSetKey(row.meas_type, candidate)) || {};
    if (best.meas_type) break;
  }
  return {
    name: best.name || "",
    meas_type: best.meas_type || "",
    real: numberOrNull(best.real_value),
    scada: numberOrNull(best.scada_value),
  };
}

function runtimeSignalMeasurementPair(dev, measType, measurements = state.snapshot?.measurements || {}, context = null) {
  const measurementRowsByDevice = context?.measurementRowsByDevice
    || runtimeMeasurementRowsByDevice(measurements);
  const rows = measurementRowsByDevice.get(`${dev.dev_type || ""}|${dev.dev_name || ""}`) || [];
  const expectedType = String(measType || "").toUpperCase();
  const best = rows.find((row) => String(row.meas_type || "").toUpperCase() === expectedType) || {};
  return {
    name: best.name || "",
    meas_type: best.meas_type || "",
    real: numberOrNull(best.real_value),
    scada: numberOrNull(best.scada_value),
  };
}

function formatRuntimeRemoteSignal(value, commandType) {
  const numeric = numberOrNull(value);
  if (numeric === null) return "--";
  if (commandType === "status") return numeric !== 0 ? "闭合" : "断开";
  return numeric !== 0 ? "投入" : "退出";
}

function runtimeDeviceTraceSignal(dev, measurements = state.snapshot?.measurements || {}, context = null) {
  const control = runtimeControlMeta(dev);
  const pair = runtimeMeasurementPair(dev, control, measurements, context);
  return {
    control: control.value,
    real: pair.real,
    scada: pair.scada,
    set_type: control.key,
    signal_kind: control.kind,
    unit: control.unit,
    meas_name: pair.name,
    meas_type: pair.meas_type,
  };
}

function runtimeCommandTraceKey(row) {
  const dev = row.device || {};
  return [
    row.command_kind || "runtime_command",
    dev.dev_type || "",
    dev.dev_name || "",
    row.set_type || "",
  ].join("|");
}

function runtimeCommandTraceLabel(row) {
  const dev = row.device || {};
  return row.trace_label || `${dev.dev_name || "--"} · ${row.command || "--"} ${row.set_type || ""}`.trim();
}

function runtimeCommandTypeLabel(row) {
  return row?.command || row?.set_type || row?.category || row?.signal_kind || "";
}

function runtimeCommandRowOrigin(row) {
  const origin = String(row?.receive_time?.command_origin || row?.command_origin || "").trim().toLowerCase();
  return ["manual", "automatic"].includes(origin) ? origin : "";
}

function runtimeCommandFilterFields(row) {
  const dev = row?.device || {};
  return [
    runtimeCommandTraceLabel(row),
    runtimeCommandTypeLabel(row),
    row?.category,
    row?.command_kind,
    row?.command,
    row?.set_type,
    row?.signal_kind,
    row?.command_text,
    row?.real_text,
    row?.scada_text,
    dev.dev_type,
    dev.dev_name,
    dev.mode,
  ];
}

function syncRuntimeCommandTypeFilter(rows) {
  syncTableKeywordFilter("runtimeCommandKeywordFilter", state.runtimeCommandKeywordFilter);
  syncTableTypeFilter(
    "runtimeCommandTypeFilter",
    "runtimeCommandTypeFilter",
    tableFilterTypeOptions(rows, runtimeCommandTypeLabel),
  );
  const originSelect = $("runtimeCommandOriginFilter");
  if (originSelect) originSelect.value = state.runtimeCommandOriginFilter || "all";
}

function applyRuntimeCommandTableFilters(rows) {
  const keyword = state.runtimeCommandKeywordFilter || "";
  const type = state.runtimeCommandTypeFilter || "all";
  const origin = state.runtimeCommandOriginFilter || "all";
  return (rows || []).filter((row) => {
    if (state.runtimeCommandOnlyActive && !row.active) return false;
    if (!tableFilterMatchesKeyword(runtimeCommandFilterFields(row), keyword)) return false;
    if (type !== "all" && runtimeCommandTypeLabel(row) !== type) return false;
    if (origin !== "all" && runtimeCommandRowOrigin(row) !== origin) return false;
    return true;
  });
}

function syncRuntimeCommandOnlyActiveControl() {
  const input = $("runtimeCommandOnlyActive");
  const text = $("runtimeCommandOnlyActiveText");
  if (input) input.checked = Boolean(state.runtimeCommandOnlyActive);
  if (text) text.textContent = state.runtimeCommandOnlyActive ? "是" : "否";
}

function runtimeCommandRowsForDevices(devices, measurements = state.snapshot?.measurements || {}, context = null) {
  return [
    ...runtimeRemoteControlRows(devices, context),
    ...runtimeRemoteAdjustmentRows(devices, measurements, context),
  ];
}

function appendRuntimeTrace(snapshot) {
  const sampledClock = snapshot.measurement_clock;
  const clock = sampledClock && Number(sampledClock.step_count ?? 0) > 0
    ? sampledClock
    : snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return;
  const result = snapshot.result || {};
  const summary = snapshot.summary || {};
  const signature = [
    snapshot.model?.id || state.activeModelId,
    clock.absolute_minute ?? clock.minute ?? "",
    clock.time || "",
    result.updated ?? "",
    result.solver_info || "",
    summary.scada_count ?? 0,
  ].join("|");
  if (signature === state.lastRuntimeTraceKey) return;
  state.lastRuntimeTraceKey = signature;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.runtimeTraceHistory.length) || 0,
    sim_time: clock.time || "--",
    record_time: Date.now(),
    devices: {},
    commands: {},
  };
  const context = runtimeCommandBuildContext(snapshot, snapshot.measurements || {});
  const devices = [];
  controlDefinitionDevices(snapshot).forEach((dev) => {
    devices.push(dev);
    point.devices[deviceKey(dev)] = runtimeDeviceTraceSignal(dev, snapshot.measurements || {}, context);
  });
  runtimeCommandRowsForDevices(devices, snapshot.measurements || {}, context).forEach((row) => {
    point.commands[runtimeCommandTraceKey(row)] = {
      control: numberOrNull(row.control_value),
      real: numberOrNull(row.real_value),
      scada: numberOrNull(row.scada_value),
      unit: row.unit || "",
      signal_kind: row.signal_kind || "",
      label: runtimeCommandTraceLabel(row),
    };
  });
  state.runtimeTraceHistory.push(point);
  state.runtimeTraceHistory = compactTraceHistory(state.runtimeTraceHistory, state.runtimeTraceWindowMinutes);
}

function renderRuntimeDeviceTree() {
  const container = $("runtimeDeviceTree");
  if (!container) return;
  const devices = runtimeDevices();
  const filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "runtime");
  $("runtimeTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-runtime-tree-type="all"
      data-runtime-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("runtime", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
          data-runtime-tree-type="${escapeHtml(devType)}"
          data-runtime-tree-name=""
          ${deviceTreeTypeAttrs("runtime", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
            <button
              type="button"
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-runtime-tree-type="${escapeHtml(dev.dev_type)}"
              data-runtime-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function setRuntimeDeviceFilter(devType, devName = "", event = null, button = null) {
  state.runtimeDeviceFilter = updateDeviceTreeFilterSelection(
    "runtimeDeviceFilter",
    devType,
    devName,
    event,
    "runtime",
    button,
  );
  renderRuntimeMonitor(true);
}

function runtimeFilterLabel(filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" }) {
  return deviceFilterLabel(filter);
}

function formatRuntimeSignal(value, unit) {
  const formatted = formatMeasurementValue(value);
  return formatted === "--" || !unit ? formatted : `${formatted} ${unit}`;
}

function commandRefreshTimeFromMinute(minute) {
  const numericMinute = numberOrNull(minute);
  if (numericMinute === null) return "--";
  return formatSimulationClock({
    time: runtimeFormatClockMinute(numericMinute),
    minute: numericMinute,
    absolute_minute: numericMinute,
  });
}

function emptyCommandTimeInfo() {
  return {
    wall_time: "--",
    simu_time: "--",
    source: "",
    command_origin: "",
    origin_text: "--",
    process_state: "inactive",
    process_text: "未接收",
  };
}

function commandTimeInfoAvailable(info = {}) {
  return [info.wall_time, info.simu_time].some((value) => {
    const text = String(value || "").trim();
    return text && text !== "--";
  });
}

function commandReceiveTimeInfo(entry = {}) {
  const wallTime = runtimeLogWallTimeText(entry.received_wall_time || entry.time || entry.wall_time || entry.record_time || "");
  const minute = entry.received_absolute_minute ?? entry.issued_absolute_minute;
  const origin = commandOrigin(entry);
  const queued = String(entry.queue_state || "").trim().toLowerCase() === "waiting"
    || Number(entry.queued || 0) > 0;
  return {
    wall_time: wallTime,
    simu_time: commandRefreshTimeFromMinute(minute),
    source: String(entry.source || entry.payload?.source || ""),
    command_origin: origin,
    origin_text: commandOriginLabel(origin),
    process_state: queued ? "queued" : "effective",
    process_text: queued ? "已接收，模拟台排队" : "已接收，立即生效",
  };
}

function manualCommandHoldsAcrossClockLifecycle(entry = {}) {
  const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
  if (entry.manual_hold || entry.hold_until_cancelled || payload.manual_hold || payload.hold_until_cancelled) return true;
  if (payload.strategy && typeof payload.strategy === "object") return false;
  const source = String(entry.source || payload.source || "").trim().toLowerCase();
  if (source.includes("renewable") || source.includes("strategy")) return false;
  return source === "trainee-ui"
    || source === "student-ui"
    || source.startsWith("trainee-ui-")
    || source.startsWith("student-ui-")
    || source.includes("人工");
}

function commandOrigin(entry = {}) {
  const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
  const explicit = String(entry.command_origin || payload.command_origin || "").trim().toLowerCase();
  if (["manual", "human", "operator", "人工"].includes(explicit)) return "manual";
  if (["automatic", "auto", "strategy", "自动"].includes(explicit)) return "automatic";
  return manualCommandHoldsAcrossClockLifecycle(entry) ? "manual" : "automatic";
}

function commandOriginLabel(originOrEntry = "") {
  const origin = typeof originOrEntry === "string"
    ? String(originOrEntry).trim().toLowerCase()
    : commandOrigin(originOrEntry);
  if (origin === "manual") return "人工";
  if (origin === "automatic") return "自动";
  return "--";
}

function activeCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const commandEntries = Array.isArray(snapshot.commands?.effective)
    ? snapshot.commands.effective
    : (snapshot.commands?.history || []);
  return [...commandEntries].filter((entry) => {
    if (!entry?.eligible_source) return false;
    if (entry.cancelled) return false;
    const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);
    if (!manualHold) {
      const entryRunId = numberOrNull(entry.run_id);
      if (entryRunId === null || entryRunId !== currentRunId) return false;
    }
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = numberOrNull(entry.issued_absolute_minute);
    const expires = numberOrNull(entry.expires_at_absolute_minute);
    if (issued === null || expires === null) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function queuedCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const commandEntries = Array.isArray(snapshot.commands?.queued) ? snapshot.commands.queued : [];
  return [...commandEntries].filter((entry) => {
    if (!entry?.eligible_source || entry.cancelled) return false;
    const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);
    if (!manualHold) {
      const entryRunId = numberOrNull(entry.run_id);
      if (entryRunId === null || entryRunId !== currentRunId) return false;
    }
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = numberOrNull(entry.issued_absolute_minute);
    const expires = numberOrNull(entry.expires_at_absolute_minute);
    if (issued === null || expires === null) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function displayedCommandHistory(snapshot = state.snapshot || {}) {
  // Effective commands are appended last so they remain the displayed owner
  // when an automatic fallback is queued behind a manual command.
  return [...queuedCommandHistory(snapshot), ...activeCommandHistory(snapshot)];
}

function runtimeCommandRefreshIndex(snapshot = state.snapshot || {}) {
  const commandRefreshIndex = {
    run_stat: new Map(),
    status: new Map(),
    set_value: new Map(),
  };
  displayedCommandHistory(snapshot).forEach((entry) => {
    const normalized = entry.normalized || {};
    const payload = entry.payload || {};
    const info = commandReceiveTimeInfo(entry);
    const setItems = Array.isArray(normalized.set_values)
      ? normalized.set_values
      : Array.isArray(payload.set_values)
        ? payload.set_values
        : [];
    setItems.forEach((item) => {
      if (!item?.dev_type || !item?.dev_name || !item?.set_type) return;
      commandRefreshIndex.set_value.set(
        `${item.dev_type}|${item.dev_name}|${item.set_type}`,
        { ...info, control_value: item.set_value },
      );
    });
    const runItems = Array.isArray(normalized.run_status)
      ? normalized.run_status
      : Array.isArray(payload.run_status)
        ? payload.run_status
        : [];
    runItems.forEach((item) => {
      if (!item?.dev_type || !item?.dev_name) return;
      if (Object.prototype.hasOwnProperty.call(item, "status")) {
        commandRefreshIndex.status.set(
          `${item.dev_type}|${item.dev_name}|status`,
          { ...info, control_value: item.status },
        );
      }
      if (item.run_stat !== undefined && item.run_stat !== "") {
        commandRefreshIndex.run_stat.set(
          `${item.dev_type}|${item.dev_name}|run_stat`,
          { ...info, control_value: item.run_stat },
        );
      }
    });
  });
  return commandRefreshIndex;
}

function runtimeCommandBuildContext(snapshot = state.snapshot || {}, measurements = snapshot.measurements || {}, options = {}) {
  return {
    commandRefreshIndex: runtimeCommandRefreshIndex(snapshot),
    measurementRowsByDevice: options.includeMeasurements === false ? null : runtimeMeasurementRowsByDevice(measurements),
    snapshotDevicesByKey: runtimeSnapshotDevicesByKey(snapshot),
  };
}

function runtimeCommandRefreshInfo(dev, commandType, setType = "", snapshot = state.snapshot || {}, context = null) {
  const commandRefreshIndex = context?.commandRefreshIndex || runtimeCommandRefreshIndex(snapshot);
  const key = `${dev.dev_type || ""}|${dev.dev_name || ""}|${commandType === "set_value" ? setType : commandType}`;
  const indexed = commandRefreshIndex[commandType]?.get(key);
  if (indexed) return indexed;
  if (context?.commandRefreshIndex) return emptyCommandTimeInfo();
  const history = displayedCommandHistory(snapshot).reverse();
  for (const entry of history) {
    const normalized = entry.normalized || {};
    if (commandType === "set_value") {
      const items = normalized.set_values || entry.payload?.set_values || [];
      const match = items.find((item) => (
        item.dev_type === dev.dev_type
        && item.dev_name === dev.dev_name
        && item.set_type === setType
      ));
      if (match) return commandReceiveTimeInfo(entry);
      continue;
    }
    const items = normalized.run_status || entry.payload?.run_status || [];
    const match = items.find((item) => {
      if (item.dev_type !== dev.dev_type || item.dev_name !== dev.dev_name) return false;
      if (commandType === "status") return Object.prototype.hasOwnProperty.call(item, "status");
      return item.run_stat !== undefined && item.run_stat !== "";
    });
    if (match) return commandReceiveTimeInfo(entry);
  }
  return emptyCommandTimeInfo();
}

function runtimeCommandRefreshTime(dev, commandType, setType = "", snapshot = state.snapshot || {}) {
  return runtimeCommandRefreshInfo(dev, commandType, setType, snapshot).simu_time;
}

function selectedRuntimeDeviceKeys(devices) {
  return new Set((devices || []).map((dev) => deviceKey(dev)));
}

function runtimeRemoteControlRows(devices, context = null, options = {}) {
  const live = options.live !== false;
  const selectedKeys = selectedRuntimeDeviceKeys(devices);
  const runRows = definedControlRows("RunStat").filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
  const cbRows = definedControlRows("CbOpenStat").filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
  return [
    ...runRows.map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow, state.snapshot || {}, context);
      const runStatTime = runtimeCommandRefreshInfo(dev, "run_stat", "", state.snapshot || {}, context);
      const runPair = live
        ? runtimeSignalMeasurementPair(dev, "RUN_STAT", state.snapshot?.measurements || {}, context)
        : {};
      const value = Number(runStatTime.control_value ?? dev.run_stat ?? definitionRow.run_stat ?? 0);
      return {
        category: "遥控指令",
        command_kind: "remote_control",
        device: dev,
        command: "设备投退",
        set_type: "run_stat",
        command_text: formatRuntimeRemoteSignal(value, "run_stat"),
        real_text: formatRuntimeRemoteSignal(runPair.real ?? value, "run_stat"),
        scada_text: formatRuntimeRemoteSignal(runPair.scada, "run_stat"),
        refresh_time: runStatTime.simu_time,
        receive_time: runStatTime,
        active: commandTimeInfoAvailable(runStatTime),
        control_value: value,
        real_value: runPair.real ?? value,
        scada_value: runPair.scada ?? null,
        signal_kind: "STAT",
        unit: "",
        meas_name: runPair.name || "",
        meas_type: runPair.meas_type || "RUN_STAT",
        trace_label: `${dev.dev_type}.${dev.dev_name}.设备投退`,
      };
    }),
    ...cbRows.map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow, state.snapshot || {}, context);
      const statusTime = runtimeCommandRefreshInfo(dev, "status", "", state.snapshot || {}, context);
      const statusPair = live
        ? runtimeSignalMeasurementPair(dev, "STATUS", state.snapshot?.measurements || {}, context)
        : {};
      const value = Number(
        statusTime.control_value
        ?? dev.closed_status_set
        ?? dev.status
        ?? definitionRow.closed_status_set
        ?? definitionRow.status
        ?? 0,
      );
      return {
        category: "遥控指令",
        command_kind: "remote_control",
        device: dev,
        command: "开关开合",
        set_type: "status",
        command_text: formatRuntimeRemoteSignal(value, "status"),
        real_text: formatRuntimeRemoteSignal(statusPair.real ?? value, "status"),
        scada_text: formatRuntimeRemoteSignal(statusPair.scada, "status"),
        refresh_time: statusTime.simu_time,
        receive_time: statusTime,
        active: commandTimeInfoAvailable(statusTime),
        control_value: value,
        real_value: statusPair.real ?? value,
        scada_value: statusPair.scada ?? null,
        signal_kind: "STAT",
        unit: "",
        meas_name: statusPair.name || "",
        meas_type: statusPair.meas_type || "STATUS",
        trace_label: `${dev.dev_type}.${dev.dev_name}.开关开合`,
      };
    }),
  ];
}

function runtimeRemoteAdjustmentRows(devices, measurements = state.snapshot?.measurements || {}, context = null, options = {}) {
  const live = options.live !== false;
  const selectedKeys = selectedRuntimeDeviceKeys(devices);
  return definedControlRows("SetValue")
    .filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`))
    .map((definitionRow) => {
      const dev = runtimeControlDeviceFromRow(definitionRow, state.snapshot || {}, context);
      const key = definitionRow.set_type || "";
      const value = dev.set_values?.[key] ?? definitionRow.set_value;
      const commandTime = runtimeCommandRefreshInfo(dev, "set_value", key, state.snapshot || {}, context);
      const commandValue = commandTime.control_value ?? value;
      const meta = runtimeMetaFromSetKey(key, Number(commandValue));
      const pair = live ? runtimeMeasurementPair(dev, meta, measurements, context) : {};
      return {
        category: "遥调指令",
        command_kind: "remote_adjustment",
        device: dev,
        command: runtimeSetpointLabel(key, meta.kind),
        set_type: key,
        command_text: formatRuntimeSignal(meta.value, meta.unit),
        real_text: formatRuntimeSignal(pair.real, meta.unit),
        scada_text: formatRuntimeSignal(pair.scada, meta.unit),
        refresh_time: commandTime.simu_time,
        receive_time: commandTime,
        active: commandTimeInfoAvailable(commandTime),
        control_value: meta.value,
        real_value: pair.real,
        scada_value: pair.scada,
        signal_kind: meta.kind,
        unit: meta.unit,
        trace_label: `${dev.dev_type}.${dev.dev_name}.${key}`,
      };
    });
}

function renderRuntimeCommandTabs(remoteControlRows, remoteAdjustmentRows, activeTab = state.activeRuntimeCommandTab) {
  const normalizedTab = activeTab === "remote_adjustment" ? "remote_adjustment" : "remote_control";
  return `
    <div class="runtime-command-tabs" role="tablist" aria-label="控制指令类型">
      <button
        type="button"
        role="tab"
        class="runtime-command-tab ${normalizedTab === "remote_control" ? "is-active" : ""}"
        data-runtime-command-tab="remote_control"
        aria-selected="${normalizedTab === "remote_control" ? "true" : "false"}"
      >
        <span>遥控指令</span><strong>${remoteControlRows.length}</strong>
      </button>
      <button
        type="button"
        role="tab"
        class="runtime-command-tab ${normalizedTab === "remote_adjustment" ? "is-active" : ""}"
        data-runtime-command-tab="remote_adjustment"
        aria-selected="${normalizedTab === "remote_adjustment" ? "true" : "false"}"
      >
        <span>遥调指令</span><strong>${remoteAdjustmentRows.length}</strong>
      </button>
    </div>
  `;
}

function runtimeCommandTableStructureKey(rows) {
  const filter = state.runtimeDeviceFilter || { dev_type: "all", dev_name: "" };
  return [
    state.activeRuntimeCommandTab || "remote_control",
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.runtimeCommandKeywordFilter || "",
    state.runtimeCommandTypeFilter || "all",
    state.runtimeCommandOriginFilter || "all",
    state.runtimeCommandOnlyActive ? "active" : "all",
    rows.map((row) => runtimeCommandTraceKey(row)).join("||"),
  ].join("::");
}

function runtimeCommandTableValueText(row, field) {
  const textFields = {
    control: "command_text",
    real: "real_text",
    scada: "scada_text",
  };
  const text = String(row?.[textFields[field]] ?? "--");
  const unit = String(row?.unit || "").trim();
  if (!unit || text === "--") return text;
  const suffix = ` ${unit}`;
  return text.endsWith(suffix) ? text.slice(0, -suffix.length) : text;
}

function runtimeCommandDeleteName(row) {
  const devType = String(row?.device?.dev_type || "").trim();
  const devName = String(row?.device?.dev_name || "").trim();
  const fieldName = String(row?.set_type || "").trim();
  return devType && devName && fieldName ? `${devType}.${devName}.${fieldName}` : "";
}

function runtimeCommandDeleteButtonHtml(row) {
  const commandName = runtimeCommandDeleteName(row);
  const sending = commandName && state.runtimeCommandDeleteSending.has(commandName);
  const label = runtimeCommandTraceLabel(row);
  const devName = String(row?.device?.dev_name || "").trim();
  const kind = row?.command_kind === "remote_adjustment" ? "yt" : "yk";
  const jump104Btn = devName
    ? `<button
      type="button"
      class="compact-action-btn runtime-command-104-button"
      data-jump-scada104-device="${escapeHtml(devName)}"
      data-jump-scada104-kind="${kind}"
      title="在 IEC104 四遥点表中定位该设备"
    >104</button>`
    : "";
  return `
    <span class="runtime-command-row-actions">
      <button
        type="button"
        class="runtime-command-delete-button"
        data-runtime-command-delete-name="${escapeHtml(commandName)}"
        data-runtime-command-delete-label="${escapeHtml(label)}"
        title="删除当前有效指令"
        aria-label="删除当前有效指令：${escapeHtml(label)}"
        ${row.active && !sending ? "" : "disabled"}
      >${sending ? "删除中" : "删除"}</button>${jump104Btn}
    </span>
  `;
}

async function deleteRuntimeCommand(commandName, label = "") {
  const name = String(commandName || "").trim();
  if (!name || state.runtimeCommandDeleteSending.has(name)) return;
  const displayLabel = String(label || name).trim();
  const confirmed = await confirmDangerousAction({
    title: "删除当前有效控制指令？",
    target: displayLabel,
    message: "删除后将立即恢复模拟台默认值，后续学员台新下发指令仍可生效。",
    confirmLabel: "确认删除",
  });
  if (!confirmed) return;

  state.runtimeCommandDeleteSending.add(name);
  renderRuntimeDeviceTable();
  try {
    const result = await api("/api/simulator/commands/delete", {
      method: "POST",
      body: JSON.stringify({ commands: [{ name }] }),
    });
    const deleted = result.deleted || result;
    const count = Number(deleted.remote_controls || 0) + Number(deleted.remote_adjustments || 0);
    if (!count) {
      showUiToast(`未找到可删除的当前有效指令：${displayLabel}`, "warn", 3200);
    }
    await refresh();
  } catch (error) {
    showUiToast(`删除控制指令失败：${apiErrorText(error)}`, "error", 3600);
  } finally {
    state.runtimeCommandDeleteSending.delete(name);
    renderRuntimeDeviceTable();
  }
}

function runtimeCommandLiveCellHtml(row, field) {
  if (field === "control") return escapeHtml(runtimeCommandTableValueText(row, "control"));
  if (field === "origin") return escapeHtml(row.receive_time?.origin_text || "--");
  if (field === "wall_time") return escapeHtml(row.receive_time?.wall_time || "--");
  if (field === "simu_time") return escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--");
  if (field === "process") {
    const processState = row.receive_time?.process_state || "inactive";
    const processText = row.receive_time?.process_text || "未接收";
    return `<span class="command-process-pill is-${escapeHtml(processState)}">${escapeHtml(processText)}</span>`;
  }
  if (field === "real") return escapeHtml(runtimeCommandTableValueText(row, "real"));
  if (field === "scada") return escapeHtml(runtimeCommandTableValueText(row, "scada"));
  if (field === "delete") return runtimeCommandDeleteButtonHtml(row);
  return "";
}

function updateRuntimeCommandTableLiveCells(rows) {
  const tableRows = Array.from(document.querySelectorAll("#deviceTable [data-runtime-command-row-key]"));
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [runtimeCommandTraceKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.runtimeCommandRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    const selected = key === state.selectedRuntimeCommandKey;
    tableRow.classList.toggle("is-selected", selected);
    tableRow.dataset.runtimeCommandRowLabel = runtimeCommandTraceLabel(row);
    tableRow.querySelectorAll("[data-runtime-command-live-field]").forEach((cell) => {
      const nextHtml = runtimeCommandLiveCellHtml(row, cell.dataset.runtimeCommandLiveField || "");
      if (cell.dataset.lastHtml !== nextHtml) {
        cell.dataset.lastHtml = nextHtml;
        cell.innerHTML = nextHtml;
      }
    });
  }
  return true;
}

function renderRuntimeCommandRows(rows) {
  return rows.map((row) => {
    const traceKey = runtimeCommandTraceKey(row);
    const traceLabel = runtimeCommandTraceLabel(row);
    return `
    <tr
      class="${traceKey === state.selectedRuntimeCommandKey ? "is-selected" : ""}"
      data-runtime-command-row-key="${escapeHtml(traceKey)}"
      data-runtime-command-row-label="${escapeHtml(traceLabel)}"
      title="单击或双击刷新控制跟踪曲线"
    >
      <td>${escapeHtml(row.device.dev_name)}</td>
      <td>${escapeHtml(row.device.dev_type)}</td>
      <td>${escapeHtml(row.device.mode || "--")}</td>
      <td>${escapeHtml(row.command)} <small class="command-set-type">${escapeHtml(row.set_type)}</small></td>
      <td class="numeric-cell" data-runtime-command-live-field="control">${runtimeCommandLiveCellHtml(row, "control")}</td>
      <td data-runtime-command-live-field="origin">${runtimeCommandLiveCellHtml(row, "origin")}</td>
      <td class="mono-cell" data-runtime-command-live-field="wall_time">${escapeHtml(row.receive_time?.wall_time || "--")}</td>
      <td class="mono-cell" data-runtime-command-live-field="simu_time">${escapeHtml(row.receive_time?.simu_time || row.refresh_time || "--")}</td>
      <td data-runtime-command-live-field="process">${runtimeCommandLiveCellHtml(row, "process")}</td>
      <td class="numeric-cell" data-runtime-command-live-field="real">${runtimeCommandLiveCellHtml(row, "real")}</td>
      <td class="numeric-cell" data-runtime-command-live-field="scada">${runtimeCommandLiveCellHtml(row, "scada")}</td>
      <td class="runtime-command-delete-cell" data-runtime-command-live-field="delete">${runtimeCommandLiveCellHtml(row, "delete")}</td>
    </tr>
  `;
  }).join("");
}

function runtimeCommandSortAttr(col) {
  const s = state.tableSort?.runtimeCommand || { col: "", dir: "none" };
  const dir = s.col === col ? s.dir : "none";
  return `class="is-sortable" data-virtual-sort-table="runtimeCommand" data-virtual-sort-col="${col}" aria-sort="${dir}"`;
}

function sortRuntimeCommandRows(rows) {
  const s = state.tableSort?.runtimeCommand;
  if (!s || !s.col || s.dir === "none") return rows;
  const dir = s.dir === "ascending" ? 1 : -1;
  const rankProcess = (p) => (p === "effective" ? 2 : (p === "queued" ? 1 : 0));
  return rows.slice().sort((a, b) => {
    const col = s.col;
    if (col === "control" || col === "real" || col === "scada") {
      const key = col === "control" ? "control_value" : (col === "real" ? "real_value" : "scada_value");
      const va = Number(a[key]);
      const vb = Number(b[key]);
      const fa = Number.isFinite(va);
      const fb = Number.isFinite(vb);
      if (fa && fb) return (va - vb) * dir;
      if (fa) return -1;
      if (fb) return 1;
      return 0;
    }
    if (col === "process") {
      return (rankProcess(a.receive_time?.process_state) - rankProcess(b.receive_time?.process_state)) * dir;
    }
    const textVal = (r) => {
      if (col === "device") return String(r.device?.dev_name || "");
      if (col === "dev_type") return String(r.device?.dev_type || "");
      if (col === "command") return String(r.command || "");
      if (col === "origin") return String(r.receive_time?.origin_text || "");
      if (col === "wall_time") return String(r.receive_time?.wall_time || "");
      if (col === "simu_time") return String(r.receive_time?.simu_time || r.refresh_time || "");
      return "";
    };
    return textVal(a).localeCompare(textVal(b), "zh-CN") * dir;
  });
}

function renderRuntimeCommandTable(rows, emptyText, virtualRows = { beforeHeight: 0, afterHeight: 0 }) {
  if (!rows.length) return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  const numSortAttr = (col) => {
    const s = state.tableSort?.runtimeCommand || { col: "", dir: "none" };
    const dir = s.col === col ? s.dir : "none";
    return `class="numeric-cell is-sortable" data-virtual-sort-table="runtimeCommand" data-virtual-sort-col="${col}" data-virtual-sort-numeric="1" aria-sort="${dir}"`;
  };
  return `
    <table class="runtime-device-table runtime-command-table">
      <thead>
        <tr>
          <th ${runtimeCommandSortAttr("device")}>设备</th>
          <th ${runtimeCommandSortAttr("dev_type")}>设备类型</th>
          <th>模式</th>
          <th ${runtimeCommandSortAttr("command")}>指令项</th>
          <th ${numSortAttr("control")}>控制指令</th>
          <th ${runtimeCommandSortAttr("origin")}>指令来源</th>
          <th ${runtimeCommandSortAttr("wall_time")}>接收本机时刻</th>
          <th ${runtimeCommandSortAttr("simu_time")}>接收仿真时刻</th>
          <th ${runtimeCommandSortAttr("process")}>处理状态</th>
          <th ${numSortAttr("real")}>实时值</th>
          <th ${numSortAttr("scada")}>量测值</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 12)}
        ${renderRuntimeCommandRows(rows)}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 12)}
      </tbody>
    </table>
  `;
}

function renderRuntimeDeviceTable() {
  const container = $("deviceTable");
  if (!container) return;
  syncRuntimeCommandOnlyActiveControl();
  const devices = runtimeDevices();
  const selectedDevices = filteredRuntimeDevices(devices);
  const activeTab = state.activeRuntimeCommandTab === "remote_adjustment" ? "remote_adjustment" : "remote_control";
  const context = runtimeCommandBuildContext(state.snapshot || {}, state.snapshot?.measurements || {}, {
    includeMeasurements: true,
  });
  const remoteControlRows = runtimeRemoteControlRows(selectedDevices, context, { live: activeTab === "remote_control" });
  const remoteAdjustmentRows = runtimeRemoteAdjustmentRows(selectedDevices, state.snapshot?.measurements || {}, context, { live: activeTab === "remote_adjustment" });
  const totalCommandRows = [...remoteControlRows, ...remoteAdjustmentRows];
  syncRuntimeCommandTypeFilter(totalCommandRows);
  const filteredRemoteControlRows = applyRuntimeCommandTableFilters(remoteControlRows);
  const filteredRemoteAdjustmentRows = applyRuntimeCommandTableFilters(remoteAdjustmentRows);
  const commandCount = filteredRemoteControlRows.length + filteredRemoteAdjustmentRows.length;
  const totalCommandCount = totalCommandRows.length;
  const visibleCommandKeys = new Set([...filteredRemoteControlRows, ...filteredRemoteAdjustmentRows].map(runtimeCommandTraceKey));
  if (state.selectedRuntimeCommandKey && !visibleCommandKeys.has(state.selectedRuntimeCommandKey)) {
    state.selectedRuntimeCommandKey = "";
    state.selectedRuntimeCommandLabel = "";
  }
  const filterActive = state.runtimeCommandOnlyActive
    || state.runtimeCommandOriginFilter !== "all"
    || tableFilterIsActive(state.runtimeCommandKeywordFilter, state.runtimeCommandTypeFilter);
  $("runtimeDeviceSummary").textContent = filterActive
    ? `${runtimeFilterLabel()} · ${commandCount}/${totalCommandCount} 条指令`
    : `${runtimeFilterLabel()} · ${totalCommandCount} 条指令`;
  if (!devices.length) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = '<div class="empty-state">暂无设备数据</div>';
    return;
  }
  if (!selectedDevices.length) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  if (!totalCommandCount) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = '<div class="empty-state">当前筛选无控制指令</div>';
    return;
  }
  const tabHtml = renderRuntimeCommandTabs(filteredRemoteControlRows, filteredRemoteAdjustmentRows, activeTab);
  const rawActiveRows = activeTab === "remote_adjustment"
    ? filteredRemoteAdjustmentRows
    : filteredRemoteControlRows;
  const activeRows = sortRuntimeCommandRows(rawActiveRows);
  const sortState = state.tableSort?.runtimeCommand || { col: "", dir: "none" };
  const virtualRows = virtualTableWindow(`runtimeCommand:${activeTab}`, activeRows);
  const structureKey = [
    runtimeCommandTableStructureKey(activeRows),
    `${sortState.col}:${sortState.dir}`,
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  const emptyText = activeTab === "remote_adjustment"
    ? (filterActive ? "当前过滤无遥调指令" : "当前筛选无遥调指令")
    : (filterActive ? "当前过滤无遥控指令" : "当前筛选无遥控指令");
  if (!activeRows.length) {
    container.dataset.runtimeCommandStructureKey = "";
    container.innerHTML = `${tabHtml}<section class="runtime-command-tab-page is-active" data-runtime-command-page="${activeTab}" role="tabpanel"><div class="empty-state">${escapeHtml(emptyText)}</div></section>`;
    return;
  }
  if (
    container.dataset.runtimeCommandStructureKey === structureKey
    && updateRuntimeCommandTableLiveCells(virtualRows.rows)
  ) {
    return;
  }
  container.dataset.runtimeCommandStructureKey = structureKey;
  container.innerHTML = `
    ${tabHtml}
    <section class="runtime-command-tab-page is-active" data-runtime-command-page="${activeTab}" role="tabpanel">
      <div class="runtime-command-table-wrap virtual-table-scroll" data-virtual-table="runtimeCommand:${activeTab}">
        ${renderRuntimeCommandTable(virtualRows.rows, emptyText, virtualRows)}
      </div>
    </section>
  `;
  restoreVirtualTableScroll(container, `runtimeCommand:${activeTab}`);
}

function setRuntimeCommandTab(tabName) {
  if (!["remote_control", "remote_adjustment"].includes(tabName)) return;
  if (state.activeRuntimeCommandTab === tabName) return;
  state.activeRuntimeCommandTab = tabName;
  state.selectedRuntimeCommandKey = "";
  state.selectedRuntimeCommandLabel = "";
  renderRuntimeDeviceTable();
  drawRuntimeTraceChart();
}

function selectRuntimeCommandTrace(key, label = "") {
  state.selectedRuntimeCommandKey = key || "";
  state.selectedRuntimeCommandLabel = label || "";
  document.querySelectorAll("[data-runtime-command-row-key]").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.runtimeCommandRowKey === state.selectedRuntimeCommandKey);
  });
  drawRuntimeTraceChart();
}

function selectedRuntimeCommandTraceRows() {
  const devices = filteredRuntimeDevices(runtimeDevices());
  const context = runtimeCommandBuildContext(state.snapshot || {}, state.snapshot?.measurements || {});
  return runtimeCommandRowsForDevices(devices, state.snapshot?.measurements || {}, context);
}

function selectedRuntimeCommandTraceSeries(range = runtimeTraceWindowRange()) {
  const key = state.selectedRuntimeCommandKey;
  if (!key) return null;
  const rows = selectedRuntimeCommandTraceRows();
  const row = rows.find((item) => runtimeCommandTraceKey(item) === key);
  if (!row) return null;
  const points = runtimeTraceWindowPoints(range)
    .map((point) => {
      const signal = point.commands?.[key];
      if (!signal) return null;
      return {
        minute: point.minute,
        sim_time: point.sim_time,
        control: numberOrNull(signal.control),
        real: numberOrNull(signal.real),
        scada: numberOrNull(signal.scada),
        unit: signal.unit || row.unit || "",
        signal_kind: signal.signal_kind || row.signal_kind || "",
      };
    })
    .filter(Boolean);
  return {
    label: state.selectedRuntimeCommandLabel || runtimeCommandTraceLabel(row),
    points,
  };
}

function runtimeTraceDevicesForChart() {
  const rows = filteredRuntimeDevices();
  if (rows.length <= 1) return rows;
  const firstMeta = runtimeControlMeta(rows[0]);
  return rows.filter((dev) => {
    const meta = runtimeControlMeta(dev);
    return meta.kind === firstMeta.kind && meta.unit === firstMeta.unit;
  });
}

function runtimeTraceWindowPoints(range = runtimeTraceWindowRange()) {
  const history = state.runtimeTraceHistory || [];
  if (!history.length) return [];
  return traceWindowRealPoints(history, range);
}

function traceAxisStepMinutes(windowMinutes) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  if (minutes <= 15) return 5;
  if (minutes <= 60) return 15;
  if (minutes <= 180) return 30;
  if (minutes <= 360) return 60;
  if (minutes <= 1440) return 240;
  if (minutes <= 10080) return 1440;
  if (minutes <= 43200) return 5 * 1440;
  if (minutes <= 525600) return 60 * 1440;
  return Math.max(60, Math.round(minutes / 6 / 60) * 60);
}

function traceWindowAlignmentMinutes(windowMinutes) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  if (minutes <= 15) return 15;
  if (minutes <= 1440) return minutes;
  if (minutes >= 525600) return 525600;
  return 1440;
}

function traceHistoryMinuteBounds(history, fallbackMinute = 0) {
  let earliestMinute = Number.POSITIVE_INFINITY;
  let latestMinute = Number.NEGATIVE_INFINITY;
  (Array.isArray(history) ? history : []).forEach((point) => {
    const minute = Number(point?.minute);
    if (!Number.isFinite(minute)) return;
    earliestMinute = Math.min(earliestMinute, minute);
    latestMinute = Math.max(latestMinute, minute);
  });
  const fallback = Number.isFinite(Number(fallbackMinute)) ? Number(fallbackMinute) : 0;
  const hasHistory = Number.isFinite(earliestMinute) && Number.isFinite(latestMinute);
  return {
    earliestMinute: hasHistory ? earliestMinute : fallback,
    latestMinute: hasHistory ? latestMinute : fallback,
    hasHistory,
  };
}

function alignedTraceWindowRange(
  history,
  windowMinutes,
  fallbackMinute,
  requestedOffset = 0,
  simulationDurationMinutes = Number.POSITIVE_INFINITY,
) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  const alignmentMinutes = traceWindowAlignmentMinutes(minutes);
  const axisStepMinutes = traceAxisStepMinutes(minutes);
  const bounds = traceHistoryMinuteBounds(history, fallbackMinute);
  const fallback = Number.isFinite(Number(fallbackMinute)) ? Number(fallbackMinute) : bounds.latestMinute;
  const latestMinute = Math.max(bounds.latestMinute, fallback);
  const currentStartMinute = Math.floor(latestMinute / alignmentMinutes) * alignmentMinutes;
  const normalizedSimulationDuration = Number(simulationDurationMinutes);
  const cycleStartMinute = Number.isFinite(normalizedSimulationDuration) && normalizedSimulationDuration > 0
    ? Math.floor((latestMinute + 1e-9) / normalizedSimulationDuration) * normalizedSimulationDuration
    : Number.NEGATIVE_INFINITY;
  const earliestMinute = bounds.hasHistory
    ? Math.max(bounds.earliestMinute, cycleStartMinute)
    : latestMinute;
  const periodNavigationAllowed = !Number.isFinite(normalizedSimulationDuration)
    || normalizedSimulationDuration <= 0
    || minutes < normalizedSimulationDuration;
  const minWindowOffset = periodNavigationAllowed && bounds.hasHistory
    ? Math.min(0, Math.floor((earliestMinute - currentStartMinute) / minutes))
    : 0;
  const normalizedOffset = periodNavigationAllowed
    ? Math.min(0, Math.trunc(Number(requestedOffset) || 0))
    : 0;
  const windowOffset = Math.max(minWindowOffset, normalizedOffset);
  const startMinute = currentStartMinute + windowOffset * minutes;
  return {
    startMinute,
    endMinute: startMinute + minutes,
    latestMinute,
    earliestMinute,
    currentStartMinute,
    windowMinutes: minutes,
    alignmentMinutes,
    axisStepMinutes,
    windowOffset,
    minWindowOffset,
    periodNavigationAllowed,
  };
}

function tracePeriodNavigationState(range = {}) {
  const periodNavigationAllowed = range.periodNavigationAllowed !== false;
  const windowOffset = Math.min(0, Math.trunc(Number(range.windowOffset) || 0));
  const minWindowOffset = Math.min(0, Math.trunc(Number(range.minWindowOffset) || 0));
  return {
    visible: periodNavigationAllowed && (minWindowOffset < 0 || windowOffset < 0),
    previousDisabled: !periodNavigationAllowed || windowOffset <= minWindowOffset,
    currentDisabled: !periodNavigationAllowed || windowOffset === 0,
    nextDisabled: !periodNavigationAllowed || windowOffset >= 0,
  };
}

function chartPeriodOffset(chartKey) {
  return Math.min(0, Math.trunc(Number(state.chartPeriodOffsets?.[chartKey]) || 0));
}

function setChartPeriodOffset(chartKey, offset) {
  state.chartPeriodOffsets = {
    ...(state.chartPeriodOffsets || {}),
    [chartKey]: Math.min(0, Math.trunc(Number(offset) || 0)),
  };
}

function resetChartPeriodOffsets(...chartKeys) {
  const keys = chartKeys.length ? chartKeys : Object.keys(state.chartPeriodOffsets || {});
  keys.forEach((chartKey) => setChartPeriodOffset(chartKey, 0));
}

function syncChartPeriodNavigation(chartKey, range) {
  const navigation = tracePeriodNavigationState(range);
  document.querySelectorAll(`[data-chart-period-nav="${chartKey}"]`).forEach((container) => {
    container.hidden = !navigation.visible;
    container.dataset.windowOffset = String(Number(range?.windowOffset) || 0);
    const previous = container.querySelector('[data-chart-period-action="previous"]');
    const current = container.querySelector('[data-chart-period-action="current"]');
    const next = container.querySelector('[data-chart-period-action="next"]');
    if (previous) previous.disabled = navigation.previousDisabled;
    if (current) current.disabled = navigation.currentDisabled;
    if (next) next.disabled = navigation.nextDisabled;
  });
  return navigation;
}

function initChartPeriodNavigation(chartKey, rangeProvider, drawChart) {
  const container = document.querySelector(`[data-chart-period-nav="${chartKey}"]`);
  if (!container || container.dataset.periodNavigationReady === "true") return;
  container.dataset.periodNavigationReady = "true";
  container.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest('[data-chart-period-action]')
      : null;
    if (!button || button.disabled || !container.contains(button)) return;
    const range = rangeProvider();
    const action = button.getAttribute("data-chart-period-action") || "";
    const currentOffset = Number(range.windowOffset) || 0;
    const nextOffset = action === "previous"
      ? currentOffset - 1
      : action === "next" ? currentOffset + 1 : 0;
    setChartPeriodOffset(chartKey, nextOffset);
    drawChart();
  });
}

function runtimeTraceWindowRange() {
  const history = state.runtimeTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.runtimeTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("runtimeTrace"),
    simulationModeDurationMinutes(),
  );
  setChartPeriodOffset("runtimeTrace", range.windowOffset);
  return range;
}

function runtimeFormatClockMinute(minute) {
  const total = ((Math.round(minute) % 1440) + 1440) % 1440;
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:00`;
}

function formatYearTraceTickLabel(minute) {
  const absoluteDay = Math.floor(Math.max(0, Number(minute) || 0) / 1440);
  const year = Math.floor(absoluteDay / 365) + 1;
  let dayOfYear = absoluteDay % 365;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfYear >= monthDays[month]) {
    dayOfYear -= monthDays[month];
    month += 1;
  }
  return year === 1 ? `${String(month + 1).padStart(2, "0")}月` : `第${year}年${String(month + 1).padStart(2, "0")}月`;
}

function runtimeAxisTickLabel(minute, range, index, lastIndex) {
  const targetMinute = index === lastIndex ? range.endMinute : minute;
  if (range.windowMinutes <= 1440) return runtimeFormatClockMinute(targetMinute);
  if (range.windowMinutes >= 525600) return formatYearTraceTickLabel(targetMinute);
  const absolute = Math.max(0, Math.round(targetMinute));
  const day = Math.floor(absolute / 1440);
  const clock = runtimeFormatClockMinute(absolute).slice(0, 5);
  return absolute % 1440 === 0 ? `第${day + 1}天` : `第${day + 1}天 ${clock}`;
}

function runtimeTracePointTimeLabel(point, range) {
  const time = String(point?.sim_time || point?.time || "").trim();
  if (time && time !== "--") return time;
  return runtimeAxisTickLabel(point?.minute, range, -1, 0);
}

function runtimeTraceAxisTicks(range, canvasWidth) {
  const maxTicks = canvasWidth < 480 ? 4 : canvasWidth < 760 ? 5 : 8;
  let step = range.axisStepMinutes || traceAxisStepMinutes(range.windowMinutes);
  while (Math.floor(range.windowMinutes / step) + 1 > maxTicks) {
    step *= 2;
  }
  const ticks = [];
  for (let minute = range.startMinute; minute <= range.endMinute + 1e-9; minute += step) {
    ticks.push(minute);
  }
  if (ticks[ticks.length - 1] !== range.endMinute) ticks.push(range.endMinute);
  return ticks;
}

function runtimeAggregateTracePoint(point, devices) {
  const keys = devices.map(deviceKey);
  const signals = keys.map((key) => point.devices[key]).filter(Boolean);
  const average = (field) => {
    const values = signals.map((signal) => numberOrNull(signal[field])).filter((value) => value !== null);
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  };
  const first = signals[0] || {};
  return {
    minute: point.minute,
    sim_time: point.sim_time,
    control: average("control"),
    real: average("real"),
    scada: average("scada"),
    unit: first.unit || "",
    signal_kind: first.signal_kind || "",
  };
}

function resizeRuntimeTraceCanvas() {
  const canvas = $("runtimeTraceChart");
  return resizeCanvasToRenderedSize(canvas, 900, 260);
}

function drawRuntimeTraceChart() {
  const canvas = $("runtimeTraceChart");
  if (!canvas) return;
  resizeRuntimeTraceCanvas();
  const chartKey = "runtimeTrace";
  const { ctx, width, height } = prepareCanvas2D(canvas, 900, 260);
  const plot = width < 640
    ? { left: 42, right: 14, top: 28, bottom: 32 }
    : { left: 58, right: 24, top: 28, bottom: 36 };
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  const range = runtimeTraceWindowRange();
  syncChartPeriodNavigation("runtimeTrace", range);
  const selectedCommandSeries = selectedRuntimeCommandTraceSeries(range);
  const chartDevices = selectedCommandSeries ? [] : runtimeTraceDevicesForChart();
  const points = selectedCommandSeries?.points
    || runtimeTraceWindowPoints(range).map((point) => runtimeAggregateTracePoint(point, chartDevices));
  const seriesDefs = [
    { key: "control", field: "control", label: "控制指令", color: "#b87500" },
    { key: "real", field: "real", label: "实时值", color: "#008c8c" },
    { key: "scada", field: "scada", label: "量测值", color: "#c93a3a" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  const palette = chartThemePalette();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = palette.text;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + i * ((bottom - top) / 4);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  const xTicks = runtimeTraceAxisTicks(range, width);
  xTicks.forEach((minute, tickIndex) => {
    const ratio = (minute - range.startMinute) / range.windowMinutes;
    const x = left + ratio * (right - left);
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? palette.axis : palette.gridSubtle;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4;
    ctx.fillText(runtimeAxisTickLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12);
  });
  const label = runtimeFilterLabel();
  const chartLabel = selectedCommandSeries
    ? selectedCommandSeries.label
    : chartDevices.length > 1 ? `${label} · ${chartDevices.length}台平均` : label;
  $("runtimeTraceSummary").textContent = `${chartLabel} · ${traceWindowDataPointCount(points)} 点`;
  if ((!selectedCommandSeries && !chartDevices.length) || !points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = palette.text;
    ctx.textAlign = "center";
    const emptyMsg = !visibleSeries.length ? "所有曲线已隐藏" : "暂无跟踪数据";
    ctx.fillText(typeof translatePhrase === "function" ? translatePhrase(emptyMsg) : emptyMsg, width / 2, height / 2);
    ctx.textAlign = "left";
    return;
  }
  let minValue = Infinity;
  let maxValue = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (v < minValue) minValue = v;
    if (v > maxValue) maxValue = v;
  }
  if (Math.abs(maxValue - minValue) < 1e-9) {
    minValue -= 1;
    maxValue += 1;
  }
  const padding = (maxValue - minValue) * 0.12;
  minValue -= padding;
  maxValue += padding;
  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * (right - left);
  const yForValue = (value) => bottom - ((value - minValue) / (maxValue - minValue)) * (bottom - top);
  const hitData = [];
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const drawSeries = (series, widthScale = 2) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = series.key === selectedSeries ? widthScale + 1.2 : widthScale;
    ctx.beginPath();
    let started = false;
    let previousY = Number.NaN;
    points.forEach((point) => {
      const value = numberOrNull(point[series.field]);
      if (value === null) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({
        x,
        y,
        minute: point.minute,
        time: point.sim_time || point.time,
        sim_time: point.sim_time || point.time,
        value,
      });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else if (series.key === "control") {
        ctx.lineTo(x, previousY);
        if (Math.abs(y - previousY) > 1e-9) ctx.lineTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      previousY = y;
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit, points: pixelPoints });
  };
  const unit = points.find((point) => point.unit)?.unit || "";
  visibleSeries.forEach((series) => drawSeries(series, series.key === "scada" ? 2 : 2.5));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    timeLabel: (point) => runtimeTracePointTimeLabel(point, range),
    valueFormatter: formatMeasurementValue,
  });
  ctx.fillStyle = palette.text;
  ctx.textAlign = "left";
  ctx.fillText(formatMeasurementValue(maxValue), 8, top + 4);
  ctx.fillText(formatMeasurementValue(minValue), 8, bottom);
  if (unit) ctx.fillText(unit, left, 18);
}

function renderRuntimeMonitor(force = false) {
  const activeEditor = document.activeElement?.closest?.("#runtimeTraceWindow");
  renderRuntimeDeviceTree();
  renderRuntimeDeviceTable();
  if (force || !activeEditor) drawRuntimeTraceChart();
}

