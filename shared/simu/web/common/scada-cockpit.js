/**
 * 极地微电网 SCADA 大屏幕主画面统一引擎 (shared/simu/web/common/scada-cockpit.js)
 * 挂载于独立目录页面 section[data-page="screen"]，自动区分教员端与学员端，
 * 直读实时快照与能量流聚合模型，支持沉浸全屏、14 风格自适应及三语实时切换。
 */
(function initPolarScadaCockpit() {
  if (typeof document === "undefined" || typeof window === "undefined") return;
  if (window.__polarScadaCockpitReady) return;
  window.__polarScadaCockpitReady = true;

  const tr = (zh) => (typeof translatePhrase === "function" ? translatePhrase(zh) : zh);

  function isTraineeApp() {
    return Boolean(document.getElementById("traineeRunToggle"));
  }

  function textOf(id) {
    return (document.getElementById(id)?.textContent || "").trim();
  }

  function finiteOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function groupPowerKw(groups, key) {
    const g = groups?.[key];
    if (!g || g.present === false) return 0;
    const val = finiteOrNull(g.power);
    return val == null ? 0 : val;
  }

  function readStorageSocFromGroups(groups, power) {
    const socVals = [];
    ["dcStorage", "acStorage", "dcGridFollowingStorage", "acGridFollowingStorage", "dcGridFormingStorage", "acGridFormingStorage"].forEach((key) => {
      const g = groups?.[key];
      if (!g || g.present === false) return;
      const s = finiteOrNull(g.soc);
      if (s != null) socVals.push(s <= 1.0001 && s >= 0 ? s * 100 : s);
    });
    if (socVals.length) {
      return socVals.reduce((a, b) => a + b, 0) / socVals.length;
    }
    const pSoc = finiteOrNull(power?.soc);
    return pSoc != null ? (pSoc <= 1.0001 && pSoc >= 0 ? pSoc * 100 : pSoc) : null;
  }

  function readHydrogenMetaFromGroups(groups) {
    const h2 = groups?.hydrogenStorage;
    if (!h2 || h2.present === false) return { soc: null, pressure: null };
    const rawSoc = finiteOrNull(h2.soc);
    const soc = rawSoc != null ? (rawSoc <= 1.0001 && rawSoc >= 0 ? rawSoc * 100 : rawSoc) : null;
    const pressure = finiteOrNull(h2.gasPressure ?? h2.pressure);
    return { soc, pressure };
  }

  function readBusVoltageRange(snapshot) {
    const snap = snapshot || (typeof state !== "undefined" ? (state.snapshot || state.localSnapshot || null) : null);
    if (!snap) return { minPu: null, maxPu: null };
    let rows = [];
    if (typeof measurementDisplayRows === "function") {
      try {
        rows = measurementDisplayRows(snap) || [];
      } catch (_e) {
        rows = [];
      }
    }
    if (!rows.length) {
      const raw = snap.measurements ?? snap.scada_measurements;
      if (Array.isArray(raw)) rows = raw;
      else if (raw && typeof raw === "object") rows = Object.values(raw);
    }
    let minPu = Infinity;
    let maxPu = -Infinity;
    for (let i = 0; i < rows.length; i += 1) {
      const r = rows[i];
      if (!r || typeof r !== "object") continue;
      if (r.valid !== undefined && Number(r.valid) === 0) continue;
      const k = String(r.meas_type || r.key || r.field || r.name || "").toLowerCase();
      const t = String(r.dev_type || r.type || "");
      const v = Number(r.value ?? r.meas ?? r.val ?? r.v);
      if (!Number.isFinite(v) || v <= 0.1 || v >= 2.5) continue;
      if (
        /(?:^|_)(?:v_pu|u_pu|vm_pu|voltage_pu|u_mag)(?:$|_)/.test(k)
        || (/bus|node/i.test(t) && /^(?:v|u|vm|v_pu|u_pu|voltage)$/.test(k))
      ) {
        if (v < minPu) minPu = v;
        if (v > maxPu) maxPu = v;
      }
    }
    return {
      minPu: Number.isFinite(minPu) ? minPu : null,
      maxPu: Number.isFinite(maxPu) ? maxPu : null,
    };
  }

  function syncScadaI18n(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-sc-zh]").forEach((el) => {
      const zh = el.dataset.scZh || "";
      if (zh) el.textContent = tr(zh);
    });
  }

  function navigateToPage(pageName) {
    if (typeof showPage === "function") {
      showPage(pageName);
      return;
    }
    document.querySelector(`.page-nav button[data-nav-page="${pageName}"]`)?.click();
  }

  function jumpCategory(cat, trainee) {
    const keywordMap = {
      pv: "PVGen",
      wind: "WindGen",
      hydrogen: "Hydro",
      storage: "Storage",
      diesel: "Diesel",
      load: "Load",
    };
    const kw = keywordMap[cat] || "";
    if (trainee && typeof window.jumpToDeviceCommands === "function" && ["storage", "diesel", "hydrogen", "wind", "pv"].includes(cat)) {
      window.jumpToDeviceMeasurements?.(kw);
      return;
    }
    if (typeof window.jumpToDeviceMeasurements === "function") {
      window.jumpToDeviceMeasurements(kw);
    } else {
      navigateToPage("measurements");
    }
  }

  const SC_ICONS = Object.freeze({
    wind: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M9.6 4.6A2 2 0 1 1 11 8H2m10.6 11.4A2 2 0 1 0 14 16H2m15.7-8.3A2.5 2.5 0 1 1 19.5 12H2"/></svg>',
    sun: '<svg class="sc-ico is-amber" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    temp: '<svg class="sc-ico is-purple" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0Z"/><path d="M12 9v7"/></svg>',
    press: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 12l4-3M12 7v1M7 12h1M16 12h1"/></svg>',
    hum: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.6C8.5 7 6 10.2 6 13.8a6 6 0 0 0 12 0C18 10.2 15.5 7 12 2.6Z"/></svg>',
    load: '<svg class="sc-ico is-amber" viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 10-12h-7Z"/></svg>',
    turbine: '<svg class="sc-ico is-green" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12v9M9 21h6"/><circle cx="12" cy="10" r="1.8"/><path d="M12 8 10.5 3c2.4 0 4 1.5 3.3 4.2M10.4 11l-5 1.8c.2-2.4 1.8-4 4.2-3.3M13.6 11l3.6 4c-2.4.7-4.5-.8-3.8-3.3"/></svg>',
    pv: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16l1.5 10h-19L4 6ZM9 6 8 16M15 6l1 10M3.5 11h17M9 20h6M12 16v4"/></svg>',
    bess: '<svg class="sc-ico is-purple" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="6" width="15" height="12" rx="2"/><path d="M19 10h2v4h-2M8 10v4M11.5 10v4M15 10v4"/></svg>',
    wave: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12h4l2.5-6 4 12 2.5-6H22"/></svg>',
    h2: '<svg class="sc-ico is-green" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M9 9v6M15 9v6M9 12h6"/></svg>',
    leaf: '<svg class="sc-ico is-green" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 5c-6 0-11 3.5-13 9 2.5 1 5.5 1.5 8 0 3.5-2 5-5.5 5-9Z"/><path d="M6 19c1.5-2.5 4-4.5 7-6"/></svg>',
    link: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
    ping: '<svg class="sc-ico is-green" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/></svg>',
    spark: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/></svg>',
    moon: '<svg class="sc-ico is-purple" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z"/></svg>',
    storm: '<svg class="sc-ico is-amber" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.5 18a4 4 0 0 0 .5-7.9A5.5 5.5 0 0 0 7.2 8.5 4 4 0 0 0 6.5 16h2"/><path d="M13 12l-3 5h4l-2 4"/></svg>',
    cloud: '<svg class="sc-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.5 18H7a4 4 0 0 1-.5-7.9A5.5 5.5 0 0 1 17 8.5a3.5 3.5 0 0 1 .5 9.5Z"/></svg>',
  });

  const POLAR_ENV_PRESETS = Object.freeze([
    { id: "polar-night", icon: SC_ICONS.moon, labelZh: "极夜极寒静风", wind: 1.5, irr: 0, temp: -42, press: 952, hum: 62 },
    { id: "blizzard", icon: SC_ICONS.storm, labelZh: "暴风雪切出", wind: 28.0, irr: 0, temp: -36, press: 928, hum: 92 },
    { id: "cold-gale", icon: SC_ICONS.wind, labelZh: "寒潮强风高发", wind: 16.5, irr: 80, temp: -30, press: 945, hum: 78 },
    { id: "polar-day", icon: SC_ICONS.sun, labelZh: "极昼晴好微风", wind: 7.5, irr: 780, temp: -8, press: 985, hum: 55 },
    { id: "low-press", icon: SC_ICONS.cloud, labelZh: "低气压寒流", wind: 12.0, irr: 180, temp: -24, press: 938, hum: 84 },
  ]);

  let lastLiveEnv = { wind: null, irr: null, temp: null, press: null, hum: null };

  /**
   * 评估南极极端气象与风光储系统的实时耦合状态
   */
  function evaluatePolarClimateCoupling(env) {
    const w = finiteOrNull(env.wind);
    const irr = finiteOrNull(env.irr);
    const t = finiteOrNull(env.temp);

    // 1. 整体气候态诊断
    let regimeZh = "常规极地";
    let regimeLevel = "";
    if (w != null && w >= 25) {
      regimeZh = "暴雪切出";
      regimeLevel = "danger";
    } else if (w != null && w >= 15 && t != null && t <= -25) {
      regimeZh = "极寒强风";
      regimeLevel = "warn";
    } else if ((irr == null || irr < 5) && t != null && t <= -30) {
      regimeZh = "极夜极寒";
      regimeLevel = "warn";
    } else if (w != null && w < 3 && (irr == null || irr < 50)) {
      regimeZh = "低温静风";
      regimeLevel = "warn";
    } else if (irr != null && irr >= 400) {
      regimeZh = "极昼晴好";
      regimeLevel = "ok";
    }

    // 2. 风电耦合（切入 / 爬坡 / 额定 / 高风切出）
    let windStatusZh = "--";
    let windLevel = "";
    if (w != null) {
      if (w >= 25) {
        windStatusZh = "高风切出";
        windLevel = "danger";
      } else if (w >= 12) {
        windStatusZh = "额定满发";
        windLevel = "ok";
      } else if (w >= 3) {
        windStatusZh = "爬坡发电";
        windLevel = "ok";
      } else {
        windStatusZh = "未切入";
        windLevel = "warn";
      }
    }

    // 3. 光伏耦合（极夜归零 / 弱光 / 低温增益）
    let pvStatusZh = "--";
    let pvLevel = "";
    let pvSuffix = "";
    if (irr != null) {
      if (irr < 5) {
        pvStatusZh = "极夜归零";
        pvLevel = "warn";
      } else if (irr < 150) {
        pvStatusZh = "弱光出力";
        pvLevel = "";
      } else {
        pvStatusZh = "低温增益";
        pvLevel = "ok";
        if (t != null && t < 25) {
          const gainPct = Math.min(25, Math.max(0, (25 - t) * 0.35));
          pvSuffix = ` +${gainPct.toFixed(0)}%`;
        }
      }
    }

    // 4. 极寒电化学储能温控耦合
    let bessStatusZh = "--";
    let bessLevel = "";
    if (t != null) {
      if (t <= -30) {
        bessStatusZh = "极寒降容";
        bessLevel = "danger";
      } else if (t <= -15) {
        bessStatusZh = "低温受限";
        bessLevel = "warn";
      } else {
        bessStatusZh = "常温正常";
        bessLevel = "ok";
      }
    }

    return {
      regimeZh,
      regimeLevel,
      windStatusZh,
      windLevel,
      pvStatusZh,
      pvLevel,
      pvSuffix,
      bessStatusZh,
      bessLevel,
    };
  }

  let envModalBackdrop = null;

  function ensureEnvInjectModal() {
    if (envModalBackdrop) return envModalBackdrop;
    const backdrop = document.createElement("div");
    backdrop.id = "scEnvInjectModal";
    backdrop.className = "sc-env-modal-backdrop";
    backdrop.hidden = true;
    const presetsHtml = POLAR_ENV_PRESETS.map(
      (p) => `<button type="button" class="sc-env-preset-btn" data-sc-preset="${p.id}">${p.icon}<span data-sc-zh="${p.labelZh}"></span></button>`,
    ).join("");
    backdrop.innerHTML = `
      <div class="sc-env-modal" role="dialog" aria-modal="true" aria-labelledby="scEnvModalTitle">
        <div class="sc-env-modal-head">
          <h3 id="scEnvModalTitle" data-sc-zh="南极极端气象与工况注入"></h3>
          <button type="button" class="sc-env-modal-close" data-sc-env-close aria-label="Close">×</button>
        </div>
        <div class="sc-env-modal-body">
          <div class="sc-env-presets">${presetsHtml}</div>
          <div class="sc-env-form-grid">
            <div class="sc-env-field">
              <label for="scInWind" data-sc-zh="风速"></label>
              <input id="scInWindRange" type="range" min="0" max="35" step="0.5" value="8" />
              <input id="scInWind" type="number" min="0" max="45" step="0.1" value="8" />
              <small>m/s</small>
            </div>
            <div class="sc-env-field">
              <label for="scInIrr" data-sc-zh="太阳辐照"></label>
              <input id="scInIrrRange" type="range" min="0" max="1200" step="10" value="0" />
              <input id="scInIrr" type="number" min="0" max="1400" step="1" value="0" />
              <small>W/m²</small>
            </div>
            <div class="sc-env-field">
              <label for="scInTemp" data-sc-zh="气温"></label>
              <input id="scInTempRange" type="range" min="-60" max="10" step="1" value="-25" />
              <input id="scInTemp" type="number" min="-80" max="30" step="0.5" value="-25" />
              <small>℃</small>
            </div>
            <div class="sc-env-field">
              <label for="scInPress" data-sc-zh="气压"></label>
              <input id="scInPressRange" type="range" min="900" max="1030" step="1" value="960" />
              <input id="scInPress" type="number" min="850" max="1060" step="0.5" value="960" />
              <small>hPa</small>
            </div>
            <div class="sc-env-field">
              <label for="scInHum" data-sc-zh="相对湿度"></label>
              <input id="scInHumRange" type="range" min="0" max="100" step="1" value="72" />
              <input id="scInHum" type="number" min="0" max="100" step="1" value="72" />
              <small>%</small>
            </div>
          </div>
          <div class="sc-env-duration-row">
            <label>
              <span data-sc-zh="持续时长"></span>
              <select id="scInDuration">
                <option value="0" data-sc-zh="当前单步"></option>
                <option value="15" data-sc-zh="15 分钟"></option>
                <option value="60" selected data-sc-zh="1 小时"></option>
                <option value="180" data-sc-zh="3 小时"></option>
                <option value="360" data-sc-zh="6 小时"></option>
              </select>
            </label>
            <span id="scEnvModalStatus" class="sc-env-modal-status"></span>
          </div>
        </div>
        <div class="sc-env-modal-foot">
          <button type="button" id="scEnvLoadLiveBtn" class="compact-action-btn"><span data-sc-zh="读取当前"></span></button>
          <div class="sc-env-modal-foot-right">
            <button type="button" class="compact-action-btn" data-sc-env-close><span data-sc-zh="关闭"></span></button>
            <button type="button" id="scEnvSubmitBtn" class="primary"><span data-sc-zh="立即注入"></span></button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    syncScadaI18n(backdrop);

    const pairs = [
      ["scInWindRange", "scInWind"],
      ["scInIrrRange", "scInIrr"],
      ["scInTempRange", "scInTemp"],
      ["scInPressRange", "scInPress"],
      ["scInHumRange", "scInHum"],
    ];
    pairs.forEach(([rId, nId]) => {
      const rEl = backdrop.querySelector(`#${rId}`);
      const nEl = backdrop.querySelector(`#${nId}`);
      rEl?.addEventListener("input", () => { if (nEl) nEl.value = rEl.value; });
      nEl?.addEventListener("input", () => { if (rEl) rEl.value = nEl.value; });
    });

    const fillValues = (vals) => {
      const setPair = (rId, nId, v) => {
        if (v == null || !Number.isFinite(Number(v))) return;
        const rEl = backdrop.querySelector(`#${rId}`);
        const nEl = backdrop.querySelector(`#${nId}`);
        if (rEl) rEl.value = String(v);
        if (nEl) nEl.value = String(v);
      };
      setPair("scInWindRange", "scInWind", vals.wind);
      setPair("scInIrrRange", "scInIrr", vals.irr);
      setPair("scInTempRange", "scInTemp", vals.temp);
      setPair("scInPressRange", "scInPress", vals.press);
      setPair("scInHumRange", "scInHum", vals.hum);
    };

    backdrop.querySelectorAll("[data-sc-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const preset = POLAR_ENV_PRESETS.find((p) => p.id === btn.dataset.scPreset);
        if (!preset) return;
        backdrop.querySelectorAll("[data-sc-preset]").forEach((b) => b.classList.toggle("is-active", b === btn));
        fillValues(preset);
        const st = backdrop.querySelector("#scEnvModalStatus");
        if (st) { st.textContent = ""; st.className = "sc-env-modal-status"; }
      });
    });

    backdrop.querySelector("#scEnvLoadLiveBtn")?.addEventListener("click", () => {
      fillValues({
        wind: lastLiveEnv.wind ?? 8.0,
        irr: lastLiveEnv.irr ?? 0,
        temp: lastLiveEnv.temp ?? -25.0,
        press: lastLiveEnv.press ?? 960.0,
        hum: lastLiveEnv.hum ?? 72,
      });
      backdrop.querySelectorAll("[data-sc-preset]").forEach((b) => b.classList.remove("is-active"));
    });

    const closeModal = () => { backdrop.hidden = true; };
    backdrop.querySelectorAll("[data-sc-env-close]").forEach((b) => b.addEventListener("click", closeModal));
    backdrop.addEventListener("click", (ev) => {
      if (ev.target === backdrop) closeModal();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !backdrop.hidden) closeModal();
    });

    backdrop.querySelector("#scEnvSubmitBtn")?.addEventListener("click", async () => {
      const submitBtn = backdrop.querySelector("#scEnvSubmitBtn");
      const statusEl = backdrop.querySelector("#scEnvModalStatus");
      const weather = {
        wind_speed_mps: Number(backdrop.querySelector("#scInWind")?.value),
        solar_irradiance_w_m2: Number(backdrop.querySelector("#scInIrr")?.value),
        air_temp_c: Number(backdrop.querySelector("#scInTemp")?.value),
        air_pressure_hpa: Number(backdrop.querySelector("#scInPress")?.value),
        humidity_pct: Number(backdrop.querySelector("#scInHum")?.value),
      };
      const durationMin = Number(backdrop.querySelector("#scInDuration")?.value || 0);
      if (typeof api !== "function") {
        if (statusEl) { statusEl.textContent = "API unavailable"; statusEl.className = "sc-env-modal-status is-error"; }
        return;
      }
      if (submitBtn) submitBtn.disabled = true;
      if (statusEl) { statusEl.textContent = `${tr("注入中")}...`; statusEl.className = "sc-env-modal-status"; }
      try {
        let payload;
        let injectedCount = 1;
        if (durationMin > 0) {
          const schema = await api("/api/external/realtime-inputs", { method: "GET" });
          const target = schema?.target_point || {};
          const stepMin = Math.max(1 / 60, Number(target.time_step_minutes) || 1);
          const maxPts = Math.max(1, Number(target.point_count) || 1440);
          injectedCount = Math.max(1, Math.min(maxPts, Math.round(durationMin / stepMin)));
          payload = {
            start_time: target.simu_time,
            point_count: injectedCount,
            point_interval_seconds: stepMin * 60,
            points: Array.from({ length: injectedCount }, () => ({ weather })),
          };
        } else {
          payload = { weather };
        }
        await api("/api/external/realtime-inputs", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        const okMsg = `${tr("气象已注入")} (${injectedCount})`;
        if (statusEl) { statusEl.textContent = okMsg; statusEl.className = "sc-env-modal-status is-ok"; }
        if (typeof showUiToast === "function") showUiToast(okMsg, "ok", 2200);
        if (typeof refreshSnapshot === "function") {
          setTimeout(() => { try { refreshSnapshot(); } catch (_e) {} }, 120);
        }
      } catch (err) {
        const msg = err?.message || "Failed";
        if (statusEl) { statusEl.textContent = msg; statusEl.className = "sc-env-modal-status is-error"; }
        if (typeof showUiToast === "function") showUiToast(msg, "error", 2600);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });

    backdrop.__fillLive = () => {
      fillValues({
        wind: lastLiveEnv.wind ?? 8.0,
        irr: lastLiveEnv.irr ?? 0,
        temp: lastLiveEnv.temp ?? -25.0,
        press: lastLiveEnv.press ?? 960.0,
        hum: lastLiveEnv.hum ?? 72,
      });
    };
    envModalBackdrop = backdrop;
    return backdrop;
  }

  const trendHistory = [];
  const TREND_MAX_POINTS = 120;
  let lastTrendSig = "";

  function buildScadaScreenDom(screenSection) {
    if (!screenSection || screenSection.querySelector("#polarScadaScreen")) return;
    const trainee = isTraineeApp();

    const screen = document.createElement("div");
    screen.id = "polarScadaScreen";
    screen.className = "sc-screen";
    screen.dataset.role = trainee ? "trainee" : "simulator";

    const titleZh = trainee ? "极地微电网智能调控大屏" : "极地微电网仿真主控大屏";
    const leftTopTitleZh = trainee ? "绿电保供与策略态势" : "仿真引擎运行态势";
    const leftMidTitleZh = trainee ? "教员数据源与气象" : "极地气象与边界";
    const curveTitleZh = trainee ? "策略功率与储能 SOC 曲线" : "源荷功率实时曲线";
    const rightTopTitleZh = trainee ? "电网安全与策略健康" : "电网安全与联动状态";
    const rightMidTitleZh = trainee ? "当前有效 / 排队指令" : "当前有效控制指令";
    const rightBotTitleZh = trainee ? "最新教员交互事件" : "最新仿真运行事件";

    const leftCumCards = trainee
      ? `
        <button type="button" class="sc-cum-item" data-sc-nav="renewable">
          <span class="sc-orb ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M19 5c-6 0-11 3.5-13 9 2.5 1 5.5 1.5 8 0 3.5-2 5-5.5 5-9Z"/><path d="M6 19c1.5-2.5 4-4.5 7-6"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="绿电占比"></span><div class="sc-cum-val"><strong id="scKpi1">--</strong><small>%</small></div></div>
        </button>
        <button type="button" class="sc-cum-item" data-sc-nav="measurements">
          <span class="sc-orb" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="6" y="4" width="12" height="17" rx="2"/><path d="M10 2h4M9 10h6M9 14h6"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="综合 SOC"></span><div class="sc-cum-val"><strong id="scKpi2">--</strong><small>%</small></div></div>
        </button>
        <button type="button" class="sc-cum-item" data-sc-nav="measurements">
          <span class="sc-orb ok" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M9 9v6M13 9v6M9 12h4"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="储氢余量"></span><div class="sc-cum-val"><strong id="scKpi3">--</strong><small id="scKpi3Unit">%</small></div></div>
        </button>
        <button type="button" class="sc-cum-item" data-sc-nav="commands">
          <span class="sc-orb warn" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M13 2 3 14h8l-1 8 10-12h-8Z"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="排队指令"></span><div class="sc-cum-val"><strong id="scKpi4">0</strong><small data-sc-zh="项"></small></div></div>
        </button>
      `
      : `
        <button type="button" class="sc-cum-item" data-sc-nav="model">
          <span class="sc-orb ok" aria-hidden="true"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="投入设备"></span><div class="sc-cum-val"><strong id="scKpi1">--</strong></div></div>
        </button>
        <button type="button" class="sc-cum-item" data-sc-nav="measurements">
          <span class="sc-orb" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M2 12h4l2.5-6 4 12 2.5-6H22"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="有效量测"></span><div class="sc-cum-val"><strong id="scKpi2">--</strong></div></div>
        </button>
        <button type="button" class="sc-cum-item" data-sc-nav="runtime">
          <span class="sc-orb warn" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M13 2 3 14h8l-1 8 10-12h-8Z"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="控制指令"></span><div class="sc-cum-val"><strong id="scKpi3">0</strong></div></div>
        </button>
        <button type="button" class="sc-cum-item" data-sc-nav="logs">
          <span class="sc-orb danger" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3 2.5 19.5h19L12 3Z"/><path d="M12 9.5v4.5M12 17h.01"/></svg></span>
          <div class="sc-cum-body"><span class="sc-cum-label" data-sc-zh="告警"></span><div class="sc-cum-val"><strong id="scKpi4">0</strong></div></div>
        </button>
      `;

    screen.innerHTML = `
      <div class="sc-backdrop" aria-hidden="true">
        <img class="sc-backdrop-img" src="/assets/qinling-hero.jpg" alt="" draggable="false" />
        <div class="sc-backdrop-vignette"></div>
        <div class="sc-backdrop-grid"></div>
        <div class="sc-corner tl"></div>
        <div class="sc-corner tr"></div>
        <div class="sc-corner bl"></div>
        <div class="sc-corner br"></div>
      </div>

      <div class="sc-grid">
        <!-- 左栏 -->
        <div class="sc-col">
          <article class="sc-panel">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="${leftTopTitleZh}"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <span class="sc-head-meta" id="scLeftModeMeta">--</span>
            </header>
            <div class="sc-cum-grid">${leftCumCards}</div>
          </article>

          <article class="sc-panel">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="${trainee ? leftMidTitleZh : "极地气象"}"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <span class="sc-regime-badge" id="scClimateRegime" data-sc-zh="常规极地"></span>
              ${trainee ? '<span class="sc-head-meta" id="scBoundaryTime">--</span>' : `<button type="button" id="scOpenEnvInjectBtn" class="sc-env-inject-btn">${SC_ICONS.spark}<span data-sc-zh="工况注入"></span></button>`}
            </header>
            <div class="sc-env-grid">
              <div class="sc-env-box" title="风速"><span>${SC_ICONS.wind}<em data-sc-zh="风速" style="font-style:normal"></em></span><strong id="scEnvWind">--</strong></div>
              <div class="sc-env-box" title="太阳辐照"><span>${SC_ICONS.sun}<em data-sc-zh="太阳辐照" style="font-style:normal"></em></span><strong id="scEnvIrr">--</strong></div>
              <div class="sc-env-box" title="气温"><span>${SC_ICONS.temp}<em data-sc-zh="气温" style="font-style:normal"></em></span><strong id="scEnvTemp">--</strong></div>
              <div class="sc-env-box" title="气压"><span>${SC_ICONS.press}<em data-sc-zh="气压" style="font-style:normal"></em></span><strong id="scEnvPress">--</strong></div>
              <div class="sc-env-box" title="相对湿度"><span>${SC_ICONS.hum}<em data-sc-zh="相对湿度" style="font-style:normal"></em></span><strong id="scEnvHum">--</strong></div>
              <div class="sc-env-box" title="负荷需求"><span>${SC_ICONS.load}<em data-sc-zh="负荷需求" style="font-style:normal"></em></span><strong id="scEnvLoad">--</strong></div>
            </div>
            <div class="sc-coupling-strip" aria-label="气象与能源耦合状态">
              <div class="sc-coupling-chip" id="scCoupleWind" title="风电耦合">${SC_ICONS.turbine}<strong id="scCoupleWindVal">--</strong></div>
              <div class="sc-coupling-chip" id="scCouplePv" title="光伏耦合">${SC_ICONS.pv}<strong id="scCouplePvVal">--</strong></div>
              <div class="sc-coupling-chip" id="scCoupleBess" title="储能温控">${SC_ICONS.bess}<strong id="scCoupleBessVal">--</strong></div>
            </div>
          </article>

          <article class="sc-panel sc-panel-grow">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="电源结构占比"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <span class="sc-head-meta" id="scMixTotalKw">-- kW</span>
            </header>
            <div class="sc-mix-body">
              <div class="sc-donut-wrap">
                <svg class="sc-donut-svg" viewBox="0 0 120 120" aria-hidden="true">
                  <circle class="sc-donut-track" cx="60" cy="60" r="44"></circle>
                  <g id="scDonutArcs"></g>
                </svg>
                <div class="sc-donut-center">
                  <strong id="scDonutGreen">--%</strong>
                  <span data-sc-zh="绿电"></span>
                </div>
              </div>
              <div class="sc-mix-bars" id="scMixBars"></div>
            </div>
          </article>
        </div>

        <!-- 中栏：南极秦岭站 3D 浮空全息枢纽 + 源荷实时功率曲线 -->
        <div class="sc-col">
          <article class="sc-panel sc-panel-hub" id="scHubPanel">
            <div class="sc-hub-stage">
              <div class="sc-hub-env-tag" id="scHubEnvTag">
                ${SC_ICONS.spark}<span id="scHubEnvRegime">--</span>
                <i aria-hidden="true"></i>
                ${SC_ICONS.wind}<span id="scHubEnvWind">--</span>
                <i aria-hidden="true"></i>
                ${SC_ICONS.temp}<span id="scHubEnvTemp">--</span>
              </div>
              <svg class="sc-hub-svg" viewBox="0 0 680 340" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
                <defs>
                  <radialGradient id="scCoreGlow" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stop-color="var(--teal)" stop-opacity="0.45" />
                    <stop offset="55%" stop-color="var(--teal)" stop-opacity="0.14" />
                    <stop offset="100%" stop-color="var(--teal)" stop-opacity="0" />
                  </radialGradient>
                </defs>
                <ellipse cx="340" cy="196" rx="236" ry="96" class="sc-hub-ring outer" />
                <ellipse cx="340" cy="196" rx="158" ry="64" class="sc-hub-ring mid" />
                <ellipse cx="340" cy="196" rx="110" ry="44" fill="url(#scCoreGlow)" />
                <ellipse cx="340" cy="196" rx="88" ry="34" class="sc-hub-ring core" />
                <g transform="translate(340, 196) scale(1, 0.4)">
                  <g class="sc-spin-cw"><circle r="108" class="sc-dial-ring" /></g>
                  <g class="sc-spin-ccw"><circle r="84" class="sc-dial-inner" /></g>
                </g>

                <g>
                  <path class="sc-flow-track" d="M 118 76 Q 214 92 292 162" />
                  <path class="sc-flow-track" d="M 104 176 Q 202 184 268 186" />
                  <path class="sc-flow-track" d="M 126 270 Q 226 260 296 210" />
                  <path class="sc-flow-track" d="M 388 162 Q 466 92 562 76" />
                  <path class="sc-flow-track" d="M 412 186 Q 478 184 576 176" />
                  <path class="sc-flow-track" d="M 554 270 Q 454 260 384 210" />
                </g>
                <g>
                  <path id="scPulsePv" class="sc-flow-pulse is-green is-idle" d="M 118 76 Q 214 92 292 162" />
                  <path id="scPulseWind" class="sc-flow-pulse is-green is-idle" d="M 104 176 Q 202 184 268 186" />
                  <path id="scPulseHydro" class="sc-flow-pulse is-green is-idle" d="M 126 270 Q 226 260 296 210" />
                  <path id="scPulseLoad" class="sc-flow-pulse is-idle" d="M 388 162 Q 466 92 562 76" />
                  <path id="scPulseStorage" class="sc-flow-pulse is-green is-idle" d="M 412 186 Q 478 184 576 176" />
                  <path id="scPulseDiesel" class="sc-flow-pulse is-warn is-idle" d="M 554 270 Q 454 260 384 210" />
                </g>
                <g>
                  <circle id="scBeadPv" r="3.4" class="sc-orb-bead is-green is-idle"><animateMotion dur="2.5s" repeatCount="indefinite" path="M 118 76 Q 214 92 292 162" /></circle>
                  <circle id="scBeadWind" r="3.6" class="sc-orb-bead is-green is-idle"><animateMotion dur="2.1s" repeatCount="indefinite" path="M 104 176 Q 202 184 268 186" /></circle>
                  <circle id="scBeadHydro" r="3.4" class="sc-orb-bead is-green is-idle"><animateMotion dur="2.6s" repeatCount="indefinite" path="M 126 270 Q 226 260 296 210" /></circle>
                  <circle id="scBeadLoad" r="3.8" class="sc-orb-bead is-idle"><animateMotion dur="1.9s" repeatCount="indefinite" path="M 388 162 Q 466 92 562 76" /></circle>
                  <circle id="scBeadStorage" r="3.5" class="sc-orb-bead is-green is-idle"><animateMotion dur="2.3s" repeatCount="indefinite" path="M 412 186 Q 478 184 576 176" /></circle>
                  <circle id="scBeadDiesel" r="3.4" class="sc-orb-bead is-warn is-idle"><animateMotion dur="2.4s" repeatCount="indefinite" path="M 554 270 Q 454 260 384 210" /></circle>
                </g>

                <g transform="translate(340, 168)">
                  <ellipse cx="0" cy="28" rx="84" ry="30" fill="url(#scCoreGlow)" />
                  <g class="sc-iso-float">
                    <image href="/assets/qinling-station-holo.png" x="-106" y="-88" width="212" height="162" preserveAspectRatio="xMidYMid meet" />
                  </g>
                </g>
              </svg>

              <button type="button" class="sc-node sc-node-pv" data-sc-cat="pv">
                <span class="sc-node-disc" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="10" rx="1.5"/><path d="M3 11h18M9 6v10M15 6v10"/></svg></span>
                <div class="sc-node-body"><span class="sc-node-title" data-sc-zh="光伏发电"></span><strong class="sc-node-val" id="scNodePv">-- kW</strong><span class="sc-node-sub" id="scNodePvSub">--</span></div>
              </button>
              <button type="button" class="sc-node sc-node-wind" data-sc-cat="wind">
                <span class="sc-node-disc" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="10" r="1.5"/><path d="M12 11.5V21M9 21h6M12 8.5 9.5 3M13.3 10.8 19 13M10.7 10.8 5 13"/></svg></span>
                <div class="sc-node-body"><span class="sc-node-title" data-sc-zh="风力发电"></span><strong class="sc-node-val" id="scNodeWind">-- kW</strong><span class="sc-node-sub" id="scNodeWindSub">--</span></div>
              </button>
              <button type="button" class="sc-node sc-node-hydrogen" data-sc-cat="hydrogen">
                <span class="sc-node-disc" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M8.5 9v6M12.5 9v6M8.5 12h4"/></svg></span>
                <div class="sc-node-body"><span class="sc-node-title" data-sc-zh="氢能制储"></span><strong class="sc-node-val" id="scNodeHydro">-- kW</strong><span class="sc-node-sub" id="scNodeHydroSub">--</span></div>
              </button>
              <button type="button" class="sc-node sc-node-load" data-sc-cat="load">
                <span class="sc-node-disc" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 4v5M16 4v5M6 9h12v3a6 6 0 0 1-12 0V9ZM12 18v3"/></svg></span>
                <div class="sc-node-body"><span class="sc-node-title" data-sc-zh="科考负荷"></span><strong class="sc-node-val" id="scNodeLoad">-- kW</strong><span class="sc-node-sub" id="scNodeLoadSub">--</span></div>
              </button>
              <button type="button" class="sc-node sc-node-storage" data-sc-cat="storage">
                <span class="sc-node-disc" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="6" y="4" width="12" height="17" rx="2"/><path d="M10 2h4M9 10h6M9 14h6"/></svg></span>
                <div class="sc-node-body"><span class="sc-node-title" data-sc-zh="电化学储能"></span><strong class="sc-node-val" id="scNodeStorage">-- kW</strong><span class="sc-node-sub" id="scNodeStorageSub">SOC --%</span></div>
              </button>
              <button type="button" class="sc-node sc-node-diesel" data-sc-cat="diesel">
                <span class="sc-node-disc" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h4M7 14h3M15 10v4M18 10v4"/></svg></span>
                <div class="sc-node-body"><span class="sc-node-title" data-sc-zh="柴发保供"></span><strong class="sc-node-val" id="scNodeDiesel">-- kW</strong><span class="sc-node-sub" id="scNodeDieselSub">--</span></div>
              </button>

              <div class="sc-hub-center-stat">
                <span><em data-sc-zh="绿电" style="font-style:normal"></em> <strong class="is-green" id="scHubGreen">--%</strong></span>
                <i></i>
                <span><em data-sc-zh="发" style="font-style:normal"></em> <strong id="scHubGen">--</strong> / <em data-sc-zh="荷" style="font-style:normal"></em> <strong id="scHubLoad">--</strong> kW</span>
              </div>
            </div>
          </article>

          <article class="sc-panel sc-panel-curve">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="${curveTitleZh}"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <div class="sc-curve-legend">
                <span><i class="ux-spark-dot" style="background:var(--green)"></i><em data-sc-zh="绿电出力" style="font-style:normal"></em></span>
                <span><i class="ux-spark-dot" style="background:var(--teal)"></i><em data-sc-zh="总负荷" style="font-style:normal"></em></span>
                <span><i class="ux-spark-dot" style="background:var(--amber)"></i><em data-sc-zh="柴发" style="font-style:normal"></em></span>
                ${trainee ? '<span><i class="ux-spark-dot" style="background:var(--blue)"></i>SOC</span>' : ""}
              </div>
            </header>
            <div class="sc-canvas-wrap">
              <canvas id="scTrendCanvas" class="sc-curve-canvas" width="640" height="180"></canvas>
            </div>
          </article>
        </div>

        <!-- 右栏 -->
        <div class="sc-col">
          <article class="sc-panel">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="${rightTopTitleZh}"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <button type="button" class="sc-head-link" data-sc-nav="${trainee ? "renewable" : "scada104"}" data-sc-zh="详情"></button>
            </header>
            <div class="sc-stat-grid">
              <div class="sc-stat-box"><span>${SC_ICONS.wave}<em data-sc-zh="母线电压" style="font-style:normal"></em></span><strong id="scStatBus">--</strong></div>
              <div class="sc-stat-box"><span>${SC_ICONS.bess}<em data-sc-zh="综合 SOC" style="font-style:normal"></em></span><strong id="scStatSoc">--</strong></div>
              <div class="sc-stat-box"><span>${SC_ICONS.h2}<em data-sc-zh="储氢压力" style="font-style:normal"></em></span><strong id="scStatH2">--</strong></div>
              <div class="sc-stat-box"><span>${SC_ICONS.leaf}<em data-sc-zh="绿电占比" style="font-style:normal"></em></span><strong id="scStatGreen">--</strong></div>
              <div class="sc-stat-box"><span>${SC_ICONS.link}<em data-sc-zh="${trainee ? "数据源" : "仿真模式"}" style="font-style:normal"></em></span><strong id="scStatExtra1">--</strong></div>
              <div class="sc-stat-box"><span>${SC_ICONS.ping}<em data-sc-zh="接口延迟" style="font-style:normal"></em></span><strong id="scStatLatency">--</strong></div>
            </div>
          </article>

          <article class="sc-panel sc-panel-grow">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="${rightMidTitleZh}"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <span class="sc-head-meta" id="scCmdCount">0</span>
              <button type="button" class="sc-head-link" data-sc-nav="${trainee ? "commands" : "runtime"}" data-sc-zh="全部"></button>
            </header>
            <div class="sc-list" id="scCommandList"><div class="sc-list-empty">—</div></div>
          </article>

          <article class="sc-panel sc-panel-grow">
            <header class="sc-head">
              <span class="sc-head-gem" aria-hidden="true"></span>
              <h2 data-sc-zh="${rightBotTitleZh}"></h2>
              <span class="sc-head-slash" aria-hidden="true"></span>
              <span class="sc-head-meta" id="scEventCount">0</span>
              <button type="button" class="sc-head-link" data-sc-nav="${trainee ? "history" : "logs"}" data-sc-zh="日志"></button>
            </header>
            <div class="sc-list" id="scEventList"><div class="sc-list-empty">—</div></div>
          </article>
        </div>
      </div>
    `;

    screenSection.appendChild(screen);
    syncScadaI18n(screenSection);

    screen.querySelector("#scOpenEnvInjectBtn")?.addEventListener("click", () => {
      const modal = ensureEnvInjectModal();
      modal.__fillLive?.();
      const st = modal.querySelector("#scEnvModalStatus");
      if (st) { st.textContent = ""; st.className = "sc-env-modal-status"; }
      modal.hidden = false;
    });

    screen.querySelectorAll("[data-sc-nav]").forEach((btn) => {
      btn.addEventListener("click", () => {
        navigateToPage(btn.dataset.scNav);
      });
    });

    screen.querySelectorAll("[data-sc-cat]").forEach((btn) => {
      btn.addEventListener("click", () => {
        jumpCategory(btn.dataset.scCat, trainee);
      });
    });
  }

  function renderDonutAndBars(mixItems, greenShare) {
    const arcsEl = document.getElementById("scDonutArcs");
    const barsEl = document.getElementById("scMixBars");
    const centerEl = document.getElementById("scDonutGreen");
    const totalEl = document.getElementById("scMixTotalKw");
    if (!arcsEl || !barsEl) return;

    const total = mixItems.reduce((acc, it) => acc + Math.max(0, it.kw), 0);
    if (totalEl) totalEl.textContent = `${total.toFixed(1)} kW`;
    if (centerEl) centerEl.textContent = greenShare == null ? "--%" : `${greenShare.toFixed(0)}%`;

    const r = 44;
    const circ = 2 * Math.PI * r;
    let offset = 0;
    const arcHtml = [];
    const barHtml = [];
    mixItems.forEach((it) => {
      const kw = Math.max(0, it.kw);
      const pct = total > 1e-4 ? (kw / total) * 100 : 0;
      const segLen = (pct / 100) * circ;
      if (segLen > 0.5) {
        arcHtml.push(
          `<circle class="sc-donut-arc" cx="60" cy="60" r="${r}" stroke="${it.color}" stroke-dasharray="${segLen.toFixed(2)} ${circ.toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}"></circle>`,
        );
        offset += segLen;
      }
      barHtml.push(`
        <div class="sc-mix-row">
          <div class="sc-mix-row-top">
            <span><i class="ux-spark-dot" style="background:${it.color}"></i>${tr(it.label)}</span>
            <strong>${kw.toFixed(1)} kW (${pct.toFixed(0)}%)</strong>
          </div>
          <div class="sc-mix-track"><div class="sc-mix-fill" style="width:${pct.toFixed(1)}%;background:${it.color}"></div></div>
        </div>
      `);
    });
    arcsEl.innerHTML = arcHtml.join("");
    barsEl.innerHTML = barHtml.join("");
  }

  function drawScadaTrendChart() {
    const canvas = document.getElementById("scTrendCanvas");
    if (!canvas) return;
    const wrap = canvas.parentElement;
    if (wrap && wrap.clientWidth > 60 && wrap.clientHeight > 40) {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const targetW = Math.round(wrap.clientWidth * dpr);
      const targetH = Math.round(wrap.clientHeight * dpr);
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const styles = getComputedStyle(document.documentElement);
    const gridColor = styles.getPropertyValue("--line").trim() || "rgba(148,163,184,0.2)";
    const textColor = styles.getPropertyValue("--muted").trim() || "#94a3b8";
    const cGreen = styles.getPropertyValue("--green").trim() || "#34d399";
    const cTeal = styles.getPropertyValue("--teal").trim() || "#38bdf8";
    const cAmber = styles.getPropertyValue("--amber").trim() || "#fbbf24";
    const cBlue = styles.getPropertyValue("--blue").trim() || "#60a5fa";

    const padL = 38;
    const padR = isTraineeApp() ? 34 : 12;
    const padT = 10;
    const padB = 20;
    const plotW = Math.max(20, w - padL - padR);
    const plotH = Math.max(20, h - padT - padB);

    const maxKw = Math.max(
      10,
      ...trendHistory.map((p) => Math.max(p.green, p.load, p.diesel)),
    );

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.font = `${Math.max(10, Math.round(h * 0.06))}px ui-monospace, Consolas, monospace`;
    ctx.fillStyle = textColor;
    ctx.textAlign = "right";
    for (let i = 0; i <= 3; i += 1) {
      const y = padT + (plotH * i) / 3;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      const val = maxKw * (1 - i / 3);
      ctx.fillText(val.toFixed(0), padL - 5, y + 3);
    }

    if (!trendHistory.length) {
      ctx.textAlign = "center";
      ctx.fillText("—", padL + plotW / 2, padT + plotH / 2);
      return;
    }

    const plotSeries = (key, color, maxVal, dashed = false) => {
      ctx.save();
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      if (dashed) ctx.setLineDash([5, 4]);
      let started = false;
      trendHistory.forEach((pt, idx) => {
        const v = Number(pt[key]);
        if (!Number.isFinite(v)) return;
        const x = trendHistory.length === 1 ? padL + plotW / 2 : padL + (idx / (trendHistory.length - 1)) * plotW;
        const y = padT + plotH - (Math.max(0, v) / maxVal) * plotH;
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();
      ctx.restore();
    };

    plotSeries("load", cTeal, maxKw);
    plotSeries("green", cGreen, maxKw);
    plotSeries("diesel", cAmber, maxKw);
    if (isTraineeApp()) {
      plotSeries("soc", cBlue, 100, true);
    }

    // 横轴起止时间
    ctx.textAlign = "left";
    ctx.fillStyle = textColor;
    ctx.fillText(trendHistory[0]?.time || "", padL, h - 5);
    ctx.textAlign = "right";
    ctx.fillText(trendHistory[trendHistory.length - 1]?.time || "", padL + plotW, h - 5);
  }

  function setFlowActive(pulseId, beadId, active) {
    const pulse = document.getElementById(pulseId);
    const bead = document.getElementById(beadId);
    pulse?.classList.toggle("is-idle", !active);
    bead?.classList.toggle("is-idle", !active);
  }

  function renderScadaList(items, targetId, countId, targetPage) {
    const target = document.getElementById(targetId);
    const countEl = document.getElementById(countId);
    if (!target) return;
    if (countEl) countEl.textContent = String(items.length);
    if (!items.length) {
      target.innerHTML = '<div class="sc-list-empty">—</div>';
      return;
    }
    target.replaceChildren();
    items.slice(0, 8).forEach((it) => {
      const row = document.createElement("div");
      row.className = "sc-list-item";
      const main = document.createElement("span");
      main.className = "sc-list-main";
      main.textContent = it.main;
      main.title = it.main;
      row.appendChild(main);
      if (it.meta) {
        const meta = document.createElement("span");
        meta.className = "sc-list-meta";
        meta.textContent = it.meta;
        row.appendChild(meta);
      }
      row.addEventListener("click", () => {
        delete document.documentElement.dataset.scadaImmersive;
        document.getElementById("scImmersiveToggle")?.classList.remove("is-active");
        navigateToPage(targetPage);
      });
      target.appendChild(row);
    });
  }

  function updateScadaCockpitData(incomingSnapshot = null) {
    const screenSection = document.querySelector('.page-section[data-page="screen"]');
    if (!screenSection || !screenSection.classList.contains("is-active")) return;
    buildScadaScreenDom(screenSection);

    const trainee = isTraineeApp();
    const snap = incomingSnapshot || (typeof state !== "undefined" ? (state.snapshot || {}) : {});
    const clock = snap.clock || {};
    const power = typeof parsePowerFlowOverview === "function" ? (parsePowerFlowOverview(snap) || {}) : {};
    const groups = power.flowGroups || {};

    const pvKw = Math.max(0, groupPowerKw(groups, "dcSolar")) + Math.max(0, groupPowerKw(groups, "acSolar"));
    const windKw = Math.max(0, groupPowerKw(groups, "dcWind")) + Math.max(0, groupPowerKw(groups, "acWind"));
    const dieselKw = Math.max(0, groupPowerKw(groups, "diesel"));
    const storageKw = groupPowerKw(groups, "dcStorage")
      + groupPowerKw(groups, "acStorage")
      + groupPowerKw(groups, "dcGridFollowingStorage")
      + groupPowerKw(groups, "acGridFollowingStorage")
      + groupPowerKw(groups, "dcGridFormingStorage")
      + groupPowerKw(groups, "acGridFormingStorage");
    const fcKw = Math.max(0, groupPowerKw(groups, "fuelCell"));
    const elecKw = Math.max(0, groupPowerKw(groups, "electrolyzer"));
    const dcLoad = Math.abs(groupPowerKw(groups, "dcLoad"));
    const acLoad = Math.abs(groupPowerKw(groups, "acLoad"));
    const totalLoad = dcLoad + acLoad + elecKw;
    const renewableKw = pvKw + windKw + fcKw;
    const totalGen = renewableKw + dieselKw + Math.max(0, storageKw);

    let greenShare = null;
    if (typeof overviewGreenMetrics === "function") {
      const gm = overviewGreenMetrics(power);
      if (gm && finiteOrNull(gm.greenPowerShare) != null) greenShare = Number(gm.greenPowerShare);
    }
    if (greenShare == null) {
      greenShare = totalLoad > 1e-4
        ? Math.max(0, Math.min(100, ((totalLoad - dieselKw) / totalLoad) * 100))
        : (totalGen > 1e-4 ? Math.min(100, (renewableKw / totalGen) * 100) : null);
    }

    const avgSoc = readStorageSocFromGroups(groups, power);
    const h2Meta = readHydrogenMetaFromGroups(groups);
    const busV = readBusVoltageRange(snap);

    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    // 顶栏徽标信息
    const modelSel = document.getElementById("modelSelector");
    const modelName = (
      modelSel?.options?.[modelSel.selectedIndex]?.text
      || snap.model?.name
      || snap.model?.id
      || textOf("activeModelName")
      || "--"
    ).trim();
    const stateLabels = { running: tr("运行中"), paused: tr("已暂停"), stopped: tr("已停止") };
    const headerState = trainee
      ? (textOf("connectionText") || stateLabels[clock.state] || "--")
      : (stateLabels[clock.state] || clock.state || "--");

    const effStepSec = Number(
      clock.effective_step_seconds
      ?? snap.system_parameters?.effective_step_seconds
      ?? ((clock.step_seconds ?? 1) * (clock.speed ?? 1)),
    );
    let stepText = "--";
    if (trainee && typeof formatTraineeClockDuration === "function" && Number.isFinite(effStepSec)) {
      stepText = formatTraineeClockDuration(effStepSec);
    } else if (!trainee && typeof formatClockDuration === "function" && Number.isFinite(effStepSec)) {
      stepText = formatClockDuration(effStepSec);
    } else if (clock.time) {
      stepText = clock.time;
    }

    let modeText = "--";
    if (trainee && typeof curveDisplayModeLabel === "function") {
      modeText = curveDisplayModeLabel(snap) || "--";
    } else if (!trainee && typeof simulationModeLabel === "function") {
      const rawMode = snap.curve_boundary?.mode || snap.curves?.mode || (typeof state !== "undefined" ? state.curveMode : "");
      modeText = simulationModeLabel(rawMode) || "--";
    }

    setText("scHeaderModel", modelName);
    setText("scHeaderState", headerState);
    setText("scHeaderStep", stepText);
    setText("scLeftModeMeta", modeText);

    // 指令列表数据源
    let cmdItems = [];
    let pendingCountTotal = 0;
    if (trainee) {
      const rows = typeof activeCommandPreviewRows === "function" ? (activeCommandPreviewRows(snap) || []) : [];
      pendingCountTotal = rows.length;
      cmdItems = rows.map((item) => ({
        main: `${item.wall_time || "--"} · ${item.name || "--"} · ${item.type || ""} · ${item.value ?? ""}`.trim(),
        meta: item.time || item.process_text || "",
      }));
    } else {
      const rows = typeof overviewActiveRuntimeCommandRows === "function" ? (overviewActiveRuntimeCommandRows(snap) || []) : [];
      pendingCountTotal = rows.length;
      cmdItems = rows.map((row) => ({
        main: `${row.receive_time?.wall_time || "--"} · ${row.device?.dev_name || "--"} · ${row.command || "--"}`,
        meta: row.receive_time?.simu_time || "",
      }));
    }

    // 左栏顶部 4 KPI
    if (trainee) {
      setText("scKpi1", greenShare == null ? "--" : greenShare.toFixed(1));
      setText("scKpi2", avgSoc == null ? "--" : avgSoc.toFixed(1));
      if (h2Meta.soc != null) {
        setText("scKpi3", h2Meta.soc.toFixed(1));
        setText("scKpi3Unit", "%");
      } else if (h2Meta.pressure != null) {
        setText("scKpi3", h2Meta.pressure.toFixed(2));
        setText("scKpi3Unit", "MPa");
      } else {
        setText("scKpi3", "--");
      }
      setText("scKpi4", String(pendingCountTotal));
    } else {
      const devices = Array.isArray(snap.devices) ? snap.devices : [];
      const onlineDevices = devices.filter((d) => Number(d.run_stat ?? 1) !== 0).length;
      const validScada = Number(snap.summary?.valid_scada_count || 0);
      const totalScada = Number(snap.summary?.scada_count || 0);
      setText("scKpi1", devices.length ? `${onlineDevices}/${devices.length}` : "--");
      setText("scKpi2", `${validScada}/${totalScada}`);
      setText("scKpi3", String(snap.summary?.command_count || 0));
      setText("scKpi4", String(snap.summary?.alarm_count || 0));
    }

    // 气象与环境工况（完整读取 5 维南极气象 + 负荷 + 实时耦合诊断）
    let boundaryTime = clock.time || textOf("simTime") || "--";
    const cbPt = snap.curve_boundary?.point || {};
    let windNum = finiteOrNull(cbPt.wind_speed_mps);
    let irrNum = finiteOrNull(cbPt.solar_irradiance_w_m2);
    let tempNum = finiteOrNull(cbPt.air_temp_c);
    const pressNum = finiteOrNull(cbPt.air_pressure_hpa);
    const humNum = finiteOrNull(cbPt.humidity_pct);
    let loadNum = finiteOrNull(snap.curve_boundary?.load_total);

    if (trainee) {
      const w = typeof currentWeatherLoad === "function" ? (currentWeatherLoad(snap) || {}) : {};
      if (typeof overviewClockText === "function") boundaryTime = overviewClockText(snap) || boundaryTime;
      if (finiteOrNull(w.windSpeed) != null) windNum = Number(w.windSpeed);
      if (finiteOrNull(w.solarIrradiance) != null) irrNum = Number(w.solarIrradiance);
      if (finiteOrNull(w.airTemp) != null) tempNum = Number(w.airTemp);
      if (finiteOrNull(w.loadKw) != null) loadNum = Number(w.loadKw);
    } else {
      const b = typeof overviewCurveBoundary === "function" ? (overviewCurveBoundary(snap) || {}) : {};
      const pt = b.point || {};
      if (typeof formatSimulationClock === "function") boundaryTime = formatSimulationClock(clock) || boundaryTime;
      if (finiteOrNull(pt.wind_speed_mps) != null) windNum = Number(pt.wind_speed_mps);
      if (finiteOrNull(pt.solar_irradiance_w_m2) != null) irrNum = Number(pt.solar_irradiance_w_m2);
      if (finiteOrNull(pt.air_temp_c) != null) tempNum = Number(pt.air_temp_c);
      if (finiteOrNull(b.loadTotal) != null) loadNum = Number(b.loadTotal);
    }
    lastLiveEnv = { wind: windNum, irr: irrNum, temp: tempNum, press: pressNum, hum: humNum };

    const windText = windNum != null ? `${windNum.toFixed(2)} m/s` : "--";
    const irrText = irrNum != null ? `${irrNum.toFixed(1)} W/m²` : "--";
    const tempText = tempNum != null ? `${tempNum.toFixed(1)} ℃` : "--";
    const pressText = pressNum != null ? `${pressNum.toFixed(1)} hPa` : "--";
    const humText = humNum != null ? `${humNum.toFixed(0)} %` : "--";
    const loadText = loadNum != null ? `${loadNum.toFixed(1)} kW` : `${totalLoad.toFixed(1)} kW`;

    setText("scBoundaryTime", boundaryTime);
    setText("scEnvWind", windText);
    setText("scEnvIrr", irrText);
    setText("scEnvTemp", tempText);
    setText("scEnvPress", pressText);
    setText("scEnvHum", humText);
    setText("scEnvLoad", loadText);

    const coupling = evaluatePolarClimateCoupling(lastLiveEnv);
    const regimeEl = document.getElementById("scClimateRegime");
    if (regimeEl) {
      regimeEl.textContent = tr(coupling.regimeZh);
      regimeEl.className = `sc-regime-badge${coupling.regimeLevel ? ` is-${coupling.regimeLevel}` : ""}`;
    }
    const setCouple = (boxId, valId, text, level) => {
      const box = document.getElementById(boxId);
      const val = document.getElementById(valId);
      if (box) box.className = `sc-coupling-chip${level ? ` is-${level}` : ""}`;
      if (val) val.textContent = text;
    };
    setCouple("scCoupleWind", "scCoupleWindVal", tr(coupling.windStatusZh), coupling.windLevel);
    setCouple("scCouplePv", "scCouplePvVal", `${tr(coupling.pvStatusZh)}${coupling.pvSuffix}`, coupling.pvLevel);
    setCouple("scCoupleBess", "scCoupleBessVal", tr(coupling.bessStatusZh), coupling.bessLevel);

    const hubPanel = document.getElementById("scHubPanel");
    if (hubPanel) {
      if (coupling.regimeLevel) hubPanel.dataset.climateLevel = coupling.regimeLevel;
      else delete hubPanel.dataset.climateLevel;
    }
    setText("scHubEnvRegime", tr(coupling.regimeZh));
    setText("scHubEnvWind", windText);
    setText("scHubEnvTemp", tempText);

    // 电源结构 Donut
    const styles = getComputedStyle(document.documentElement);
    const cGreen = styles.getPropertyValue("--green").trim() || "#34d399";
    const cTeal = styles.getPropertyValue("--teal").trim() || "#38bdf8";
    const cAmber = styles.getPropertyValue("--amber").trim() || "#fbbf24";
    const cBlue = styles.getPropertyValue("--blue").trim() || "#60a5fa";
    renderDonutAndBars(
      [
        { label: "风电", kw: windKw, color: cGreen },
        { label: "光伏", kw: pvKw, color: cTeal },
        { label: "储能/氢电", kw: Math.max(0, storageKw) + fcKw, color: cBlue },
        { label: "柴发", kw: dieselKw, color: cAmber },
      ],
      greenShare,
    );

    // 中央全息 6 台座与光轨动画
    setText("scNodePv", `${pvKw.toFixed(1)} kW`);
    setText("scNodePvSub", irrText);
    setText("scNodeWind", `${windKw.toFixed(1)} kW`);
    setText("scNodeWindSub", windText);
    setText("scNodeHydro", `${(fcKw - elecKw).toFixed(1)} kW`);
    setText("scNodeHydroSub", h2Meta.soc != null ? `SOC ${h2Meta.soc.toFixed(0)}%` : (h2Meta.pressure != null ? `${h2Meta.pressure.toFixed(2)} MPa` : "--"));
    setText("scNodeLoad", `${totalLoad.toFixed(1)} kW`);
    setText("scNodeLoadSub", `DC ${dcLoad.toFixed(0)} / AC ${acLoad.toFixed(0)}`);
    setText("scNodeStorage", `${storageKw.toFixed(1)} kW`);
    setText("scNodeStorageSub", avgSoc != null ? `SOC ${avgSoc.toFixed(1)}%` : "SOC --%");
    setText("scNodeDiesel", `${dieselKw.toFixed(1)} kW`);
    setText("scNodeDieselSub", totalLoad > 1e-4 ? `${((dieselKw / totalLoad) * 100).toFixed(0)}%` : "0%");

    setText("scHubGreen", greenShare == null ? "--%" : `${greenShare.toFixed(1)}%`);
    setText("scHubGen", totalGen.toFixed(1));
    setText("scHubLoad", totalLoad.toFixed(1));

    setFlowActive("scPulsePv", "scBeadPv", pvKw > 0.1);
    setFlowActive("scPulseWind", "scBeadWind", windKw > 0.1);
    setFlowActive("scPulseHydro", "scBeadHydro", fcKw > 0.1 || elecKw > 0.1);
    setFlowActive("scPulseLoad", "scBeadLoad", totalLoad > 0.1);
    setFlowActive("scPulseStorage", "scBeadStorage", Math.abs(storageKw) > 0.1);
    setFlowActive("scPulseDiesel", "scBeadDiesel", dieselKw > 0.1);

    // 右栏安全与健康 2×3
    const busEl = document.getElementById("scStatBus");
    if (busEl) {
      if (busV.minPu == null) {
        busEl.textContent = "—";
        busEl.className = "";
      } else {
        busEl.textContent = `${busV.minPu.toFixed(3)}–${busV.maxPu.toFixed(3)}`;
        busEl.className = busV.minPu < 0.93 || busV.maxPu > 1.07 ? "is-danger" : (busV.minPu < 0.95 || busV.maxPu > 1.05 ? "is-warn" : "is-ok");
      }
    }
    const socEl = document.getElementById("scStatSoc");
    if (socEl) {
      socEl.textContent = avgSoc == null ? "—" : `${avgSoc.toFixed(1)}%`;
      socEl.className = avgSoc != null ? (avgSoc < 20 ? "is-danger" : avgSoc < 35 ? "is-warn" : "is-ok") : "";
    }
    setText("scStatH2", h2Meta.pressure != null ? `${h2Meta.pressure.toFixed(2)} MPa` : (h2Meta.soc != null ? `${h2Meta.soc.toFixed(1)}%` : "—"));
    const grEl = document.getElementById("scStatGreen");
    if (grEl) {
      grEl.textContent = greenShare == null ? "—" : `${greenShare.toFixed(1)}%`;
      grEl.className = greenShare != null && greenShare >= 60 ? "is-ok" : "";
    }
    const teacherSrc = trainee
      ? (snap.teacher_url || snap.source_url || (typeof state !== "undefined" ? state.teacherUrl : "") || modeText)
      : modeText;
    setText("scStatExtra1", teacherSrc || "--");
    setText("scStatLatency", textOf("uxDisplayHubPerf") || "—");

    // 渲染指令与运行事件列表
    renderScadaList(cmdItems, "scCommandList", "scCmdCount", trainee ? "commands" : "runtime");
    const rawLogs = typeof state !== "undefined" && Array.isArray(state.runtimeLogs) && state.runtimeLogs.length
      ? state.runtimeLogs
      : (Array.isArray(snap.runtime_logs) ? [...snap.runtime_logs].reverse() : []);
    const eventItems = rawLogs.slice(0, 8).map((item) => ({
      main: `${item.wall_time || item.simu_time || item.sim_time || "--"} · ${item.type || tr("运行")}`,
      meta: String(item.result || (typeof item.detail === "string" ? item.detail : "") || "").slice(0, 36),
    }));
    renderScadaList(eventItems, "scEventList", "scEventCount", trainee ? "history" : "logs");

    // 追加工况趋势点并重绘曲线
    const simTime = clock.time || textOf("simTime") || "";
    const hasPower = totalLoad > 0 || renewableKw > 0 || dieselKw > 0;
    const sig = `${simTime}|${renewableKw.toFixed(1)}|${totalLoad.toFixed(1)}|${dieselKw.toFixed(1)}`;
    if (sig !== lastTrendSig && (hasPower || trendHistory.length === 0)) {
      lastTrendSig = sig;
      const point = {
        time: simTime,
        green: renewableKw,
        load: totalLoad,
        diesel: dieselKw,
        soc: avgSoc ?? NaN,
      };
      if (
        hasPower
        && trendHistory.length === 1
        && trendHistory[0].load === 0
        && trendHistory[0].green === 0
        && trendHistory[0].diesel === 0
        && (!trendHistory[0].time || trendHistory[0].time === "00:00:00")
      ) {
        trendHistory[0] = point;
      } else {
        trendHistory.push(point);
      }
      if (trendHistory.length > TREND_MAX_POINTS) trendHistory.shift();
    }
    drawScadaTrendChart();
  }

  function bootScadaCockpit() {
    const screenSection = document.querySelector('.page-section[data-page="screen"]');
    if (screenSection) {
      buildScadaScreenDom(screenSection);
      updateScadaCockpitData();
    }
    window.__updateScadaCockpitFromSnapshot = (snap) => updateScadaCockpitData(snap);
    window.__syncScadaCockpitI18n = () => {
      syncScadaI18n(document);
      if (envModalBackdrop) syncScadaI18n(envModalBackdrop);
      updateScadaCockpitData();
    };
    document.getElementById("themeSelector")?.addEventListener("change", () => setTimeout(drawScadaTrendChart, 20));
    document.getElementById("modelSelector")?.addEventListener("change", () => {
      trendHistory.length = 0;
      lastTrendSig = "";
      setTimeout(updateScadaCockpitData, 80);
    });
    document.querySelectorAll(".page-nav button[data-nav-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.navPage === "screen") {
          setTimeout(updateScadaCockpitData, 40);
        }
      });
    });
    window.addEventListener("resize", () => {
      if (!document.hidden) setTimeout(drawScadaTrendChart, 40);
    });
    setInterval(() => {
      if (!document.hidden) updateScadaCockpitData();
    }, 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootScadaCockpit, { once: true });
  } else {
    bootScadaCockpit();
  }
})();
