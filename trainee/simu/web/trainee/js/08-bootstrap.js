// 学员端模块：人工遥控遥调弹窗、防抖搜索、快捷键与启动装配（08-bootstrap.js）
function findDeviceByKey(key) {
  const [devType = "", devName = ""] = String(key || "").split("|");
  return controlDefinitionDevices().find((dev) => deviceKey(dev) === `${devType}|${devName}`)
    || null;
}

function diagramDeviceCommandContext(container, devId, snapshot = state.snapshot || {}) {
  const record = diagramDeviceRecord(container, devId);
  if (!record) return null;
  const dev = controlDefinitionDevices(snapshot).find((candidate) => (
    deviceType(candidate) === record.devType
    && deviceName(candidate) === record.devName
  )) || null;
  const remoteControls = dev ? remoteControlCommandRows([dev], snapshot) : [];
  const adjustments = dev ? diagramDeviceAdjustmentRows(dev, snapshot) : [];
  return {
    container,
    devId: record.devId,
    record,
    dev,
    options: [
      ...remoteControls.map((row) => ({ kind: "remote-control", row })),
      ...adjustments.map((row) => ({ kind: "remote-adjustment", row })),
    ],
  };
}

function diagramDeviceAdjustmentRows(dev, snapshot = state.snapshot || {}) {
  const bindings = Array.isArray(dev?.control_bindings) ? dev.control_bindings : [];
  if (!bindings.length) return remoteAdjustmentRows([dev], snapshot);
  const couplingControlSetType = {
    P: "p_set",
    FLOW: "flow_set",
  }[String(dev?.mode ?? dev?.raw?.control_type ?? "").trim().toUpperCase()] || "";
  const controlDevices = controlDefinitionDevices(snapshot);
  return bindings.flatMap((binding) => {
    const bindingSetType = String(binding?.set_type || binding?.target_set_type || "");
    const bindingIsActive = typeof binding?.active === "boolean"
      ? binding.active
      : Boolean(couplingControlSetType && bindingSetType === couplingControlSetType);
    if (!bindingIsActive) return [];
    const targetType = String(binding?.target_dev_type || "");
    const targetName = String(binding?.target_dev_name || "");
    const targetSetType = String(binding?.target_set_type || binding?.set_type || "");
    const target = controlDevices.find((candidate) => (
      deviceType(candidate) === targetType
      && deviceName(candidate) === targetName
    ));
    if (!target) return [];
    return remoteAdjustmentRows([target], snapshot).filter(
      (row) => row.setType === targetSetType,
    );
  });
}

function closeDiagramDeviceCommandDialog() {
  const dialog = $("diagramDeviceCommandDialog");
  if (dialog?.open) dialog.close();
  state.diagramDeviceCommandContext = null;
}

function diagramDeviceCommandOptionMarkup(option, index) {
  const row = option?.row || {};
  const isRemoteControl = option?.kind === "remote-control";
  const currentValue = isRemoteControl
    ? remoteControlValueText(row.commandType, row.dev?.[row.valueKey])
    : formatRemoteAdjustmentValue(row.controlValue);
  const detail = isRemoteControl
    ? `当前状态：${currentValue}`
    : `当前控制值：${currentValue}；量测值：${formatRemoteAdjustmentValue(row.measurement)}`;
  return `
    <button class="diagram-device-command-option" type="button" data-diagram-device-command-index="${index}">
      <span class="diagram-device-command-option-main">
        <strong>${escapeHtml(row.name || "设备操作")}</strong>
        <small>${escapeHtml(detail)}</small>
      </span>
      <span class="diagram-device-command-option-type">${isRemoteControl ? "遥控" : "遥调"}</span>
    </button>
  `;
}

function openDiagramDeviceCommandDialog(context) {
  const dialog = $("diagramDeviceCommandDialog");
  if (!dialog || !context) return;
  state.diagramDeviceCommandContext = context;
  $("diagramDeviceCommandTitle").textContent = "设备人工操作";
  $("diagramDeviceCommandDevice").textContent = context.record.devName || context.record.devId || "--";
  $("diagramDeviceCommandType").textContent = `${context.record.devType || "--"} / ${context.record.devId || "--"}`;
  $("diagramDeviceCommandList").innerHTML = context.options
    .map((option, index) => diagramDeviceCommandOptionMarkup(option, index))
    .join("");
  $("diagramDeviceCommandHint").textContent = context.options.length
    ? "请选择要执行的人工遥控或遥调操作。"
    : "当前设备未配置遥控或遥调点";
  $("diagramDeviceCommandHint").className = context.options.length
    ? "remote-control-hint"
    : "remote-control-hint is-error";
  if (!dialog.open) dialog.showModal();
}

function refreshDiagramDeviceCommandDialog(snapshot = state.snapshot || {}) {
  const dialog = $("diagramDeviceCommandDialog");
  const context = state.diagramDeviceCommandContext;
  if (!dialog?.open || !context) return;
  const refreshedContext = diagramDeviceCommandContext(context.container, context.devId, snapshot);
  if (!refreshedContext) {
    closeDiagramDeviceCommandDialog();
    return;
  }
  openDiagramDeviceCommandDialog(refreshedContext);
}

function activateDiagramDeviceCommandOption(option) {
  if (!option?.row) return;
  if (option.kind === "remote-control") {
    openRemoteControlDialog(option.row.dev, option.row.commandType);
    return;
  }
  if (option.kind === "remote-adjustment") openRemoteAdjustmentDialog(option.row);
}

function openDiagramDeviceCommandForSvgDevice(container, devId) {
  const context = diagramDeviceCommandContext(container, devId, state.snapshot || {});
  if (!context) return;
  setDiagramSelectedDevice(container, context.devId);
  if (context.options.length === 1) {
    activateDiagramDeviceCommandOption(context.options[0]);
    return;
  }
  openDiagramDeviceCommandDialog(context);
}

function closeRemoteControlDialog() {
  const dialog = $("remoteControlDialog");
  if (dialog?.open) dialog.close();
  state.remoteControlDevice = null;
  state.remoteControlSending = false;
}

function updateRemoteControlDialogSummary(dev, commandType = dev?.__command_type || "run_stat") {
  if (!dev) return 0;
  state.remoteControlDevice = { ...dev, __command_type: commandType };
  const valueKey = commandType === "status" ? "status" : "run_stat";
  const currentRun = Number(dev[valueKey]) ? 1 : 0;
  $("remoteControlDevice").textContent = deviceName(dev);
  $("remoteControlType").textContent = `${deviceType(dev)} / ${remoteControlLabel(commandType)}`;
  $("remoteControlCurrent").innerHTML = `<span class="status-pill ${currentRun ? "is-ok" : "is-off"}">${remoteControlValueText(commandType, currentRun)}</span>`;
  return currentRun;
}

function refreshRemoteControlDialog(snapshot = state.snapshot || {}) {
  const dialog = $("remoteControlDialog");
  const current = state.remoteControlDevice;
  if (!dialog?.open || !current) return;
  const commandType = current.__command_type === "status" ? "status" : "run_stat";
  const key = `${deviceKey(current)}|${commandType}`;
  const refreshed = remoteControlCommandRows(controlDefinitionDevices(snapshot), snapshot)
    .find((row) => row.key === key);
  if (!refreshed) {
    closeRemoteControlDialog();
    return;
  }
  updateRemoteControlDialogSummary(refreshed.dev, commandType);
}

