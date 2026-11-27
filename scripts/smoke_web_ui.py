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
                page = browser.new_page(viewport={"width": 1440, "height": 900})
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

                for theme in ALL_THEMES:
                    page.select_option("#themeSelector", theme)
                    actual = page.evaluate("document.documentElement.dataset.theme")
                    if actual != theme:
                        errors.append(f"{label} 切换主题 {theme} 失败，实际为 {actual}")

                for lang in ALL_LANGS:
                    page.select_option("#langSelector", lang)
                    actual_lang = page.evaluate("document.documentElement.lang")
                    if actual_lang != lang:
                        errors.append(f"{label} 切换语言 {lang} 失败，实际为 {actual_lang}")

                page.select_option("#langSelector", "zh-CN")
                page.select_option("#themeSelector", "minimalist-light")

                # 验证本次升级的新增交互组件：色卡预览弹层、日/夜快切、主页 KPI+Sparkline、性能胶囊、接线图 HUD 与曲线工具条
                page.click("#uxDayNightToggleBtn")
                if page.evaluate("document.documentElement.dataset.colorScheme") != "dark":
                    errors.append(f"{label} 日/夜一键快切未切换至暗色主题")
                page.click("#uxThemeSwatchBtn")
                if not page.locator("#uxThemeSwatchPopover").is_visible():
                    errors.append(f"{label} 风格色卡预览弹层未打开")
                page.click('#uxThemeSwatchPopover .ux-theme-card[data-theme-id="arctic-frost"]')
                if page.evaluate("document.documentElement.dataset.theme") != "arctic-frost":
                    errors.append(f"{label} 色卡预览弹层点击切换 arctic-frost 失败")
                page.select_option("#themeSelector", "minimalist-light")

                if page.locator(".ux-overview-live-strip").count() == 0:
                    errors.append(f"{label} 主页缺少紧凑运行 KPI + Sparkline 条")
                if page.locator("#uxPerfTelemetryPill").count() == 0:
                    errors.append(f"{label} 顶栏缺少性能可观测胶囊")

                page.click('.page-nav button[data-nav-page="model"]')
                page.wait_for_timeout(200)
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
