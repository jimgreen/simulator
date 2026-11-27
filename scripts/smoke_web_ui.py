"""双端 Web UI 端到端冒烟验证脚本（HTTP + 可选无头 Chromium 渲染巡检）。

功能：
1. 校验教员端与学员端主页面、CSS 与所有引用 JS 静态资源均返回 HTTP 200；
2. 校验内嵌 IEC104 状态接口与学员端健康接口正常响应；
3. 若本机已安装 playwright，自动启动无头 Chromium 巡检 8 套风格预设切换、
   zh-CN / en-US / ru-RU 三语切换、关键二级子页签交互及零 console/pageerror。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any

ALL_THEMES = (
    "minimalist-light",
    "arctic-frost",
    "warm-paper",
    "slate-daylight",
    "bento-grid",
    "editorial",
    "precision-dark",
    "ocean-slate",
    "nord-dark",
    "industrial-amber",
    "glassmorphism",
    "sci-fi-cyan",
    "sci-fi-purple",
    "sci-fi-matrix",
)
ALL_LANGS = ("zh-CN", "en-US", "ru-RU")


def _http_get(url: str, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status), resp.read().decode("utf-8", errors="replace")


def run_http_smoke(simulator_url: str, trainee_url: str) -> list[str]:
    """核查双端 HTML、引用的全部 CSS/JS 资源及核心状态 API 可达性。"""
    errors: list[str] = []
    for label, base in (("教员端", simulator_url.rstrip("/")), ("学员端", trainee_url.rstrip("/"))):
        try:
            status, html = _http_get(f"{base}/")
            if status != 200 or "<html" not in html.lower():
                errors.append(f"{label} 首页响应异常：HTTP {status}")
                continue
            assets = re.findall(r'(?:src|href)="(/[^"]+)"', html)
            for asset in assets:
                if asset.startswith("//"):
                    continue
                try:
                    a_status, _ = _http_get(f"{base}{asset}")
                    if a_status != 200:
                        errors.append(f"{label} 资源 {asset} 返回 HTTP {a_status}")
                except Exception as exc:
                    errors.append(f"{label} 资源 {asset} 请求失败：{exc}")
        except Exception as exc:
            errors.append(f"{label} ({base}) 不可达：{exc}")

    # 校验教员端 IEC104 状态与学员端健康检查
    try:
        st, body = _http_get(f"{simulator_url.rstrip('/')}/api/simulator104/status")
        data = json.loads(body) if st == 200 else {}
        if st != 200 or not isinstance(data, dict):
            errors.append(f"IEC104 状态接口响应异常：HTTP {st}")
    except Exception as exc:
        errors.append(f"IEC104 状态接口请求失败：{exc}")

    try:
        st, body = _http_get(f"{trainee_url.rstrip('/')}/api/health")
        data = json.loads(body) if st == 200 else {}
        if st != 200 or not isinstance(data, dict):
            errors.append(f"学员端健康接口响应异常：HTTP {st}")
    except Exception as exc:
        errors.append(f"学员端健康接口请求失败：{exc}")

    return errors


def run_playwright_smoke(simulator_url: str, trainee_url: str) -> tuple[bool, list[str]]:
    """若已安装 Playwright，则启动无头浏览器走查双端 8 主题、3 语言与控制台零报错。"""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return False, []

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for label, url in (("教员端", simulator_url.rstrip("/")), ("学员端", trainee_url.rstrip("/"))):
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                console_errors: list[str] = []
                page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
                page.on(
                    "console",
                    lambda msg: console_errors.append(f"console.{msg.type}: {msg.text}")
                    if msg.type == "error"
                    else None,
                )
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(800)

                def assert_topbar_geometry(lang_tag: str) -> None:
                    geo = page.evaluate(
                        """() => {
                            const header = document.querySelector('header.topbar');
                            if (!header) return { ok: false, reason: 'missing header.topbar' };
                            const hr = header.getBoundingClientRect();
                            if (header.scrollWidth > header.clientWidth + 2) {
                                return { ok: false, reason: `topbar overflow ${header.scrollWidth} > ${header.clientWidth}` };
                            }
                            if (hr.height > 62) {
                                return { ok: false, reason: `topbar wrapped height=${hr.height}` };
                            }
                            const items = [
                                header.querySelector('.brand'),
                                header.querySelector('#uxTopbarCrest'),
                                ...Array.from(header.querySelectorAll('.ux-topbar-hubs > .ux-hub, .ux-topbar-hubs > #scImmersiveToggle')),
                            ].filter(Boolean).map((el) => {
                                const r = el.getBoundingClientRect();
                                return { id: el.id || el.className, left: r.left, right: r.right, top: r.top, bottom: r.bottom };
                            });
                            for (const it of items) {
                                if (it.right > hr.right + 2 || it.left < hr.left - 2) {
                                    return { ok: false, reason: `${it.id} clipped (${it.left.toFixed(0)}..${it.right.toFixed(0)} vs ${hr.right.toFixed(0)})` };
                                }
                            }
                            for (let i = 0; i < items.length; i += 1) {
                                for (let j = i + 1; j < items.length; j += 1) {
                                    const a = items[i], b = items[j];
                                    const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                                    const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                                    if (overlapX > 2 && overlapY > 2) {
                                        return { ok: false, reason: `${a.id} overlaps ${b.id} by ${overlapX.toFixed(1)}px` };
                                    }
                                }
                            }
                            return { ok: true, count: items.length, height: hr.height };
                        }"""
                    )
                    if not geo.get("ok"):
                        errors.append(f"{label} ({lang_tag}, 1280px) 顶栏几何校验失败：{geo.get('reason')}")

                # 展开「显示与工具」悬浮胶囊以操作原生风格与语言选择器
                page.click("#uxDisplayHubTrigger")
                page.wait_for_timeout(120)
                for theme in ALL_THEMES:
                    page.select_option("#themeSelector", theme)
                    actual = page.evaluate("document.documentElement.dataset.theme")
                    if actual != theme:
                        errors.append(f"{label} 切换主题 {theme} 失败，实际为 {actual}")

                for lang in ALL_LANGS:
                    page.click("#uxDisplayHubTrigger")
                    page.wait_for_timeout(80)
                    page.select_option("#langSelector", lang)
                    page.wait_for_timeout(120)
                    actual_lang = page.evaluate("document.documentElement.lang")
                    if actual_lang != lang:
                        errors.append(f"{label} 切换语言 {lang} 失败，实际为 {actual_lang}")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(60)
                    assert_topbar_geometry(lang)

                page.click("#uxDisplayHubTrigger")
                page.wait_for_timeout(180)
                page.select_option("#langSelector", "zh-CN")
                page.select_option("#themeSelector", "minimalist-light")

                # 验证顶栏三胶囊交互：日/夜快切、内嵌色卡直选、模型悬浮面板、主页 KPI+Sparkline、性能胶囊、接线图 HUD 与曲线工具条
                page.click("#uxDayNightToggleBtn")
                if page.evaluate("document.documentElement.dataset.colorScheme") != "dark":
                    errors.append(f"{label} 日/夜一键快切未切换至暗色主题")
                page.click('#uxDisplayHubSwatches .ux-theme-card[data-theme-id="arctic-frost"]')
                if page.evaluate("document.documentElement.dataset.theme") != "arctic-frost":
                    errors.append(f"{label} 显示管理悬浮面板色卡点击切换 arctic-frost 失败")
                page.select_option("#themeSelector", "minimalist-light")
                page.keyboard.press("Escape")
                page.wait_for_timeout(100)

                page.click("#uxModelHubTrigger")
                page.wait_for_timeout(180)
                if not page.locator("#uxModelHubPopover").is_visible():
                    errors.append(f"{label} 模型管理悬浮面板未打开")
                page.keyboard.press("Escape")
                page.wait_for_timeout(100)

                # 校验侧边导航拥有独立「大屏主画面」与「能流总览」目录项，默认首屏呈现 SCADA 大屏幕主画面且无页内切换按钮
                if page.locator('.page-nav button[data-nav-page="screen"]').count() == 0:
                    errors.append(f"{label} 侧边目录缺少独立的「大屏主画面」入口")
                if page.locator('.page-nav button[data-nav-page="overview"]').count() == 0:
                    errors.append(f"{label} 侧边目录缺少独立的「能流总览」入口")
                if not page.locator("#uxTopbarCrest").is_visible():
                    errors.append(f"{label} 顶栏缺少全站共享中央主桥徽标 #uxTopbarCrest")
                if not page.locator("#polarScadaScreen").is_visible():
                    errors.append(f"{label} 默认首屏未显示独立 SCADA 大屏幕主画面")
                if page.locator("#polarScadaScreen .sc-header").count() > 0:
                    errors.append(f"{label} 大屏内部仍残留重复的 .sc-header 顶栏")
                if page.locator("#polarScadaScreen .sc-view-switcher").count() > 0:
                    errors.append(f"{label} 大屏顶栏仍残留页内视图切换器（应已拆分为独立侧边目录页面）")
                if page.locator("#polarScadaScreen .sc-node").count() != 6:
                    errors.append(f"{label} SCADA 大屏全息能流台座数量应为 6")
                if page.locator("#scEnvPress").count() == 0 or page.locator("#scEnvHum").count() == 0 or page.locator("#scCoupleWind").count() == 0 or page.locator("#scClimateRegime").count() == 0:
                    errors.append(f"{label} SCADA 大屏缺少 6 维南极气象或能源耦合指标条")
                if label == "教员端":
                    if page.locator("#scOpenEnvInjectBtn").count() == 0:
                        errors.append(f"{label} 大屏缺少极端气象工况注入按钮")
                    else:
                        page.click("#scOpenEnvInjectBtn")
                        page.wait_for_timeout(120)
                        if not page.locator("#scEnvInjectModal").is_visible():
                            errors.append(f"{label} 点击工况注入未弹出南极气象注入面板")
                        else:
                            page.click('#scEnvInjectModal [data-sc-preset="blizzard"]')
                            wind_val = page.locator("#scInWind").input_value()
                            temp_val = page.locator("#scInTemp").input_value()
                            if float(wind_val or 0) < 25 or float(temp_val or 0) > -30:
                                errors.append(f"{label} 暴风雪切出预设参数回填异常: wind={wind_val}, temp={temp_val}")
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(80)
                page.click("#scImmersiveToggle")
                if page.evaluate("document.documentElement.dataset.scadaImmersive") != "true":
                    errors.append(f"{label} SCADA 大屏沉浸全屏切换失败")
                page.click("#scImmersiveToggle")

                # 校验左栏双模式（内嵌 / 悬浮）与双模式下均可隐藏与呼出
                if page.locator("#uxSidebarToggleBtn").count() == 0 or page.locator("#uxSidebarModeBtn").count() == 0:
                    errors.append(f"{label} 缺少左栏显隐或模式切换按钮")
                else:
                    # 1) 内嵌模式下隐藏与恢复
                    page.click("#uxSidebarHideBtn")
                    page.wait_for_timeout(100)
                    if page.evaluate("document.documentElement.dataset.sidebarHidden") != "true" or page.locator("#appSidebar").is_visible():
                        errors.append(f"{label} 内嵌模式下左栏未能隐藏")
                    page.click("#uxSidebarToggleBtn")
                    page.wait_for_timeout(100)
                    if page.evaluate("document.documentElement.dataset.sidebarHidden") != "false" or not page.locator("#appSidebar").is_visible():
                        errors.append(f"{label} 内嵌模式下通过顶栏按钮未能恢复显示左栏")
                    # 2) 切换悬浮模式，校验脱离文档流(position=fixed)且同样可隐藏/呼出
                    page.click("#uxSidebarModeBtn")
                    page.wait_for_timeout(140)
                    overlay_pos = page.evaluate("getComputedStyle(document.getElementById('appSidebar')).position")
                    if page.evaluate("document.documentElement.dataset.sidebarMode") != "overlay" or overlay_pos != "fixed":
                        errors.append(f"{label} 切换左栏悬浮模式失败（position={overlay_pos}）")
                    page.click("#uxSidebarHideBtn")
                    page.wait_for_timeout(200)
                    if page.evaluate("document.documentElement.dataset.sidebarHidden") != "true":
                        errors.append(f"{label} 悬浮模式下左栏未能隐藏")
                    page.click("#uxSidebarToggleBtn")
                    page.wait_for_timeout(140)
                    if page.evaluate("document.documentElement.dataset.sidebarHidden") != "false":
                        errors.append(f"{label} 悬浮模式下通过顶栏按钮未能重新呼出左栏")
                    # 切回内嵌显示态继续后续巡检
                    page.click("#uxSidebarModeBtn")
                    page.wait_for_timeout(120)

                # 通过侧边独立目录点击进入「能流总览」页面（/overview），校验 KPI 条同步及高度 <=44px
                page.click('.page-nav button[data-nav-page="overview"]')
                page.wait_for_timeout(200)
                if not page.evaluate("location.pathname.endsWith('/overview')"):
                    errors.append(f"{label} 点击独立目录「能流总览」后路径未切换至 /overview")
                if page.locator("#polarScadaScreen:visible").count() > 0:
                    errors.append(f"{label} 切换至独立「能流总览」后仍显示大屏画面")
                kpi_first = page.locator(".ux-overview-kpi span").first.inner_text().strip()
                if kpi_first != "绿电占比":
                    errors.append(f"{label} 切回中文后能流总览 KPI 文案未同步，实际为 {kpi_first!r}")

                if page.locator(".ux-overview-live-strip").count() == 0:
                    errors.append(f"{label} 能流总览缺少紧凑运行 KPI + Sparkline 条")
                else:
                    strip_h = page.locator(".ux-overview-live-strip").first.bounding_box()["height"]
                    spark_h = page.locator("canvas.ux-overview-sparkline").first.bounding_box()["height"]
                    if strip_h > 44:
                        errors.append(f"{label} 能流总览 KPI 条被异常拉高：height={strip_h:.1f}px（预期 <=44px）")
                    if spark_h > 32:
                        errors.append(f"{label} 能流总览 Sparkline 画布被全局 canvas 规则拉高：height={spark_h:.1f}px（预期 <=32px）")
                page.click('.page-nav button[data-nav-page="screen"]')
                page.wait_for_timeout(120)
                if not page.locator("#polarScadaScreen").is_visible():
                    errors.append(f"{label} 通过侧边目录切回「大屏主画面」失败")
                if page.locator("#uxPerfTelemetryPill").count() == 0:
                    errors.append(f"{label} 缺少性能可观测胶囊")

                page.click('.page-nav button[data-nav-page="model"]')
                page.wait_for_timeout(200)
                # 校验旧时钟条已彻底隐藏，无双时钟残影
                if page.locator("header.topbar .clock-strip:visible").count() > 0:
                    errors.append(f"{label} 顶栏仍残留可见的旧 .clock-strip，存在双时钟残影")
                # 切到「人工修改」子页签，校验面板满屏铺开（宽 >= 85% 主区宽，高 >= 70% 主区高）且保留表头
                page.click('button[data-model-subtab="manual-changes"]')
                page.wait_for_timeout(160)
                manual_geo = page.evaluate(
                    """() => {
                        const main = document.querySelector('.page-main');
                        const panel = document.querySelector('[data-model-subtab-pane="manual-changes"] .manual-definition-changes-panel');
                        if (!main || !panel) return { ok: false, reason: 'missing manual panel' };
                        const mr = main.getBoundingClientRect();
                        const pr = panel.getBoundingClientRect();
                        const wRatio = mr.width > 0 ? pr.width / mr.width : 0;
                        const hRatio = mr.height > 0 ? pr.height / mr.height : 0;
                        if (wRatio < 0.85) return { ok: false, reason: `width ratio ${wRatio.toFixed(2)} < 0.85` };
                        if (hRatio < 0.70) return { ok: false, reason: `height ratio ${hRatio.toFixed(2)} < 0.70` };
                        return { ok: true, wRatio, hRatio };
                    }"""
                )
                if not manual_geo.get("ok"):
                    errors.append(f"{label} 人工修改面板未铺满工作区：{manual_geo.get('reason')}")
                page.click('button[data-model-subtab="params"]')
                page.wait_for_timeout(120)
                if page.locator(".model-param-tabs").count() > 0:
                    if page.locator(".ux-tabs-scroll-shell").count() == 0:
                        errors.append(f"{label} 电网模型页缺少横向分类标签步进容器")
                else:
                    # 若当前模型服务尚未启动，注入临时 .model-param-tabs 验证 MutationObserver 自动装配步进外壳
                    ok_shell = page.evaluate(
                        """() => {
                            const host = document.getElementById('modelParamTable');
                            if (!host) return false;
                            const probe = document.createElement('div');
                            probe.className = 'model-param-tabs';
                            probe.dataset.smokeProbe = '1';
                            probe.innerHTML = '<button type="button" class="model-param-tab">A</button>';
                            host.appendChild(probe);
                            return true;
                        }"""
                    )
                    page.wait_for_timeout(120)
                    if not ok_shell or page.locator(".ux-tabs-scroll-shell").count() == 0:
                        errors.append(f"{label} 电网模型页动态渲染分类标签未自动装配步进容器")
                    page.evaluate(
                        """() => {
                            document.querySelector('.ux-tabs-scroll-shell:has([data-smoke-probe="1"])')?.remove();
                            document.querySelector('[data-smoke-probe="1"]')?.remove();
                        }"""
                    )

                page.click('.page-nav button[data-nav-page="diagram"]')
                page.wait_for_timeout(250)
                if page.locator(".ux-diagram-hud").count() == 0 or page.locator(".ux-diagram-minimap").count() == 0:
                    errors.append(f"{label} 接线图页缺少快搜 HUD 或缩略图 Minimap")

                page.click('.page-nav button[data-nav-page="curves"]')
                page.wait_for_timeout(200)
                if page.locator(".ux-chart-tools").count() == 0:
                    errors.append(f"{label} 曲线页缺少 PNG/CSV 导出与缩放工具条")

                if page.locator('.page-nav button[data-nav-page="renewable"]').count() > 0:
                    page.click('.page-nav button[data-nav-page="renewable"]')
                    page.wait_for_timeout(300)
                    ren_check = page.evaluate(
                        """() => {
                            const tools = document.querySelector('[data-page="renewable"] .ux-chart-tools');
                            const legend = document.getElementById('renewableTrendLegend');
                            if (!tools) return { ok: false, reason: 'missing .ux-chart-tools' };
                            if (legend && !legend.hidden) {
                                const tr = tools.getBoundingClientRect();
                                const lr = legend.getBoundingClientRect();
                                const ox = Math.min(tr.right, lr.right) - Math.max(tr.left, lr.left);
                                const oy = Math.min(tr.bottom, lr.bottom) - Math.max(tr.top, lr.top);
                                if (ox > 1 && oy > 1) return { ok: false, reason: `tools overlaps legend (${ox.toFixed(1)}x${oy.toFixed(1)})` };
                                const item = legend.querySelector('.renewable-trend-inline-legend-item');
                                if (item) {
                                    const ir = item.getBoundingClientRect();
                                    if (ir.height > 26) return { ok: false, reason: `legend item too tall (${ir.height.toFixed(1)}px)` };
                                    if (ir.bottom > lr.bottom + 2) return { ok: false, reason: 'legend item clipped vertically' };
                                }
                            }
                            return { ok: true };
                        }"""
                    )
                    if not ren_check.get("ok"):
                        errors.append(f"{label} 新能源控制曲线区防遮挡校验失败：{ren_check.get('reason')}")

                if console_errors:
                    errors.extend(f"{label} {item}" for item in console_errors[:10])
                page.close()
        finally:
            browser.close()
    return True, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="极地微电网双端 Web UI 冒烟巡检脚本")
    parser.add_argument("--simulator-url", default="http://127.0.0.1:18710", help="教员端地址")
    parser.add_argument("--trainee-url", default="http://127.0.0.1:18720", help="学员端地址")
    parser.add_argument("--skip-browser", action="store_true", help="跳过 Playwright 浏览器渲染巡检")
    args = parser.parse_args()

    errors = run_http_smoke(args.simulator_url, args.trainee_url)
    if not args.skip_browser:
        ran_pw, pw_errors = run_playwright_smoke(args.simulator_url, args.trainee_url)
        if ran_pw:
            print(f"[INFO] 已完成无头 Chromium {len(ALL_THEMES)} 主题 + {len(ALL_LANGS)} 语言渲染巡检。")
            errors.extend(pw_errors)
        else:
            print("[INFO] 未检测到 playwright，已跳过无头浏览器渲染步骤（仅执行 HTTP 全资源冒烟）。")

    if errors:
        for item in errors:
            print(f"[FAIL] {item}", file=sys.stderr)
        return 1
    print("[OK] 双端 Web UI 冒烟检查全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