function openRemoteControlDialog(dev, commandType = dev?.__command_type || "run_stat") {
  const dialog = $("remoteControlDialog");
  if (!dialog || !dev) return;
  state.remoteControlSending = false;
  const currentRun = updateRemoteControlDialogSummary(dev, commandType);
  $("remoteControlHint").textContent = "确认后将立即向模拟台下发遥控指令。";
  $("remoteControlHint").className = "remote-control-hint";
  document.querySelectorAll('input[name="remoteControlState"]').forEach((input) => {
    input.checked = Number(input.value) === (currentRun ? 0 : 1);
    const label = input.closest("label");
    const strong = label?.querySelector("strong");
    const small = label?.querySelector("small");
    if (strong) strong.textContent = remoteControlValueText(commandType, Number(input.value));
    if (small) small.textContent = commandType === "status"
      ? (Number(input.value) ? "闭合开关或断路器" : "断开开关或断路器")
      : (Number(input.value) ? "使设备进入运行状态" : "使设备退出运行状态");
  });
  $("remoteControlConfirm").disabled = false;
  $("remoteControlConfirm").textContent = "确认下发";
  if (!dialog.open) dialog.showModal();
}

function remoteControlCommandAcceptance(result = {}) {
  const submission = commandSubmissionQueueState(result, "run_status");
  if (submission.queued > 0 || submission.blocked.length) {
    return { ...submission, ready: false };
  }
  return { accepted: submission.accepted, ignored: submission.ignored, ok: submission.ok };
}

function commandSubmissionQueueState(result = {}, acceptedField = "run_status") {
  const wrapped = result?.accepted && typeof result.accepted === "object" ? result.accepted : {};
  const alias = acceptedField === "set_values" ? wrapped.remote_adjustments : wrapped.remote_controls;
  const acceptedValue = result?.[acceptedField] ?? wrapped[acceptedField] ?? alias ?? 0;
  const ignoredValue = result?.ignored ?? wrapped.ignored ?? 0;
  const blocked = Array.isArray(result?.blocked)
    ? result.blocked
    : (Array.isArray(wrapped.blocked) ? wrapped.blocked : []);
  const queuedValue = result?.queued ?? wrapped.queued ?? blocked.length;
  const accepted = Number.isFinite(Number(acceptedValue)) ? Math.max(0, Number(acceptedValue)) : 0;
  const ignored = Number.isFinite(Number(ignoredValue)) ? Math.max(0, Number(ignoredValue)) : 0;
  const queued = Number.isFinite(Number(queuedValue)) ? Math.max(0, Number(queuedValue)) : 0;
  const receivedBy = String(
    result?.received_by ?? wrapped.received_by ?? (accepted > 0 ? "simulator" : ""),
  ).trim().toLowerCase();
  const receiveState = String(
    result?.receive_state ?? wrapped.receive_state ?? (accepted > 0 ? "completed" : ""),
  ).trim().toLowerCase();
  const queueOwner = String(
    result?.queue_owner ?? wrapped.queue_owner ?? (queued > 0 ? "simulator" : ""),
  ).trim().toLowerCase();
  const queueState = String(
    result?.queue_state ?? wrapped.queue_state ?? (queued > 0 ? "waiting" : ""),
  ).trim().toLowerCase();
  return {
    accepted,
    ignored,
    queued,
    receivedBy,
    receiveState,
    queueOwner,
    queueState,
    blocked,
    ok: accepted > 0 && ignored === 0,
  };
}

function queuedCommandMessage(submission = {}) {
  const backendMessage = String(
    submission?.blocked?.find((item) => String(item?.message || "").trim())?.message || "",
  ).trim();
  const ownerMessage = "模拟台已接管该指令并负责后台等待；学员台不保存等待任务。";
  return backendMessage ? `${ownerMessage}${backendMessage}` : ownerMessage;
}

function remoteControlFeedbackSnapshotPath() {
  const params = new URLSearchParams({
    lite: "1",
    static: "0",
    logs: "0",
    measurements: "0",
    devices: "1",
    device_states: "0",
    commands: "0",
  });
  return `/api/trainee/snapshot?${params.toString()}`;
}

async function waitForRemoteControlFeedback(dev, commandType, targetValue, attempts = 4) {
  let latestSnapshot = null;
  let currentValue = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    latestSnapshot = await api(remoteControlFeedbackSnapshotPath());
    currentValue = remoteControlFeedbackValue(dev, commandType, latestSnapshot);
    if (currentValue === (Number(targetValue) ? 1 : 0)) {
      return { confirmed: true, value: currentValue, snapshot: latestSnapshot };
    }
    if (attempt + 1 < attempts) {
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
  }
  return { confirmed: false, value: currentValue, snapshot: latestSnapshot };
}

async function sendRemoteControlCommand() {
  const dev = state.remoteControlDevice;
  if (!dev || state.remoteControlSending) return;
  const selected = document.querySelector('input[name="remoteControlState"]:checked');
  if (!(selected instanceof HTMLInputElement)) return;
  const commandType = dev.__command_type === "status" ? "status" : "run_stat";
  const command = {
    dev_type: deviceType(dev),
    dev_name: deviceName(dev),
  };
  command[commandType] = Number(selected.value) ? 1 : 0;
  const requestedText = remoteControlValueText(commandType, command[commandType]);
  const body = withCommandSendTime({
    source: "trainee-ui",
    ...manualCommandHoldPayload(),
    run_status: [command],
    set_values: [],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  if (remoteControlTargetAlreadyReached(dev, commandType, command[commandType], state.snapshot || {})) {
    $("remoteControlConfirm").disabled = false;
    $("remoteControlConfirm").textContent = "重新选择";
    $("remoteControlHint").textContent = `${deviceName(dev)} 当前已经是${requestedText}，未重复下发。`;
    $("remoteControlHint").className = "remote-control-hint is-warn";
    addRuntimeLog(
      "人工遥控",
      targetName,
      "未下发",
      `${deviceName(dev)} 当前已经是${requestedText}，目标状态没有变化`,
      "warn",
    );
    return;
  }
  state.remoteControlSending = true;
  $("remoteControlConfirm").disabled = true;
  $("remoteControlConfirm").textContent = "下发中";
  $("remoteControlHint").textContent = `${deviceName(dev)}：${requestedText}`;
  addRuntimeLog("人工遥控", targetName, "下发请求", `${deviceName(dev)} → ${requestedText}`);
  try {
    const result = await postTeacherCommand(body);
    const acceptance = remoteControlCommandAcceptance(result);
    if (!acceptance.ok) {
      throw new Error(`模拟台未接受遥控指令：接受 ${acceptance.accepted} 条，忽略 ${acceptance.ignored} 条`);
    }
    addRuntimeLog(
      "人工遥控",
      targetName,
      "下发完成",
      `${deviceName(dev)} → ${requestedText}；模拟台接收完成；接受 ${acceptance.accepted} 条`,
      "ok",
    );
    if (acceptance.queued > 0) {
      const queueMessage = queuedCommandMessage(acceptance);
      pending.run_status.delete(`${deviceKey(dev)}|${commandType}`);
      updatePendingCount();
      await refresh();
      $("remoteControlHint").textContent = queueMessage;
      $("remoteControlHint").className = "remote-control-hint is-warn";
      addRuntimeLog(
        "模拟台响应",
        targetName,
        "接收完成，模拟台排队",
        `${deviceName(dev)} → ${requestedText}；${queueMessage}`,
        "warn",
      );
      closeRemoteControlDialog();
      return;
    }
    const feedback = await waitForRemoteControlFeedback(dev, commandType, command[commandType]);
    if (feedback.snapshot) {
      state.snapshot = mergeTeacherSnapshotWithLocalDefinitions(state.snapshot, feedback.snapshot);
      renderSnapshot(state.snapshot);
    }
    pending.run_status.delete(`${deviceKey(dev)}|${commandType}`);
    updatePendingCount();
    await refresh();
    addRuntimeLog(
      "模拟台响应",
      targetName,
      feedback.confirmed ? "接收完成，遥控生效" : "接收完成，待状态反馈",
      feedback.confirmed
        ? `${deviceName(dev)} → ${requestedText}；模拟台状态反馈已一致`
        : `${deviceName(dev)} → ${requestedText}；接受 ${acceptance.accepted} 条，但状态反馈尚未到位`,
      feedback.confirmed ? "ok" : "warn",
    );
    closeRemoteControlDialog();
  } catch (error) {
    state.remoteControlSending = false;
    $("remoteControlConfirm").disabled = false;
    $("remoteControlConfirm").textContent = "重新下发";
    $("remoteControlHint").textContent = apiErrorText(error);
    $("remoteControlHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥控失败", apiErrorText(error), "error");
  }
}

function findRemoteAdjustmentByKey(key, snapshot = state.snapshot || {}) {
  return remoteAdjustmentRows(controlDefinitionDevices(snapshot), snapshot).find((row) => row.key === key) || null;
}

function closeRemoteAdjustmentDialog() {
  const dialog = $("remoteAdjustmentDialog");
  if (dialog?.open) dialog.close();
  state.remoteAdjustment = null;
  state.remoteAdjustmentSending = false;
}

function updateRemoteAdjustmentDialogSummary(row) {
  if (!row) return;
  state.remoteAdjustment = row;
  $("remoteAdjustmentName").textContent = row.name;
  $("remoteAdjustmentDevice").textContent = `${deviceType(row.dev)} / ${deviceName(row.dev)}`;
  $("remoteAdjustmentMeasurement").textContent = formatRemoteAdjustmentValue(row.measurement);
  $("remoteAdjustmentCurrent").textContent = formatRemoteAdjustmentValue(row.controlValue);
  $("remoteAdjustmentIssuedAt").textContent = row.issuedTime?.wall_time || row.issuedAt || "--";
  if ($("remoteAdjustmentIssuedSimAt")) {
    $("remoteAdjustmentIssuedSimAt").textContent = row.issuedTime?.simu_time || "--";
  }
}

function refreshRemoteAdjustmentDialog(snapshot = state.snapshot || {}) {
  const dialog = $("remoteAdjustmentDialog");
  const current = state.remoteAdjustment;
  if (!dialog?.open || !current) return;
  const refreshed = findRemoteAdjustmentByKey(current.key, snapshot);
  if (!refreshed) {
    closeRemoteAdjustmentDialog();
    return;
  }
  updateRemoteAdjustmentDialogSummary(refreshed);
}

function openRemoteAdjustmentDialog(row) {
  const dialog = $("remoteAdjustmentDialog");
  if (!dialog || !row) return;
  state.remoteAdjustmentSending = false;
  updateRemoteAdjustmentDialogSummary(row);
  $("remoteAdjustmentValue").value = row.controlValue === null || row.controlValue === undefined ? "" : row.controlValue;
  $("remoteAdjustmentHint").textContent = "确认后将立即向模拟台下发一条遥调指令。";
  $("remoteAdjustmentHint").className = "remote-control-hint";
  $("remoteAdjustmentConfirm").disabled = false;
  $("remoteAdjustmentConfirm").textContent = "确认下发";
  dialog.showModal();
  $("remoteAdjustmentValue").focus();
  $("remoteAdjustmentValue").select();
}

async function sendRemoteAdjustmentCommand() {
  const row = state.remoteAdjustment;
  if (!row || state.remoteAdjustmentSending) return;
  const rawInput = String($("remoteAdjustmentValue")?.value ?? "").trim();
  const setValue = Number(rawInput);
  if (!rawInput || !Number.isFinite(setValue)) {
    $("remoteAdjustmentHint").textContent = "请输入有效的控制值（不能为空）。";
    $("remoteAdjustmentHint").className = "remote-control-hint is-error";
    return;
  }
  const command = {
    dev_type: deviceType(row.dev),
    dev_name: deviceName(row.dev),
    set_type: row.setType,
    set_value: setValue,
  };
  const body = withCommandSendTime({
    source: "trainee-ui",
    ...manualCommandHoldPayload(),
    run_status: [],
    set_values: [command],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  state.remoteAdjustmentSending = true;
  $("remoteAdjustmentConfirm").disabled = true;
  $("remoteAdjustmentConfirm").textContent = "下发中";
  $("remoteAdjustmentHint").textContent = `${row.name}：${formatNumber(setValue)}`;
  addRuntimeLog("人工遥调", targetName, "下发请求", `${row.name} → ${formatNumber(setValue)}`);
  try {
    const result = await postTeacherCommand(body);
    const submission = commandSubmissionQueueState(result, "set_values");
    if (!submission.ok) {
      throw new Error(`模拟台未接受遥调指令：接受 ${submission.accepted} 条，忽略 ${submission.ignored} 条`);
    }
    addRuntimeLog(
      "人工遥调",
      targetName,
      "下发完成",
      `${row.name} → ${formatNumber(setValue)}；模拟台接收完成；接受 ${submission.accepted} 条`,
      "ok",
    );
    if (submission.queued > 0) {
      const queueMessage = queuedCommandMessage(submission);
      pending.set_values.delete(row.key);
      updatePendingCount();
      addRuntimeLog(
        "模拟台响应",
        targetName,
        "接收完成，模拟台排队",
        `${row.name} → ${formatNumber(setValue)}；${queueMessage}`,
        "warn",
      );
      await refresh();
      closeRemoteAdjustmentDialog();
      return;
    }
    addRuntimeLog(
      "模拟台响应",
      targetName,
      "接收完成，遥调生效",
      `${row.name} → ${formatNumber(setValue)}；接受 ${result.set_values || 0} 条`,
      "ok",
    );
    pending.set_values.delete(row.key);
    updatePendingCount();
    await refresh();
    closeRemoteAdjustmentDialog();
  } catch (error) {
    state.remoteAdjustmentSending = false;
    $("remoteAdjustmentConfirm").disabled = false;
    $("remoteAdjustmentConfirm").textContent = "重新下发";
    $("remoteAdjustmentHint").textContent = apiErrorText(error);
    $("remoteAdjustmentHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥调失败", apiErrorText(error), "error");
  }
}

function handleTreeClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const button = target.closest("[data-model-tree-type], [data-measurement-tree-type], [data-control-tree-type]");
  if (!button) return;
  event.preventDefault();
  const toggleScope = button.dataset.treeToggleScope;
  const toggleGroup = button.dataset.treeToggleGroup || "";
  const selection =
    button.dataset.modelTreeType !== undefined
      ? ["modelFilter", button.dataset.modelTreeType, button.dataset.modelTreeName || ""]
      : button.dataset.measurementTreeType !== undefined
      ? ["measurementFilter", button.dataset.measurementTreeType, button.dataset.measurementTreeName || ""]
      : button.dataset.controlTreeType !== undefined
        ? ["controlFilter", button.dataset.controlTreeType, button.dataset.controlTreeName || ""]
          : null;
  requestAnimationFrame(() => {
    if (toggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) toggleDeviceTreeGroup(toggleScope, toggleGroup);
    if (selection?.[0] === "modelFilter") setTraineeModelFilter(selection[1], selection[2], event, button);
    else if (selection) selectTreeFilter(selection[0], selection[1], selection[2], event, button, selection[0] === "measurementFilter" ? "measurement" : "control");
  });
}

function handleTraineeTableFilterControl(target) {
  if (!(target instanceof Element)) return false;
  const control = target.closest("[data-table-filter-scope]");
  if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return false;
  const scope = control.dataset.tableFilterScope || "";
  const field = control.dataset.tableFilterField || "";
  if (scope === "measurement") {
    if (field === "type") state.measurementTypeFilter = control.value || "all";
    else state.measurementKeywordFilter = control.value || "";
    renderMeasurements(state.snapshot || {});
    drawMeasurementTraceChart();
    return true;
  }
  if (scope === "command") {
    if (field === "type") state.commandTypeFilter = control.value || "all";
    else if (field === "origin") state.commandOriginFilter = control.value || "all";
    else state.commandKeywordFilter = control.value || "";
    renderCombinedControlPage();
    drawCommandTraceChart();
    return true;
  }
  return false;
}

const debouncedTraineeSearchFilter = debounce((target) => {
  if (!(target instanceof Element)) return;
  if (handleTraineeTableFilterControl(target)) return;
  if (target.id === "curveDisplayTreeFilter") {
    state.curveDisplayTreeSearch = target.value || "";
    renderCurveDisplayTree(state.snapshot || {});
    return;
  }
  const input = target.closest?.("[data-device-tree-filter-scope]");
  if (!input) return;
  const scope = input.dataset.deviceTreeFilterScope || "";
  state.deviceTreeSearch[scope] = input.value || "";
  refreshDeviceTreeFilterScope(scope);
}, 150);

let traineeSearchComposing = false;
document.addEventListener("compositionstart", (event) => {
  if (event.target instanceof HTMLInputElement && event.target.type === "search") {
    traineeSearchComposing = true;
  }
});
document.addEventListener("compositionend", (event) => {
  if (event.target instanceof HTMLInputElement && event.target.type === "search") {
    traineeSearchComposing = false;
    debouncedTraineeSearchFilter(event.target);
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target instanceof HTMLInputElement && target.type === "search") {
    if (traineeSearchComposing) return;
    debouncedTraineeSearchFilter(target);
    return;
  }
  if (handleTraineeTableFilterControl(target)) return;
  if (target.id === "curveDisplayTreeFilter") {
    state.curveDisplayTreeSearch = target.value || "";
    renderCurveDisplayTree(state.snapshot || {});
    return;
  }
  const input = target.closest?.("[data-device-tree-filter-scope]");
  if (!input) return;
  const scope = input.dataset.deviceTreeFilterScope || "";
  state.deviceTreeSearch[scope] = input.value || "";
  refreshDeviceTreeFilterScope(scope);
});
document.addEventListener("change", (event) => {
  if (!(event.target instanceof Element)) return;
  const target = event.target;
  const onlyActiveToggle = target.closest("#commandOnlyActive");
  if (!(onlyActiveToggle instanceof HTMLInputElement)) return;
  state.commandOnlyActive = onlyActiveToggle.checked;
  syncCommandOnlyActiveControl();
  renderCombinedControlPage();
});
document.addEventListener("scroll", handleVirtualTableScroll, true);

document.addEventListener("click", (event) => {
  handleTreeClick(event);
  const target = event.target instanceof Element ? event.target : null;
  const chartToggle = target?.closest("[data-chart-toggle][data-chart-series]");
  if (chartToggle) {
    if (chartToggle.matches('input[type="checkbox"]')) return;
    event.preventDefault();
    const chartKey = chartToggle.dataset.chartToggle || "";
    const seriesKey = chartToggle.dataset.chartSeries || "";
    const drawFn = chartKey === "measurementTrace" ? drawMeasurementTraceChart
      : chartKey === "commandTrace" ? drawCommandTraceChart
        : chartKey === "renewableTrend" ? drawRenewableTrendChart
          : null;
    if (chartToggle.dataset.chartLegendVisibility === "true") {
      toggleChartLegendSeriesVisibility(chartKey, seriesKey, drawFn);
    } else {
      toggleChartSeriesVisibility(chartKey, seriesKey, drawFn);
    }
    return;
  }
  if (target?.closest("#clearRuntimeLogs")) {
    event.preventDefault();
    clearTraineeRuntimeLogs();
    return;
  }
  const modelParamTab = target?.closest("[data-model-param-tab]");
  if (modelParamTab) {
    requestAnimationFrame(() => {
      state.activeModelParamTab = modelParamTab.dataset.modelParamTab || "";
      renderTraineeModelParamTable();
    });
  }
  const curveDisplayButton = target?.closest("[data-curve-display-tree-type]");
  const curveDisplayTreeToggle = target?.closest("[data-curve-display-tree-toggle]");
  if (curveDisplayTreeToggle) {
    event.preventDefault();
    event.stopPropagation();
    requestAnimationFrame(() => {
      toggleCurveDisplayTreeGroup(curveDisplayTreeToggle.dataset.curveDisplayTreeToggle || "");
    });
    return;
  }
  if (curveDisplayButton) {
    event.preventDefault();
    const selectionEvent = { ctrlKey: event.ctrlKey, metaKey: event.metaKey, shiftKey: event.shiftKey };
    requestAnimationFrame(() => selectCurveDisplayButton(curveDisplayButton, selectionEvent));
    return;
  }
  const commandTab = target?.closest("[data-command-tab]");
  if (commandTab) {
    state.activeControlTab = commandTab.dataset.commandTab || "remote-control";
    ensureSelectedCommandTrace(controlDefinitionDevices());
    renderCombinedControlPage();
    return;
  }
  const commandCancelButton = target?.closest("[data-command-cancel-name]");
  if (commandCancelButton) {
    event.preventDefault();
    event.stopPropagation();
    const commandName = commandCancelButton.dataset.commandCancelName || "";
    const commandLabel = commandCancelButton.dataset.commandCancelLabel || commandName;
    const commandOrigin = commandCancelButton.dataset.commandCancelOrigin || "manual";
    sendCommandCancel(commandName, commandLabel, commandOrigin);
    return;
  }
  const commandTraceRow = target?.closest("[data-command-trace-key]");
  if (commandTraceRow) {
    selectCommandTraceRow(commandTraceRow);
    return;
  }
  const measurementTab = target?.closest("[data-measurement-tab]");
  if (measurementTab) {
    setMeasurementTab(measurementTab.dataset.measurementTab || "telemetry");
    return;
  }
  const measurementRow = target?.closest("[data-measurement-select-key]");
  if (measurementRow) {
    const key = measurementRow.dataset.measurementSelectKey || "";
    requestAnimationFrame(() => {
      state.selectedMeasurementKey = key;
      renderMeasurements(state.snapshot || {});
      ensureSelectedMeasurementHistory();
    });
  }
});

document.addEventListener("dblclick", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const adjustmentRow = target?.closest("[data-remote-adjustment-key]");
  if (adjustmentRow) {
    event.preventDefault();
    const adjustment = findRemoteAdjustmentByKey(adjustmentRow.dataset.remoteAdjustmentKey || "");
    if (adjustment) openRemoteAdjustmentDialog(adjustment);
    return;
  }
  const statusCell = target?.closest("[data-run-status-command]");
  if (!statusCell) return;
  event.preventDefault();
  const commandKey = statusCell.dataset.runStatusCommand || "";
  const dev = findDeviceByKey(statusCell.dataset.runStatusCommand || "");
  const commandType = commandKey.split("|")[2] || "run_stat";
  if (dev) {
    dev.__command_type = commandType;
    openRemoteControlDialog(dev);
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  if (handleTraineeTableFilterControl(target)) return;
  const runKey = target.dataset.runKey;
  if (runKey) {
    const [dev_type, dev_name, commandType = "run_stat"] = runKey.split("|");
    const item = { dev_type, dev_name };
    item[commandType === "status" ? "status" : "run_stat"] = target.checked ? 1 : 0;
    pending.run_status.set(runKey, item);
    updatePendingCount();
    renderRunControls(controlDefinitionDevices());
    drawCommandTraceChart();
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const setKey = target.dataset.setKey;
  if (setKey) {
    const [dev_type, dev_name] = setKey.split("|");
    const set_type = target.dataset.setType;
    const entryKey = `${setKey}|${set_type}`;
    const rawValue = String(target.value ?? "").trim();
    const parsed = Number(rawValue);
    if (!rawValue || !Number.isFinite(parsed)) {
      pending.set_values.delete(entryKey);
      target.classList.remove("is-pending");
    } else {
      pending.set_values.set(entryKey, {
        dev_type,
        dev_name,
        set_type,
        set_value: parsed,
      });
      target.classList.add("is-pending");
    }
    updatePendingCount();
    drawCommandTraceChart();
  }
});

async function toggleReceiveMode() {
  if (state.receiveMode) {
    try {
      await setTraineeReceiveActive(state.activeModelId, false);
    } catch (error) {
      addRuntimeLog("接收模式", "学员台服务端", "停止接收失败", apiErrorText(error), "warn");
      renderReceiveMode(apiErrorText(error));
      return;
    }
    state.receiveMode = false;
    state.frozen = true;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    state.receiveRequestActive = false;
    persistActiveModelContext({ receiveMode: false, frozen: true }, true);
    addRuntimeLog("接收模式", "模拟台实时数据", "停止接收", `冻结于 ${state.lastReceiveAt || "--"}`, "warn");
    noteRenewableReceiveInterruption("连续接收已停止，新能源实时控制已暂停，接收恢复后将自动恢复。");
    renderReceiveMode();
    return;
  }
  await startReceiveMode();
}

$("modelManagementButton").addEventListener("click", openModelManagementDialog);
$("closeModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("cancelModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("modelManagementDialog").addEventListener("click", (event) => {
  if (event.target === $("modelManagementDialog")) closeModelManagementDialog();
});
$("modelManagementList").addEventListener("click", handleModelManagementAction);
$("modelManagementList").addEventListener("keydown", handleModelManagementKeydown);
$("modelManagementList").addEventListener("contextmenu", openModelContextMenu);
$("modelManagementList").addEventListener("scroll", closeModelContextMenu);
$("modelContextMenu").addEventListener("click", handleModelContextMenuAction);
document.addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("#modelContextMenu")) return;
  closeModelContextMenu();
});
$("newModelButton").addEventListener("click", openNewModelDialog);
$("closeNewModelDialog").addEventListener("click", closeNewModelDialog);
$("cancelNewModel").addEventListener("click", closeNewModelDialog);
$("newModelDialog").addEventListener("click", (event) => {
  if (event.target === $("newModelDialog")) closeNewModelDialog();
});
$("newModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createNewModelSlot();
});
$("newModelName").addEventListener("input", () => validateNewModelForm());
$("closeCloneModelDialog").addEventListener("click", closeCloneModelDialog);
$("cancelCloneModel").addEventListener("click", closeCloneModelDialog);
$("cloneModelDialog").addEventListener("click", (event) => {
  if (event.target === $("cloneModelDialog")) closeCloneModelDialog();
});
$("cloneModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  cloneManagedModel();
});
$("cloneModelName").addEventListener("input", () => validateCloneModelName());
$("modelInitializeButton").addEventListener("click", openReceiveLinkDialog);
$("traineeRunToggle").addEventListener("click", toggleReceiveMode);
$("receiveLinkClose").addEventListener("click", closeReceiveLinkDialog);
$("receiveLinkCancel").addEventListener("click", closeReceiveLinkDialog);
$("confirmReceiveLink").addEventListener("click", initializeModelFromLink);
$("receiveLinkDialog").addEventListener("click", (event) => {
  if (event.target === $("receiveLinkDialog")) closeReceiveLinkDialog();
});
$("receiveWarningClose").addEventListener("click", closeReceiveWarningDialog);
$("receiveWarningConfirm").addEventListener("click", closeReceiveWarningDialog);
$("receiveWarningDialog").addEventListener("click", (event) => {
  if (event.target === $("receiveWarningDialog")) closeReceiveWarningDialog();
});
$("diagramDeviceCommandClose").addEventListener("click", closeDiagramDeviceCommandDialog);
$("diagramDeviceCommandCancel").addEventListener("click", closeDiagramDeviceCommandDialog);
$("diagramDeviceCommandDialog").addEventListener("click", (event) => {
  if (event.target === $("diagramDeviceCommandDialog")) closeDiagramDeviceCommandDialog();
});
$("diagramDeviceCommandDialog").addEventListener("close", () => {
  state.diagramDeviceCommandContext = null;
});
$("diagramDeviceCommandList").addEventListener("click", (event) => {
  const button = event.target instanceof Element
    ? event.target.closest("[data-diagram-device-command-index]")
    : null;
  if (!button) return;
  const index = Number(button.dataset.diagramDeviceCommandIndex);
  const option = state.diagramDeviceCommandContext?.options?.[index];
  if (option) activateDiagramDeviceCommandOption(option);
});
$("remoteControlClose").addEventListener("click", closeRemoteControlDialog);
$("remoteControlCancel").addEventListener("click", closeRemoteControlDialog);
$("remoteControlConfirm").addEventListener("click", sendRemoteControlCommand);
$("remoteControlDialog").addEventListener("click", (event) => {
  if (event.target === $("remoteControlDialog")) closeRemoteControlDialog();
});
$("remoteAdjustmentClose").addEventListener("click", closeRemoteAdjustmentDialog);
$("remoteAdjustmentCancel").addEventListener("click", closeRemoteAdjustmentDialog);
$("remoteAdjustmentConfirm").addEventListener("click", sendRemoteAdjustmentCommand);
$("remoteAdjustmentDialog").addEventListener("click", (event) => {
  if (event.target === $("remoteAdjustmentDialog")) closeRemoteAdjustmentDialog();
});
$("renewableAutoToggle").addEventListener("click", toggleRenewableAuto);
$("renewableSendOnce").addEventListener("click", runRenewableControlOnce);
$("renewableControlParametersButton")?.addEventListener("click", openRenewableControlParametersDialog);
$("closeRenewableControlParametersDialog")?.addEventListener("click", closeRenewableControlParametersDialog);
$("cancelRenewableControlParametersDialog")?.addEventListener("click", closeRenewableControlParametersDialog);
$("saveRenewableControlParameters")?.addEventListener("click", saveRenewableControlParameters);
$("renewableControlPeriod")?.addEventListener("input", syncRenewableControlPeriodConstraints);
$("renewableControlParametersDialog")?.addEventListener("cancel", (event) => {
  // This editor contains many values. Keep unsaved edits until the user explicitly closes it.
  event.preventDefault();
});
const renewableControlLogTable = $("renewableControlLogTable");
renewableControlLogTable?.addEventListener("click", (event) => {
  const row = event.target.closest("[data-renewable-log-seq]");
  if (!row) return;
  selectRenewableControlLogRow(row.dataset.renewableLogSeq);
});
renewableControlLogTable?.addEventListener("dblclick", (event) => {
  const row = event.target.closest("[data-renewable-log-seq]");
  if (!row) return;
  openRenewableControlLogDetailDialog(row.dataset.renewableLogSeq);
});
renewableControlLogTable?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const row = event.target.closest("[data-renewable-log-seq]");
  if (!row) return;
  event.preventDefault();
  openRenewableControlLogDetailDialog(row.dataset.renewableLogSeq);
});
$("closeRenewableControlLogDetailDialog")?.addEventListener("click", closeRenewableControlLogDetailDialog);
$("confirmRenewableControlLogDetailDialog")?.addEventListener("click", closeRenewableControlLogDetailDialog);
$("renewableControlLogDetailDialog")?.addEventListener("click", (event) => {
  if (event.target === $("renewableControlLogDetailDialog")) closeRenewableControlLogDetailDialog();
});
$("storagePowerDeratingButton")?.addEventListener("click", openStoragePowerDeratingDialog);
$("closeStoragePowerDeratingDialog")?.addEventListener("click", closeStoragePowerDeratingDialog);
$("cancelStoragePowerDerating")?.addEventListener("click", closeStoragePowerDeratingDialog);
$("resetStoragePowerDerating")?.addEventListener("click", resetStoragePowerDeratingCurves);
$("saveStoragePowerDerating")?.addEventListener("click", saveStoragePowerDeratingCurves);
$("storagePowerDeratingDialog")?.addEventListener("click", (event) => {
  if (event.target === $("storagePowerDeratingDialog")) closeStoragePowerDeratingDialog();
});
$("storagePowerDeratingDialog")?.addEventListener("input", () => {
  setStoragePowerDeratingMessage("相邻 SOC 节点之间自动进行线性插值。", "");
});
document.querySelectorAll("[data-renewable-loop-mode]").forEach((button) => {
  button.addEventListener("click", () => setRenewableLoopMode(button.dataset.renewableLoopMode));
});
document.querySelectorAll("[data-renewable-strategy-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tabKey = button.dataset.renewableStrategyTab || "ac-wind";
    if (!RENEWABLE_STRATEGY_TABS[tabKey]) return;
    state.renewableControl.strategyTab = tabKey;
    renderRenewableControl(state.snapshot || {});
  });
});
document.querySelectorAll("[data-renewable-metric-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tabKey = button.dataset.renewableMetricTab || "ac";
    if (!["ac", "dc", "system", "hydrogen"].includes(tabKey)) return;
    state.renewableControl.metricTab = tabKey;
    renderRenewableMetricTabs();
  });
});
document.querySelectorAll("[data-renewable-parameter-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    renderRenewableControlParameterTabs(button.dataset.renewableParameterTab || "runtime");
  });
});
document.querySelectorAll("[data-renewable-detail-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.renewableDetailTab || "trend";
    state.renewableControl.detailTab = ["trend", "logs"].includes(tab)
      ? tab
      : "trend";
    renderRenewableDetailTabs();
  });
});
$("renewableControlLogPager")?.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-renewable-pager=\"logs\"]") : null;
  if (!button) return;
  const total = renewableControlLogs().length;
  const pageCount = Math.max(1, Math.ceil(total / RENEWABLE_CONTROL_LOG_PAGE_SIZE));
  const direction = button.dataset.renewablePageAction;
  state.renewableControl.logPage = direction === "prev"
    ? Math.max(1, state.renewableControl.logPage - 1)
    : Math.min(pageCount, state.renewableControl.logPage + 1);
  state.renewableControl.lastControlLogRenderKey = "";
  renderRenewableControlLogs();
});
// #clearRuntimeLogs 由全局点击事件委托统一处理，避免重复绑定触发二次 showModal() 报错。
const runtimeLogTableNode = $("commandHistory");
runtimeLogTableNode.addEventListener("click", handleRuntimeLogTableActivation);
runtimeLogTableNode.addEventListener("dblclick", handleRuntimeLogTableActivation);
runtimeLogTableNode.addEventListener("keydown", handleRuntimeLogTableActivation);
$("closeRuntimeLogDetailDialog").addEventListener("click", closeRuntimeLogDetailDialog);
$("confirmRuntimeLogDetailDialog").addEventListener("click", closeRuntimeLogDetailDialog);
$("runtimeLogDetailDialog").addEventListener("click", (event) => {
  if (event.target === $("runtimeLogDetailDialog")) closeRuntimeLogDetailDialog();
});
$("saveBackendRuntimeParameters").addEventListener("click", () => saveWebRuntimeSettings("backend"));
$("undoBackendRuntimeParameters").addEventListener("click", () => undoWebRuntimeSettings("backend"));
$("restoreBackendRuntimeParameterDefaults").addEventListener("click", () => restoreWebRuntimeDefaults("backend"));
$("saveRuntimeParameters").addEventListener("click", () => saveWebRuntimeSettings("web"));
$("undoRuntimeParameters").addEventListener("click", () => undoWebRuntimeSettings("web"));
$("restoreRuntimeParameterDefaults").addEventListener("click", () => restoreWebRuntimeDefaults("web"));
document.querySelectorAll("[data-runtime-setting]").forEach((input) => {
  input.addEventListener("input", () => updateWebRuntimeDraft(input));
  if (input.tagName === "SELECT") {
    input.addEventListener("change", () => updateWebRuntimeDraft(input));
  }
});
$("refreshManualChanges").addEventListener("click", loadManualDefinitionChanges);
$("retryPendingManualChanges").addEventListener("click", retryPendingManualDefinitionChanges);
$("resetSelectedManualChanges").addEventListener("click", resetSelectedManualDefinitionChanges);
$("manualDefinitionChangesTable").addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") return;
  if (target.matches("[data-manual-change-select-all]")) {
    state.manualDefinitionChangeSelection = target.checked
      ? new Set(state.manualDefinitionChanges.map((item) => String(item.id || "")).filter(Boolean))
      : new Set();
    renderManualDefinitionChanges();
    return;
  }
  const changeId = target.dataset.manualChangeId || "";
  if (changeId) toggleManualDefinitionChange(changeId, target.checked);
});
$("traineeRuntimeLogTypeFilter").addEventListener("change", (event) => {
  state.runtimeLogTypeFilter = event.target.value || "all";
  state.runtimeLogPage = 1;
  renderHistory();
});
$("traineeRuntimeLogPager").addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-trainee-runtime-log-page]") : null;
  if (!button) return;
  const direction = button.dataset.traineeRuntimeLogPage;
  const pageCount = traineeRuntimeLogPageCount(filteredTraineeRuntimeLogs());
  state.runtimeLogPage = direction === "prev"
    ? Math.max(1, state.runtimeLogPage - 1)
    : Math.min(pageCount, state.runtimeLogPage + 1);
  renderHistory();
});
const modelSelector = $("modelSelector");
if (modelSelector) {
  modelSelector.addEventListener("change", (event) => setActiveModel(event.target.value));
}
$("measurementTraceWindow").addEventListener("change", (event) => {
  state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
  resetChartPeriodOffsets("measurementTrace");
  drawMeasurementTraceChart();
});
const commandTraceWindow = $("commandTraceWindow");
if (commandTraceWindow) {
  commandTraceWindow.addEventListener("change", (event) => {
    state.commandTraceWindowMinutes = Number(event.target.value) || 60;
    resetChartPeriodOffsets("commandTrace");
    drawCommandTraceChart();
  });
}
const renewableTrendWindow = $("renewableTrendWindow");
if (renewableTrendWindow) {
  renewableTrendWindow.addEventListener("change", (event) => {
    state.renewableTrendWindowMinutes = Number(event.target.value) || 60;
    resetChartPeriodOffsets("renewableTrend");
    drawRenewableTrendChart();
  });
}
renderRenewableTrendSeriesTree();
const renewableTrendSeriesFilter = $("renewableTrendSeriesFilter");
if (renewableTrendSeriesFilter) {
  renewableTrendSeriesFilter.value = state.renewableTrendSeriesFilter;
  const applyTrendSeriesFilterDebounced = debounce((value) => {
    state.renewableTrendSeriesFilter = value || "";
    applyRenewableTrendSeriesFilters(state.renewableControl.lastPlan?.metrics || {});
  }, 150);
  renewableTrendSeriesFilter.addEventListener("input", (event) => {
    if (traineeSearchComposing) return;
    applyTrendSeriesFilterDebounced(event.target.value || "");
  });
  renewableTrendSeriesFilter.addEventListener("compositionend", (event) => {
    applyTrendSeriesFilterDebounced(event.target.value || "");
  });
}
const renewableTrendSelectedOnly = $("renewableTrendSelectedOnly");
if (renewableTrendSelectedOnly) {
  renewableTrendSelectedOnly.checked = state.renewableTrendSelectedOnly;
  renewableTrendSelectedOnly.addEventListener("change", (event) => {
    state.renewableTrendSelectedOnly = Boolean(event.target.checked);
    applyRenewableTrendSeriesFilters(state.renewableControl.lastPlan?.metrics || {});
  });
}
const renewableTrendClearAll = $("renewableTrendClearAll");
if (renewableTrendClearAll) {
  renewableTrendClearAll.addEventListener("click", () => {
    setRenewableTrendBatchSeriesVisibility(
      false,
      state.renewableControl.lastPlan?.metrics || {},
    );
  });
}
const renewableTrendSelectAll = $("renewableTrendSelectAll");
if (renewableTrendSelectAll) {
  renewableTrendSelectAll.addEventListener("click", () => {
    setRenewableTrendBatchSeriesVisibility(
      true,
      state.renewableControl.lastPlan?.metrics || {},
    );
  });
}
applyRenewableTrendSeriesFilters(state.renewableControl.lastPlan?.metrics || {});
const renewableTrendSeriesPanel = $("renewableTrendSeriesPanel");
if (renewableTrendSeriesPanel) {
  renewableTrendSeriesPanel.addEventListener("change", (event) => {
    const input = event.target instanceof HTMLInputElement
      ? event.target.closest('input[data-chart-toggle="renewableTrend"][data-chart-series]')
      : null;
    if (!input) return;
    const seriesKey = input.dataset.chartSeries || "";
    const visible = input.checked;
    setChartSeriesVisibility(
      "renewableTrend",
      seriesKey,
      visible,
      drawRenewableTrendChart,
    );
    if (visible) ensureRenewableTrendHistoryForVisibleSeries();
  });
}
initTraceChartInteractions("measurementTrace", "measurementTraceChart", drawMeasurementTraceChart);
initTraceChartInteractions("commandTrace", "commandTraceChart", drawCommandTraceChart);
initTraceChartInteractions("renewableTrend", "renewableTrendChart", drawRenewableTrendChart);
initChartPeriodNavigation("measurementTrace", measurementTraceWindowRange, drawMeasurementTraceChart);
initChartPeriodNavigation("commandTrace", commandTraceWindowRange, drawCommandTraceChart);
initChartPeriodNavigation("renewableTrend", renewableTrendWindowRange, drawRenewableTrendChart);
const curveDisplayChart = $("curveDisplayChart");
if (curveDisplayChart) {
  let lastCurveDisplayPointerDownAt = 0;
  let lastCurveDisplayHandledAt = 0;
  const handleCurveDisplaySelection = (event) => {
    if (event.button !== undefined && event.button !== 0) return false;
    const legendKey = curveDisplayLegendKeyAtPointer(event);
    if (legendKey) {
      event.preventDefault();
      toggleCurveDisplaySeriesVisibility(legendKey, true);
      return true;
    }
    const hitKey = curveDisplayKeyAtPointer(event);
    if (hitKey) {
      event.preventDefault();
      state.activeCurveDisplayKey = hitKey;
      drawCurveDisplay(state.snapshot || {});
      return true;
    }
    return false;
  };
  const handleCurveDisplayPointerDown = (event) => {
    if (event.type === "pointerdown") {
      lastCurveDisplayPointerDownAt = Date.now();
    } else if (Date.now() - lastCurveDisplayPointerDownAt < 80) {
      return;
    }
    if (handleCurveDisplaySelection(event)) {
      lastCurveDisplayHandledAt = Date.now();
    }
  };
  curveDisplayChart.addEventListener("pointermove", (event) => setCurveDisplayCursorFromEvent(event));
  curveDisplayChart.addEventListener("mousemove", (event) => setCurveDisplayCursorFromEvent(event));
  curveDisplayChart.addEventListener("pointerleave", hideCurveDisplayCursor);
  curveDisplayChart.addEventListener("mouseleave", hideCurveDisplayCursor);
  curveDisplayChart.addEventListener("pointerdown", handleCurveDisplayPointerDown);
  curveDisplayChart.addEventListener("mousedown", handleCurveDisplayPointerDown);
  curveDisplayChart.addEventListener("click", (event) => {
    if (Date.now() - lastCurveDisplayHandledAt < 160) return;
    handleCurveDisplaySelection(event);
  });
}
let traineeResizeTimerId = null;
window.addEventListener("resize", () => {
  if (traineeResizeTimerId !== null) clearTimeout(traineeResizeTimerId);
  traineeResizeTimerId = setTimeout(() => {
    traineeResizeTimerId = null;
    redrawActiveTraineeCharts();
  }, 120);
});
document.addEventListener("visibilitychange", () => {
  if (pageIsHidden()) {
    if (state.frontendRefreshTimerId) {
      clearTimeout(state.frontendRefreshTimerId);
      state.frontendRefreshTimerId = null;
    }
    return;
  }
  scheduleNextRefresh(0);
});

function initTraineeUiEnhancements() {
  // 1. 新能源控制参数策略预设下拉与脏状态跟踪
  const presetSelect = $("renewableControlPreset");
  const paramDialog = $("renewableControlParametersDialog");
  if (presetSelect) {
    presetSelect.addEventListener("change", () => {
      const value = presetSelect.value || "custom";
      if (value !== "custom") applyRenewableControlPreset(value);
    });
  }
  if (paramDialog) {
    const markParamDirty = (event) => {
      if (state.renewablePresetApplying) return;
      if (event.target?.id === "renewableControlPreset") return;
      state.renewableParametersDirty = true;
      if (presetSelect && presetSelect.value !== "custom") {
        presetSelect.value = detectRenewableControlPreset();
      }
    };
    paramDialog.addEventListener("input", markParamDirty);
    paramDialog.addEventListener("change", markParamDirty);
  }

  // 2. 遥调弹窗快捷设定值按钮（置 0 / -10% / 当前量测 / +10%）
  const adjustDialog = $("remoteAdjustmentDialog");
  if (adjustDialog) {
    adjustDialog.addEventListener("click", (event) => {
      const button = event.target instanceof Element
        ? event.target.closest("[data-remote-adjust-preset]")
        : null;
      if (!button) return;
      const input = $("remoteAdjustmentValue");
      if (!input) return;
      const row = state.remoteAdjustment || {};
      const currentVal = Number(input.value);
      const measuredVal = Number(row.measurement ?? row.measurementValue ?? row.measuredValue ?? row.currentValue);
      const baseVal = Number.isFinite(currentVal)
        ? currentVal
        : (Number.isFinite(measuredVal) ? measuredVal : 0);
      const mode = button.dataset.remoteAdjustPreset || "";
      let nextVal = baseVal;
      if (mode === "zero") {
        nextVal = 0;
      } else if (mode === "measured") {
        if (!Number.isFinite(measuredVal)) return;
        nextVal = measuredVal;
      } else if (mode === "minus10") {
        nextVal = baseVal * 0.9;
      } else if (mode === "plus10") {
        nextVal = baseVal * 1.1;
      }
      input.value = String(Number(nextVal.toFixed(4)));
      input.focus();
      input.select();
    });
  }

  // 3. 全局快捷键：Esc 关闭顶层弹窗；非输入态按 "/" 聚焦当前活动页搜索框
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const openDialogs = Array.from(document.querySelectorAll("dialog[open]"));
      const topDialog = openDialogs[openDialogs.length - 1];
      if (topDialog) {
        if (topDialog.id === "dangerConfirmDialog") {
          return;
        }
        if (topDialog.id === "renewableControlParametersDialog" && state.renewableParametersDirty) {
          event.preventDefault();
          confirmDangerousAction({
            title: "放弃未保存的控制参数？",
            target: "新能源控制参数配置",
            message: "当前参数修改尚未保存，关闭弹窗将丢失未保存的更改。",
            confirmLabel: "放弃并关闭",
          }).then((accepted) => {
            if (accepted) closeRenewableControlParametersDialog();
          });
          return;
        }
        if (topDialog.id === "remoteControlDialog") {
          event.preventDefault();
          closeRemoteControlDialog();
          return;
        }
        if (topDialog.id === "remoteAdjustmentDialog") {
          event.preventDefault();
          closeRemoteAdjustmentDialog();
          return;
        }
        if (topDialog.id === "diagramDeviceCommandDialog") {
          event.preventDefault();
          closeDiagramDeviceCommandDialog();
          return;
        }
        if (topDialog.id === "modelManagementDialog") {
          event.preventDefault();
          closeModelManagementDialog();
          return;
        }
        if (typeof topDialog.close === "function") {
          event.preventDefault();
          topDialog.close();
        }
      }
      return;
    }
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (document.querySelector("dialog[open]")) return;
      const active = document.activeElement;
      const inEditable = active && (
        active.tagName === "INPUT"
        || active.tagName === "TEXTAREA"
        || active.tagName === "SELECT"
        || active.isContentEditable
      );
      if (inEditable) return;
      const candidates = Array.from(document.querySelectorAll('main input[type="search"]'));
      const visible = candidates.find((el) => el.offsetParent !== null && !el.disabled);
      if (visible) {
        event.preventDefault();
        visible.focus();
        visible.select();
      }
    }
  });

  // 5. 量测异常速筛/CSV 导出 & 运行日志关键字搜索/仅看告警
  $("measurementOnlyAbnormalFilter")?.addEventListener("change", (event) => {
    state.measurementOnlyAbnormal = Boolean(event.target.checked);
    renderMeasurements(state.snapshot || {});
  });
  $("exportMeasurementsCsvButton")?.addEventListener("click", () => {
    exportTraineeMeasurementsCsv();
  });
  let traineeLogSearchTimer = null;
  $("traineeRuntimeLogKeywordFilter")?.addEventListener("input", (event) => {
    const val = String(event.target.value || "");
    if (traineeLogSearchTimer) clearTimeout(traineeLogSearchTimer);
    traineeLogSearchTimer = setTimeout(() => {
      traineeLogSearchTimer = null;
      state.runtimeLogKeywordFilter = val;
      state.runtimeLogPage = 1;
      renderHistory();
    }, 150);
  });
  $("traineeRuntimeLogOnlyAlertFilter")?.addEventListener("change", (event) => {
    state.runtimeLogOnlyAlert = Boolean(event.target.checked);
    state.runtimeLogPage = 1;
    renderHistory();
  });

  // 4. 离开页面前未保存变更保护
  window.addEventListener("beforeunload", (event) => {
    const paramOpenAndDirty = Boolean($("renewableControlParametersDialog")?.open && state.renewableParametersDirty);
    const runtimeDirty = Boolean(
      (typeof runtimeParameterGroupDirty === "function" && (runtimeParameterGroupDirty("backend") || runtimeParameterGroupDirty("web")))
    );
    if (paramOpenAndDirty || runtimeDirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
}

initOverviewBottomSplitter();
initOverviewBottomColumnSplitter();
initVerticalSplitters();
initPrecisionUiChrome();
initTraineeUiEnhancements();
renderReceiveMode();
renderHistory();
initPageNavigation();
loadModels().finally(() => {
  refresh();
  restartRefreshScheduler();
});
