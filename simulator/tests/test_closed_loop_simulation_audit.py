"""针对模拟台时序闭环仿真 6 项改造的专项回归测试。"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
SHARED_ROOT = REPO_ROOT / "shared"
TRAINEE_ROOT = REPO_ROOT / "trainee"
for _entry in (str(TRAINEE_ROOT), str(APP_ROOT), str(SHARED_ROOT)):
    if _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)

import simu_loop  # noqa: E402
from simu import service  # noqa: E402
from simu.service_parts.clock_step import PowerFlowExecution  # noqa: E402
from src.hybrid_power_system_analysis.efile_read import EBook  # noqa: E402


def _resolve_active_model_dir() -> Path:
    settings = json.loads((APP_ROOT / "startup.json").read_text(encoding="utf-8"))
    data_dir = (APP_ROOT / settings.get("data_dir", "data")).resolve()
    models_dir = data_dir / "models"
    if (models_dir / "秦岭站" / "model.e").is_file():
        return models_dir / "秦岭站"
    candidates = sorted(p.parent for p in models_dir.glob("*/model.e"))
    if candidates:
        return candidates[0]
    return APP_ROOT


def _make_simulator(tmp_dir: str) -> service.PolarMicrogridSimulator:
    model_dir = _resolve_active_model_dir()
    return service.PolarMicrogridSimulator(
        sim_dir=model_dir,
        runtime_dir=Path(tmp_dir) / "runtime",
        model_id=model_dir.name,
        model_name=model_dir.name,
        noise_std=0.0,
        random_seed=7,
    )


class ClosedLoopSimulationAuditTests(unittest.TestCase):
    def test_storage_and_hydrogen_overlimit_emit_operating_warnings_without_hiding_errors(self) -> None:
        """验证电储 SOC 越界与氢储罐过充/过放保留暴露态，并输出结构化运行告警。"""
        model_dir = _resolve_active_model_dir()
        model_book = EBook(model_dir / "model.e")
        stat_book = EBook(model_dir / "stat.e") if (model_dir / "stat.e").is_file() else EBook({})
        dev_define = simu_loop._capability_define_book(model_book, None)

        # 1. 构网/平衡储能持续过充 -> SOC 越上限被钳位，但显式产生运行告警
        simu_loop._ensure_storage_soc_rows_book(stat_book, model_book, dev_define)
        soc_block = simu_loop._storage_soc_block(stat_book)
        self.assertIsNotNone(soc_block)
        targets = simu_loop._storage_target_rows(model_book, dev_define)
        self.assertTrue(targets)
        dev_type, source_row, _storage_name, define, _pos = targets[0]
        dev_name = str(source_row.get("name", ""))
        source_row["control_type"] = "V_THETA"
        soc_max = float((define or {}).get("soc_max", 0.9) or 0.9)
        for row in soc_block.data:
            if str(row.get("name", row.get("dev_name", ""))).strip() == dev_name:
                row["soc_curr"] = simu_loop.format_number(soc_max)
                break

        warnings: list[dict] = []
        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            60.0,
            dev_define,
            storage_power_by_name={(dev_type, dev_name): -120.0},
            operating_warnings=warnings,
        )
        overcharge_warnings = [w for w in warnings if w.get("code") == "storage_soc_overcharge"]
        self.assertEqual(len(overcharge_warnings), 1)
        self.assertEqual(overcharge_warnings[0]["dev_name"], dev_name)
        self.assertEqual(overcharge_warnings[0]["role"], "构网/平衡储能")
        self.assertGreater(overcharge_warnings[0]["value"], soc_max)

        # 2. 氢储罐默认初态正常小流量充放 -> 不误报欠压/超压/储量越界
        simu_loop.ensure_hydrogen_storage_state_rows_book(stat_book, model_book)
        hydro_rows = simu_loop._hydrogen_storage_rows(model_book)
        if not hydro_rows:
            model_book = EBook(APP_ROOT / "model.e")
            stat_book = EBook(APP_ROOT / "stat.e")
            simu_loop.ensure_hydrogen_storage_state_rows_book(stat_book, model_book)
            hydro_rows = simu_loop._hydrogen_storage_rows(model_book)
        self.assertTrue(hydro_rows)
        tank_name = str(hydro_rows[0]["name"])
        rated_cap = simu_loop._hydrogen_storage_rated_capacity(hydro_rows[0]) or 1000.0
        normal_snapshot = SimpleNamespace(
            fluid_results={"hydro": SimpleNamespace(storages={tank_name: SimpleNamespace(flow=5.0)})}
        )
        normal_warnings: list[dict] = []
        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            60.0,
            snapshot=normal_snapshot,
            operating_warnings=normal_warnings,
        )
        self.assertEqual(normal_warnings, [])

        # 3. 氢储罐过度放氢跌破 0 -> 保留负储量/负气压暴露错误，同时产生 error 级运行告警
        hydro_block = simu_loop._hydrogen_storage_state_block(stat_book)
        self.assertIsNotNone(hydro_block)
        hydro_block.data[0]["gas_quantity"] = "5"
        hydro_block.data[0]["pressure"] = "0.01"
        hydro_block.data[0]["soc"] = "0.005"
        overdischarge_snapshot = SimpleNamespace(
            fluid_results={"hydro": SimpleNamespace(storages={tank_name: SimpleNamespace(flow=60.0)})}
        )
        overdischarge_warnings: list[dict] = []
        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            3600.0,
            snapshot=overdischarge_snapshot,
            operating_warnings=overdischarge_warnings,
        )
        self.assertLess(float(hydro_block.data[0]["gas_quantity"]), 0.0)
        self.assertLess(float(hydro_block.data[0]["pressure"]), 0.0)
        codes = {w["code"] for w in overdischarge_warnings}
        self.assertIn("hydro_storage_negative_quantity", codes)
        self.assertIn("hydro_storage_negative_pressure", codes)
        self.assertTrue(any(w["severity"] == "error" for w in overdischarge_warnings))

        # 4. 氢储罐过度充氢超过额定容量 -> 保留超容储量，同时产生超容告警
        hydro_block.data[0]["gas_quantity"] = simu_loop.format_number(rated_cap - 5.0)
        hydro_block.data[0]["soc"] = simu_loop.format_number((rated_cap - 5.0) / rated_cap)
        overcharge_snapshot = SimpleNamespace(
            fluid_results={"hydro": SimpleNamespace(storages={tank_name: SimpleNamespace(flow=-50.0)})}
        )
        overcharge_hydro_warnings: list[dict] = []
        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            3600.0,
            snapshot=overcharge_snapshot,
            operating_warnings=overcharge_hydro_warnings,
        )
        self.assertGreater(float(hydro_block.data[0]["gas_quantity"]), rated_cap)
        self.assertIn("hydro_storage_overcapacity", {w["code"] for w in overcharge_hydro_warnings})

    def test_instructor_step_logs_operating_warnings(self) -> None:
        """验证教员台在 step 提交结果时将 operating_warnings 写入 latest_result 与运行日志。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            base_exec = sim._execute_kernel(sim._make_config(period_seconds=1.0))
            fake_warnings = [
                {
                    "code": "hydro_storage_negative_quantity",
                    "severity": "error",
                    "dev_type": "HydroStorage",
                    "dev_name": "集装格式储氢罐-1",
                    "metric": "GAS_QUANTITY",
                    "value": -12.5,
                    "message": "氢储罐 集装格式储氢罐-1 过度放氢导致储量跌破下限：当前储氢量 -12.5 Nm³",
                }
            ]
            patched_result = simu_loop.SimulationResult(
                real_file=base_exec.result.real_file,
                scada_file=base_exec.result.scada_file,
                updated=base_exec.result.updated,
                missing=base_exec.result.missing,
                overlay_updates=base_exec.result.overlay_updates,
                solver_info=base_exec.result.solver_info,
                model_book=base_exec.result.model_book,
                measurement_definitions=base_exec.result.measurement_definitions,
                real_rows=base_exec.result.real_rows,
                scada_rows=base_exec.result.scada_rows,
                device_states=base_exec.result.device_states,
                missing_measurements=base_exec.result.missing_measurements,
                operating_warnings=fake_warnings,
            )
            patched_exec = PowerFlowExecution(
                result=patched_result,
                runtime_stat_book=base_exec.runtime_stat_book,
                compute_seconds=base_exec.compute_seconds,
                round_trip_seconds=base_exec.round_trip_seconds,
                worker_pid=base_exec.worker_pid,
                mode=base_exec.mode,
            )
            with patch.object(sim, "_execute_kernel_with_power_flow_backtrack", return_value=(patched_exec, None)):
                sim.step(advance_minutes=1.0 / 60.0)

            self.assertEqual(len(sim.latest_result.get("operating_warnings", [])), 1)
            alarm_logs = [
                entry for entry in sim.runtime_logs if entry.get("type") == "运行告警"
            ]
            self.assertTrue(alarm_logs)
            self.assertEqual(alarm_logs[-1]["level"], "error")
            self.assertIn("集装格式储氢罐-1", alarm_logs[-1]["target"])

    def test_remote_adjustment_execution_rolls_back_on_power_flow_failure(self) -> None:
        """验证潮流失败时遥调执行状态（含 force_target_once）与仿真时钟均完整回滚。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.step(advance_minutes=1.0 / 60.0)
            diesel_rows = [
                row
                for row in sim.source_model_book.data["ACGenerator"].data
                if "diesel" in str(row.get("dev_type", "")).lower()
            ]
            self.assertTrue(diesel_rows)
            diesel_name = str(diesel_rows[0]["name"])
            key = ("ACGenerator", diesel_name, "p_set")
            sim.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": "ACGenerator",
                            "dev_name": diesel_name,
                            "set_type": "p_set",
                            "set_value": 120.0,
                        }
                    ]
                },
                source="trainee",
            )
            sim._remote_adjustment_execution[key] = {
                "executed_value": 80.0,
                "target_value": 120.0,
                "last_cycle_token": None,
                "force_target_once": True,
            }
            before_minute = sim.clock.absolute_minute
            with patch.object(
                sim,
                "_execute_kernel_with_power_flow_backtrack",
                side_effect=RuntimeError("mock power flow divergence"),
            ):
                with self.assertRaises(RuntimeError):
                    sim.step(advance_minutes=1.0 / 60.0)

            self.assertEqual(sim.clock.absolute_minute, before_minute)
            self.assertTrue(sim._remote_adjustment_execution[key].get("force_target_once"))
            self.assertEqual(sim._remote_adjustment_execution[key]["executed_value"], 80.0)

    def test_remote_adjustment_response_scales_with_step_period_and_renewable_baseline(self) -> None:
        """验证遥调一阶响应随步长 Δt 换算，且新能源遥调在夜间实发 0 时不被卡死在 0.7*target。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.remote_adjustment_response_ratio = 0.7
            self.assertAlmostEqual(
                sim._effective_remote_adjustment_response_ratio(0.7, 1.0),
                0.7,
                places=9,
            )
            self.assertAlmostEqual(
                sim._effective_remote_adjustment_response_ratio(0.7, 60.0),
                1.0 - (0.3 ** 60.0),
                places=12,
            )
            self.assertGreater(
                sim._effective_remote_adjustment_response_ratio(0.7, 60.0),
                0.999999,
            )

            # 定位一台光伏/风机（ACGenerator 或 DCGenerator），模拟夜间实发为 0，放开上限到 p_max
            ren_dev_type = ""
            ren_name = ""
            target_kw = 20.0
            for block_name in ("ACGenerator", "DCGenerator"):
                block = sim.source_model_book.data.get(block_name)
                if block is None:
                    continue
                for row in block.data:
                    if any(tok in str(row.get("dev_type", "")).lower() for tok in ("pv", "wind")):
                        ren_dev_type = block_name
                        ren_name = str(row["name"])
                        p_max_val = simu_loop._safe_float(row.get("p_max"), 20.0) or 20.0
                        target_kw = float(p_max_val)
                        break
                if ren_name:
                    break
            self.assertTrue(ren_name)
            self.assertGreater(target_kw, 0.0)
            key = (ren_dev_type, ren_name, "p_set")
            self.assertTrue(sim._is_renewable_active_power_adjustment(key))
            sim.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": ren_dev_type,
                            "dev_name": ren_name,
                            "set_type": "p_set",
                            "set_value": target_kw,
                        }
                    ]
                },
                source="trainee",
            )
            sim._materialize_active_control_commands(0.0)
            # 构造夜间实测出力为 0 的真值行
            sim.latest_real_rows = [
                ["1", f"{ren_name}_P", ren_dev_type, ren_name, "P_GEN", "1", "1", "0.0"]
            ]
            sim._remote_adjustment_execution[key] = {
                "executed_value": 0.0,
                "last_cycle_token": 0,
            }
            executed_trace: list[float] = []
            for cycle in range(1, 8):
                _stat, _yt, next_exec = sim._remote_adjustment_boundary_books(
                    0.0,
                    cycle,
                    period_seconds=1.0,
                    return_next_state=True,
                )
                sim._remote_adjustment_execution = next_exec
                executed_trace.append(float(next_exec[key]["executed_value"]))
            # 每拍应严格单调抬升并快速逼近 target_kw，而不是每拍都卡在 0.7 * target_kw
            self.assertAlmostEqual(executed_trace[0], 0.7 * target_kw, places=6)
            self.assertGreater(executed_trace[1], 0.9 * target_kw)
            self.assertGreater(executed_trace[-1], 0.999 * target_kw)

    def test_crossed_cycle_start_increments_run_id_without_exposing_empty_frame(self) -> None:
        """验证跨日周期归零递增 run_id，且不会瞬间抹空 latest_measurements。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.clock.simulation_mode = "day"
            sim.clock.absolute_minute = 1439.5
            sim.clock.minute = 1439.5
            old_run_id = sim.clock.run_id

            sim.step(advance_minutes=1.0)

            self.assertEqual(sim.clock.run_id, old_run_id + 1)
            self.assertTrue(sim.latest_measurements.get("real"))
            self.assertTrue(sim.latest_measurements.get("scada"))
            self.assertFalse(sim._automatic_runtime_state_invalidated)

    def test_scada_noise_clamps_non_negative_zero_but_preserves_negative_truth_and_clock_monotonic(self) -> None:
        """验证非负物理量零值不被噪声抖负、真值负值不被掩盖，且切换倍率时钟单调连续。"""
        class _NegativeNoiseRng(random.Random):
            def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
                return mu - abs(sigma) * 3.0

        rows = [
            ["1", "wind_speed", "Weather", "weather", "WIND_SPEED", "1", "1", "0"],
            ["2", "solar_irrad", "Weather", "weather", "SOLAR_IRRADIANCE", "1", "1", "0"],
            ["3", "tank_qty_neg", "HydroStorage", "集装格式储氢罐-1", "GAS_QUANTITY", "1", "1", "-15"],
            ["4", "tank_press_neg", "HydroStorage", "集装格式储氢罐-1", "PRESSURE", "1", "1", "-0.03"],
            ["5", "gen_p", "ACGenerator", "G1", "P_GEN", "1", "1", "0"],
        ]
        noisy = simu_loop.add_noise_to_rows(rows, noise_std=0.5, rng=_NegativeNoiseRng())
        self.assertEqual(float(noisy[0][7]), 0.0)
        self.assertEqual(float(noisy[1][7]), 0.0)
        # 氢储罐真值本身为负时，不得截断为 0 掩盖错误策略
        self.assertLess(float(noisy[2][7]), -15.0)
        self.assertLess(float(noisy[3][7]), -0.03)
        # 双向有功功率允许负值
        self.assertLess(float(noisy[4][7]), 0.0)

        # 验证切换倍率时时钟连续单调，不发生倒退或跳空
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.clock.speed = 1.0
            sim.clock.absolute_minute = round(5.0 / 60.0, 9)
            sim.clock.minute = sim.clock.absolute_minute
            sim.control_clock({"action": "faster"})
            self.assertAlmostEqual(sim.clock.absolute_minute, round(5.0 / 60.0, 9), places=9)
            sim.set_system_parameters({"clock_speed": 60})
            self.assertAlmostEqual(sim.clock.absolute_minute, round(5.0 / 60.0, 9), places=9)

    def test_fixed_boundaries_preserves_dynamic_hydro_storage_positive_pressure(self) -> None:
        """验证 repair_fixed_boundary_setpoints 保留氢储罐越界动态正压，仅在缺失或 <=0 时兜底。"""
        from simu.fixed_boundaries import repair_fixed_boundary_setpoints

        model_book = EBook(APP_ROOT / "model.e")
        hydro_rows = simu_loop._hydrogen_storage_rows(model_book)
        self.assertTrue(hydro_rows)

        # 欠压正值（0.5 < pressure_min=2）保持原值不被篡改回中值 23.5
        under_book = simu_loop._clone_ebook(model_book)
        under_book.data["HydroStorage"].data[0]["pressure_set"] = "0.5"
        repair_fixed_boundary_setpoints(under_book)
        self.assertAlmostEqual(float(under_book.data["HydroStorage"].data[0]["pressure_set"]), 0.5, places=6)

        # 超压正值（52.0 > pressure_max=45）保持原值
        over_book = simu_loop._clone_ebook(model_book)
        over_book.data["HydroStorage"].data[0]["pressure_set"] = "52.0"
        repair_fixed_boundary_setpoints(over_book)
        self.assertAlmostEqual(float(over_book.data["HydroStorage"].data[0]["pressure_set"]), 52.0, places=6)

        # 跌破零值（-0.2 <= 0）时才兜底为正压参考供流体求解器求解
        neg_book = simu_loop._clone_ebook(model_book)
        neg_book.data["HydroStorage"].data[0]["pressure_set"] = "-0.2"
        repair_fixed_boundary_setpoints(neg_book)
        self.assertGreater(float(neg_book.data["HydroStorage"].data[0]["pressure_set"]), 0.0)

    def test_backtrack_respects_renewable_anchor_and_concurrent_new_command(self) -> None:
        """验证新能源回溯锚点不被夜间零出力压回 0，且回溯提交保留并发新指令并不漏写已弹出键。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            ren_dev_type = ""
            ren_name = ""
            target_kw = 20.0
            for block_name in ("ACGenerator", "DCGenerator"):
                block = sim.source_model_book.data.get(block_name)
                if block is None:
                    continue
                for row in block.data:
                    if any(tok in str(row.get("dev_type", "")).lower() for tok in ("pv", "wind")):
                        ren_dev_type = block_name
                        ren_name = str(row["name"])
                        target_kw = float(simu_loop._safe_float(row.get("p_max"), 20.0) or 20.0)
                        break
                if ren_name:
                    break
            self.assertTrue(ren_name)
            ren_key = (ren_dev_type, ren_name, "p_set")
            sim.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": ren_dev_type,
                            "dev_name": ren_name,
                            "set_type": "p_set",
                            "set_value": target_kw,
                        }
                    ]
                },
                source="trainee",
            )
            sim._materialize_active_control_commands(0.0)
            sim.latest_real_rows = [
                ["1", f"{ren_name}_P", ren_dev_type, ren_name, "P_GEN", "1", "1", "0.0"]
            ]
            sim._remote_adjustment_execution[ren_key] = {
                "executed_value": target_kw,
                "target_value": target_kw,
                "last_cycle_token": 1,
            }
            cfg = sim._make_config(
                period_seconds=1.0,
                dev_stat_book=simu_loop._clone_ebook(sim.runtime_stat_book),
                yt_ctrl_book=simu_loop._clone_ebook(sim.yt_ctrl_book),
            )
            # 实测 0 但已执行设点已等于目标上限 -> 不应被加入回溯列表压回 0
            candidates = sim._power_flow_backtrack_candidates(cfg, 0.0)
            self.assertNotIn(ren_key, candidates)

            # 验证回溯提交：1) 原已弹出的 key_popped 被重新写入 accepted；2) 并发修改的 key_concurrent 不被覆盖
            key_popped = ("ACGenerator", "G_POP", "p_set")
            key_concurrent = ("ACGenerator", "G_CONC", "p_set")
            before_exec = {
                key_popped: {"executed_value": 10.0, "target_value": 50.0, "last_cycle_token": 1},
                key_concurrent: {"executed_value": 20.0, "target_value": 40.0, "last_cycle_token": 1},
            }
            pending_exec = {
                key_concurrent: {"executed_value": 34.0, "target_value": 40.0, "last_cycle_token": 2},
            }
            # 模拟锁外并发新指令写入 key_concurrent
            sim._remote_adjustment_execution = {
                key_popped: dict(before_exec[key_popped]),
                key_concurrent: {
                    "executed_value": 99.0,
                    "target_value": 99.0,
                    "force_target_once": True,
                    "last_cycle_token": None,
                },
            }
            backtrack_info = {
                "factor": 0.5,
                "attempts": 1,
                "initial_error": "mock",
                "controls": [
                    {"key": key_popped, "actual": 10.0, "candidate": 50.0, "accepted": 30.0},
                    {"key": key_concurrent, "actual": 20.0, "candidate": 34.0, "accepted": 27.0},
                ],
            }
            sim._apply_backtrack_controls_to_pending_execution(
                pending_exec,
                before_exec,
                backtrack_info,
                2,
            )
            sim._commit_remote_adjustment_execution(before_exec, pending_exec)
            sim._record_power_flow_backtrack(backtrack_info, 0.0)

            self.assertEqual(sim._remote_adjustment_execution[key_popped]["executed_value"], 30.0)
            self.assertEqual(sim._remote_adjustment_execution[key_concurrent]["executed_value"], 99.0)
            self.assertTrue(sim._remote_adjustment_execution[key_concurrent].get("force_target_once"))

    def test_device_fault_expiry_does_not_overwrite_command_issued_during_fault(self) -> None:
        """验证设备故障期间新下发的停机指令，在故障窗口解除当拍不被 _fault_restore 过期旧值覆写。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            diesel_rows = [
                row
                for row in sim.source_model_book.data["ACGenerator"].data
                if "diesel" in str(row.get("dev_type", "")).lower()
            ]
            self.assertTrue(diesel_rows)
            diesel_name = str(diesel_rows[0]["name"])
            sim.curves["mode"] = "day"
            sim.local_settings["device_faults"] = [
                {
                    "dev_type": "ACGenerator",
                    "dev_name": diesel_name,
                    "run_stat": 0,
                    "start_minute": 10,
                    "end_minute": 20,
                }
            ]
            # 1) t=12 处于故障窗口内，故障前 run_stat=1 进入 _fault_restore，设备被迫停运 0
            sim.clock.absolute_minute = 12.0
            sim.clock.minute = 12.0
            stat_in_fault, _yt = sim._prepare_runtime_inputs(12.0, 12.0, period_seconds=60.0)
            run_row_in_fault = next(
                r
                for r in stat_in_fault.data["RunStat"].data
                if str(r.get("dev_type")) == "ACGenerator" and str(r.get("dev_name")) == diesel_name
            )
            self.assertEqual(str(run_row_in_fault["run_stat"]), "0")
            self.assertIn(("RunStat", "ACGenerator", diesel_name), sim._fault_restore)

            # 2) 故障期间学员台下发停机指令 run_stat=0
            sim.apply_student_commands(
                {
                    "run_status": [
                        {"dev_type": "ACGenerator", "dev_name": diesel_name, "run_stat": 0}
                    ]
                },
                source="trainee",
            )

            # 3) t=21 故障窗口刚解除，必须保持故障期间新下发的 run_stat=0，不能被旧值 "1" 覆盖闪烁
            sim.clock.absolute_minute = 21.0
            sim.clock.minute = 21.0
            stat_after_fault, _yt = sim._prepare_runtime_inputs(21.0, 21.0, period_seconds=60.0)
            run_row_after_fault = next(
                r
                for r in stat_after_fault.data["RunStat"].data
                if str(r.get("dev_type")) == "ACGenerator" and str(r.get("dev_name")) == diesel_name
            )
            self.assertEqual(str(run_row_after_fault["run_stat"]), "0")
            self.assertNotIn(("RunStat", "ACGenerator", diesel_name), sim._fault_restore)

    def test_apply_realtime_input_books_applies_load_model_only_once(self) -> None:
        """验证无逐负荷 LoadPower 时 apply_load_model 仅执行一次，不产生平方缩放失真。"""
        model_book = EBook(
            {
                "ACLoad": [
                    {"idx": "1", "name": "L1", "pbase": "1", "qbase": "1", "pv0": "10", "qv0": "0", "run_stat": "1"}
                ]
            }
        )
        dev_define = EBook(
            {
                "load_temperature": [
                    {"name": "L1", "temp_base": "20", "temp_factor": "0.05"}
                ]
            }
        )
        # 温度 30℃ -> temp_scale = 1 + 0.05 * (30 - 20) = 1.5；单次缩放应得 15.0 kW（而非两次平方 22.5 kW）
        weather_book = EBook({"Weather": [{"air_temp_c": "30"}]})
        _changed, out_book, _define, _weather = simu_loop.apply_realtime_input_books(
            model_book,
            weather_book,
            EBook({}),
            EBook({}),
            dev_define,
            period_seconds=60.0,
        )
        p_out, _q, _pb, _qb = simu_loop._load_power(out_book.data["ACLoad"].data[0])
        self.assertAlmostEqual(p_out, 15.0, places=6)


class ClosedLoopSimulationAuditRound3Tests(unittest.TestCase):
    """三轮深度审查（两批合并 11 项修复）专项回归验证。"""

    def test_control_clock_step_no_abba_deadlock_with_concurrent_step(self) -> None:
        """验证 control_clock({'action': 'step'}) 先释放 self.lock 再调 step()，彻底消除 AB-BA 死锁。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            entered_kernel = threading.Event()
            release_kernel = threading.Event()
            orig_execute = sim._execute_kernel

            def slowed_execute(config):
                entered_kernel.set()
                release_kernel.wait(timeout=5.0)
                return orig_execute(config)

            errors: list[BaseException] = []

            def worker_step() -> None:
                try:
                    sim.step(advance_seconds=1.0, return_snapshot=False)
                except BaseException as exc:  # pragma: no cover
                    errors.append(exc)

            def worker_control_step() -> None:
                try:
                    sim.control_clock({"action": "step"})
                except BaseException as exc:  # pragma: no cover
                    errors.append(exc)

            sim._execute_kernel = slowed_execute  # type: ignore[method-assign]
            t1 = threading.Thread(target=worker_step)
            t1.start()
            self.assertTrue(entered_kernel.wait(timeout=5.0))

            # 此时 t1 持有 _step_lock 并在锁外执行潮流；启动 t2 调用 control_clock("step")
            t2 = threading.Thread(target=worker_control_step)
            t2.start()
            # 稍作等待让 t2 进入 control_clock 并释放 self.lock 后排队等待 _step_lock
            time.sleep(0.15)
            # 放行潮流；若存在 AB-BA 死锁，t1 在获取 self.lock 时将与 t2 永久互锁
            release_kernel.set()
            t1.join(timeout=10.0)
            t2.join(timeout=10.0)
            self.assertFalse(t1.is_alive(), "后台 step 线程发生死锁")
            self.assertFalse(t2.is_alive(), "control_clock(step) 线程发生死锁")
            self.assertEqual(errors, [])

    def test_energy_coupling_bidirectional_interlock_and_state_echo(self) -> None:
        """验证电氢耦合设备任一端点停运时联锁停运耦合父设备与对端端点，且状态回显不被 1 覆写。"""
        from effective_state import propagate_composite_run_states

        rows = {
            "AcE2Hydro": {
                "header_list": ["idx", "name", "idx_acload_t1", "idx_h2_unit_t2", "run_stat"],
                "rows": [[1, "E2H-1", 10, 20, 1]],
            },
            "ACLoad": {
                "header_list": ["idx", "name", "run_stat"],
                "rows": [[10, "E2H-1_ACLoad", 0]],
            },
            "HydroSource": {
                "header_list": ["idx", "name", "run_stat"],
                "rows": [[20, "E2H-1_H2Src", 1]],
            },
        }
        effective, overrides = propagate_composite_run_states(rows)
        self.assertEqual(effective["AcE2Hydro"]["rows"][0][4], 0)
        self.assertEqual(effective["HydroSource"]["rows"][0][2], 0)
        overridden_types = {item["dev_type"] for item in overrides}
        self.assertEqual(overridden_types, {"AcE2Hydro", "HydroSource"})

        # 验证 collect_device_operating_states 不再用未联锁的 model_book run_stat=1 覆盖快照 run_stat=0
        fake_dev = SimpleNamespace(name="E2H-1_ACLoad", run_stat=0, is_alive=True)
        fake_snap = SimpleNamespace(
            ac=SimpleNamespace(nodes=[], loads=[fake_dev]),
            dc=None,
            ac_devices={},
            dc_devices={},
            dcac_converters=[],
            acac_converters=[],
        )
        book_with_stale_one = EBook({"ACLoad": [{"idx": "10", "name": "E2H-1_ACLoad", "run_stat": "1"}]})
        states = simu_loop.collect_device_operating_states(fake_snap, book_with_stale_one)
        load_state = next(s for s in states if s["dev_type"] == "ACLoad" and s["dev_name"] == "E2H-1_ACLoad")
        self.assertEqual(load_state["run_stat"], 0)

    def test_weather_scada_preserves_fault_and_no_signal_torn_frame(self) -> None:
        """验证步进后 SCADA 气象故障不被 _with_weather_measurements 覆写，且未步进前遥控不制造遥信撕裂帧。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.local_settings["measurement_faults"] = [
                {
                    "dev_type": "Environment",
                    "dev_name": "weather",
                    "meas_type": "WIND_SPEED",
                    "fault_type": "bias",
                    "bias": 50.0,
                    "start_minute": 0,
                    "end_minute": 1440,
                }
            ]
            sim.step(advance_seconds=1.0, return_snapshot=False)
            meas = sim.measurements()
            real_wind = next(
                r for r in meas["real"] if r["dev_type"] == "Environment" and r["meas_type"] == "WIND_SPEED"
            )
            scada_wind = next(
                r for r in meas["scada"] if r["dev_type"] == "Environment" and r["meas_type"] == "WIND_SPEED"
            )
            self.assertGreater(float(scada_wind["value"]) - float(real_wind["value"]), 40.0)

            # 下发遥控停机但尚未步进潮流时，上一拍已计算帧的 RUN_STAT 不应提前跳变制造与满发功率冲突的撕裂帧
            diesel_rows = [
                row
                for row in sim.source_model_book.data["ACGenerator"].data
                if "diesel" in str(row.get("dev_type", "")).lower()
            ]
            self.assertTrue(diesel_rows)
            diesel_name = str(diesel_rows[0]["name"])
            before_run = next(
                r
                for r in meas["scada"]
                if r["dev_type"] == "ACGenerator" and r["dev_name"] == diesel_name and r["meas_type"] == "RUN_STAT"
            )["value"]
            sim.apply_student_commands(
                {"run_status": [{"dev_type": "ACGenerator", "dev_name": diesel_name, "run_stat": 0}]},
                source="trainee",
            )
            after_cmd_meas = sim.measurements()
            before_step_run = next(
                r
                for r in after_cmd_meas["scada"]
                if r["dev_type"] == "ACGenerator" and r["dev_name"] == diesel_name and r["meas_type"] == "RUN_STAT"
            )["value"]
            self.assertEqual(before_step_run, before_run)

    def test_ideal_edge_closed_status_and_scada_noise_bounds_and_missing_valid(self) -> None:
        """验证理想支路识别 closed_status、带后缀交流非负/SOC上界/停机去噪以及缺失测点置 valid=0。"""
        from update_meas_from_lf import _device_is_live

        # 初始 status=0 但遥控合闸 closed_status=1 时必须判定为 live
        reclosed_breaker = SimpleNamespace(run_stat=1, status=0, closed_status=1, is_alive=True)
        self.assertTrue(_device_is_live(reclosed_breaker, check_status=True))
        opened_breaker = SimpleNamespace(run_stat=1, status=1, closed_status=0, is_alive=True)
        self.assertFalse(_device_is_live(opened_breaker, check_status=True))

        # 校验非负带后缀交流幅值、直流有向电流保负、满电 SOC 上界截断、停机零值去噪
        model_book = EBook(
            {
                "ACGenerator": [
                    {"idx": "1", "name": "G_STOP", "run_stat": "0"},
                    {"idx": "2", "name": "G_RUN", "run_stat": "1"},
                ]
            }
        )
        rows = [
            ["1", "i_ac_zero", "ACGenerator", "G_RUN", "I_GEN", "1", "1", "0.0"],
            ["2", "v_from_zero", "ACBranch", "B1", "V_FROM", "1", "1", "0.0"],
            ["3", "dc_i_zero", "DCBranch", "DB1", "I_FROM", "1", "1", "0.0"],
            ["4", "soc_full", "ACGenerator", "G_RUN", "SOC", "1", "1", "1.0"],
            ["5", "stopped_p", "ACGenerator", "G_STOP", "P_GEN", "1", "1", "0.0"],
        ]
        # 负偏置测试非负截断与直流保负
        neg_scada = simu_loop.add_noise_to_rows(
            rows,
            noise_std=0.0,
            rng=random.Random(1),
            median_deviations={"i_ac_zero": -5.0, "v_from_zero": -2.0, "dc_i_zero": -3.0, "stopped_p": -4.0},
            model_book=model_book,
        )
        self.assertEqual(float(neg_scada[0][7]), 0.0)
        self.assertEqual(float(neg_scada[1][7]), 0.0)
        self.assertAlmostEqual(float(neg_scada[2][7]), -3.0, places=6)
        self.assertEqual(float(neg_scada[4][7]), 0.0)

        # 正偏置测试电储能 SOC 上界截断 1.0
        pos_scada = simu_loop.add_noise_to_rows(
            rows,
            noise_std=0.0,
            rng=random.Random(1),
            median_deviations={"soc_full": 0.08},
            model_book=model_book,
        )
        self.assertEqual(float(pos_scada[3][7]), 1.0)

        # 缺失测点必须将 valid 置 0
        empty_snap = SimpleNamespace(
            value=lambda *_args: None,
            ac_devices={},
            dc_devices={},
            fluid_results={},
            coupling_results=(),
        )
        _b, real_rows, _a, updated, missing = simu_loop.build_real_rows_from_data(
            [["1", "missing_pt", "ACBranch", "NO_SUCH", "P_FROM", "1", "1", "999.0"]],
            empty_snap,
        )
        self.assertEqual(updated, 0)
        self.assertEqual(missing, 1)
        self.assertEqual(real_rows[0][6], "0")

    def test_cancel_student_commands_partial_and_delta_scada_only_and_trim(self) -> None:
        """验证单点取消不误杀同批控制点；非 compact scada_only 保留未变测点；历史裁剪触发 reset。"""
        from simu.measurement_delta import apply_measurement_delta

        # 1) apply_measurement_delta 非 compact + scada_only=True 保留未变测点
        defs = [{"idx": 1, "name": "M1", "valid": 1}, {"idx": 2, "name": "M2", "valid": 1}]
        base_meas = {
            "definitions": defs,
            "scada": [{"idx": 1, "name": "M1", "value": 10.0, "valid": 1}, {"idx": 2, "name": "M2", "value": 20.0, "valid": 1}],
        }
        delta_payload = {
            "reset": False,
            "value_channels": ["scada"],
            "items": [{"name": "M1", "scada_value": 15.0, "valid": 1}],
        }
        merged = apply_measurement_delta(base_meas, defs, delta_payload)
        by_name = {r["name"]: r["value"] for r in merged["scada"]}
        self.assertEqual(by_name, {"M1": 15.0, "M2": 20.0})

        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            gens = [str(r["name"]) for r in sim.source_model_book.data["ACGenerator"].data[:2]]
            self.assertEqual(len(gens), 2)
            # 2) 单批下发两个人工遥调点，仅取消第 1 个，第 2 个必须保持生效
            sim.apply_student_commands(
                {
                    "command_origin": "manual",
                    "set_values": [
                        {"dev_type": "ACGenerator", "dev_name": gens[0], "set_type": "p_set", "set_value": 10.0},
                        {"dev_type": "ACGenerator", "dev_name": gens[1], "set_type": "p_set", "set_value": 15.0},
                    ],
                },
                source="trainee-ui",
            )
            sim.cancel_student_commands(
                {"cancel_commands": [{"dev_type": "ACGenerator", "dev_name": gens[0], "set_type": "p_set"}]},
                source="trainee-ui",
            )
            active_keys = sim._active_remote_adjustment_keys(sim.clock.absolute_minute)
            self.assertNotIn(("ACGenerator", gens[0], "p_set"), active_keys)
            self.assertIn(("ACGenerator", gens[1], "p_set"), active_keys)

            # 3) 历史滚动裁剪后 after < oldest_seq - 1 必须返回 reset=True
            sim.step(advance_seconds=1.0, return_snapshot=False)
            sim._measurement_delta_seq = 500
            sim._measurement_delta_history = [{"seq": 301, "items": [], "keys": []}]
            sim._measurement_delta_step_count = sim.clock.step_count
            sim._measurement_delta_definition_revision = sim.definition_snapshot.revision
            sim._measurement_delta_runtime_marker = sim._measurement_delta_runtime_state_marker()
            resp = sim.measurement_delta(after_seq=50, compact=False)
            self.assertTrue(resp["reset"])

    def test_remote_adjustment_renewable_curtail_down_and_active_window(self) -> None:
        """验证新能源下调限电无虚高上限死区，以及 _active_window 支持 hour 模式与零长窗口。"""
        from simu.service_parts.common import _active_window

        # hour 模式跨第 1 小时后按 60 分钟周期循环，且零长度窗口不生效
        self.assertTrue(_active_window({"start_minute": 10, "end_minute": 20}, 75.0, 75.0, "hour"))
        self.assertFalse(_active_window({"start_minute": 10, "end_minute": 20}, 85.0, 85.0, "hour"))
        self.assertFalse(_active_window({"start_minute": 10, "end_minute": 10}, 15.0, 15.0, "day"))
        self.assertTrue(_active_window({"start_minute": 0, "end_minute": 1440}, 720.0, 720.0, "day"))

        # 新能源下调限电：实测 30 kW，上拍放开上限 100 kW，现下调限电 20 kW -> 从 30 kW 直接向 20 kW 响应（<30 kW），不卡在 76 kW
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.remote_adjustment_response_ratio = 0.5
            wind_rows = [
                row
                for row in sim.source_model_book.data["ACGenerator"].data
                if "wind" in str(row.get("dev_type", "")).lower()
            ]
            self.assertTrue(wind_rows)
            wind_name = str(wind_rows[0]["name"])
            key = ("ACGenerator", wind_name, "p_set")
            # 秦岭站单台交流风电额定上限约 10 kW：上拍放开上限 10.0，当前实测 6.0，下调限电 2.0 -> 从 min(6.0, 10.0)=6.0 响应至 4.0（非 6.0）
            sim.apply_student_commands(
                {
                    "run_status": [{"dev_type": "ACGenerator", "dev_name": wind_name, "run_stat": 1}],
                    "set_values": [{"dev_type": "ACGenerator", "dev_name": wind_name, "set_type": "p_set", "set_value": 2.0}],
                },
                source="trainee",
            )
            sim._remote_adjustment_execution[key] = {
                "executed_value": 10.0,
                "target_value": 10.0,
                "last_cycle_token": 1,
            }
            sim._latest_true_remote_adjustment_value = lambda k: 6.0 if k == key else None  # type: ignore[method-assign]
            _stat, _yt, pending = sim._remote_adjustment_boundary_books(
                0.0,
                2,
                period_seconds=1.0,
                return_next_state=True,
            )
            self.assertAlmostEqual(pending[key]["executed_value"], 4.0, places=6)

    def test_curves_clock_monotonic_step_minutes_closed_endpoint_and_hydro_load(self) -> None:
        """验证编辑曲线不跳空时钟、step_minutes 展开、闭区间首段插值以及 HydroLoad 字段写读一致。"""
        from simu.service_parts.common import _interpolate, _normalize_points

        pts = _normalize_points([10.0, 20.0, 30.0], ("value",), step_minutes=60.0)
        self.assertEqual([p["minute"] for p in pts], [0.0, 60.0, 120.0])

        # 闭区间 0..1440 同时提供时，[0, 60) 必须从 minute=0 的 100 插值到 minute=60 的 200，而不是跳用 minute=1440 的 999
        interp = _interpolate(
            [{"minute": 0, "v": 100.0}, {"minute": 60, "v": 200.0}, {"minute": 1440, "v": 999.0}],
            30.0,
            "v",
            0.0,
            period_minutes=1440.0,
        )
        self.assertAlmostEqual(float(interp), 150.0, places=6)

        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.clock.speed = 60
            sim.clock.absolute_minute = 5.0 / 60.0
            sim.clock.minute = sim.clock.absolute_minute
            sim.update_curve_series({"series": {"load:HydroLoad:氢负荷-1": [12.5, 15.0]}})
            # 未切换模式编辑曲线，时钟不得跳空对齐到 1.0 分钟
            self.assertAlmostEqual(sim.clock.absolute_minute, 5.0 / 60.0, places=9)
            self.assertEqual(sim.curves["loads"]["HydroLoad:氢负荷-1"][0].get("flow_set"), 12.5)
            self.assertNotIn("p_kw", sim.curves["loads"]["HydroLoad:氢负荷-1"][0])

    def test_scada104_baseline_merges_delta_init_and_proxy_bool_parser(self) -> None:
        """验证 scada104 建基线合入 delta_init 防丢帧，以及代理布尔字符串解析正确。"""
        import scada104 as scada104_mod
        from simu.simulator_proxy import make_simulator_proxy_server

        bridge = scada104_mod.Bridge.__new__(scada104_mod.Bridge)
        bridge._delta_sync_state = {}

        def fake_pool_request(base, path, payload=None, *, timeout=5.0):
            if path.startswith("/api/measurements?"):
                return {
                    "definitions": [{"idx": 1, "name": "P1", "meas_type": "P"}],
                    "scada": [{"idx": 1, "name": "P1", "value": 10.0, "valid": 1}],
                }
            if path == "/api/external/controls/names":
                return {"model_id": "m1", "yk_names": [], "yt_names": []}
            if path.startswith("/api/measurements/delta"):
                # 模拟两次请求间隙模拟台已步进至 seq=2、值变为 42.0
                return {
                    "encoding": "measurement-arrays-v1",
                    "seq": 2,
                    "count": 1,
                    "definition_signature": "sig-1",
                    "scada_values": [42.0],
                    "valid_values": [1],
                }
            raise AssertionError(path)

        with patch.object(scada104_mod._HTTP_POOL, "request_json", side_effect=fake_pool_request):
            points, dirty = bridge._read_points_for_model("http://127.0.0.1:18711", "m1")
        self.assertTrue(dirty)
        self.assertEqual(points["yc"]["P1"]["value"], 42.0)
        self.assertEqual(bridge._delta_sync_state["m1"]["seq"], 2)

        # 验证 Bridge.execute 不强制 manual_hold=True 且回传模拟台安全限幅后的实际值
        captured_payloads: list[dict] = []

        def fake_exec_request(base, path, payload=None, *, timeout=5.0):
            captured_payloads.append(dict(payload or {}))
            return {"accepted": {"remote_adjustments": 1}, "yt_results": [{"accepted": True, "value": 80.0}]}

        bridge.command_target = lambda rtu, kind, number, value: ("http://127.0.0.1:18711", "m1", "YT_G1")  # type: ignore[method-assign]
        with patch.object(scada104_mod._HTTP_POOL, "request_json", side_effect=fake_exec_request):
            applied = bridge.execute(1, "yt", 1, 150.0)
        self.assertEqual(applied, 80.0)
        self.assertFalse(captured_payloads[0].get("manual_hold"))

        # 验证代理布尔字符串解析："false"/"0" 必须解析为 False
        from simu.simulator_proxy import parse_bool_flag

        self.assertFalse(parse_bool_flag("false"))
        self.assertFalse(parse_bool_flag("0"))
        self.assertFalse(parse_bool_flag("off"))
        self.assertTrue(parse_bool_flag("true"))
        self.assertTrue(parse_bool_flag("1"))


class ClosedLoopSimulationAuditRound4Tests(unittest.TestCase):
    """第四轮深水区审计 12 项核心修复的专项回归测试。"""

    def test_measurement_status_valid_no_whitewash_dead_no_drift_and_paused_overlay(self) -> None:
        """验证量测状态统一 valid、不洗白 row_valid=0、dead 带 bias 不漂移及暂停态覆写即时生效且无损回退。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            sim.step(advance_seconds=1.0, return_snapshot=False)
            meas = sim.measurements()
            scada_rows = meas["scada"]
            self.assertTrue(scada_rows)

            # 1) 快/慢路径状态词法统一为 "valid"
            first_valid = next(r for r in scada_rows if int(r.get("valid", 0)) == 1)
            self.assertEqual(first_valid["status"], "valid")
            target_name = str(first_valid["name"])
            base_val = float(first_valid["value"])

            # 2) row_valid=0 时不得被误标记为 "valid" 或洗白成 1
            for row in sim.latest_scada_rows:
                if str(row[1]) == target_name:
                    row[6] = "0"
                    break
            meas_invalid = sim.measurements()
            invalid_item = next(r for r in meas_invalid["scada"] if r["name"] == target_name)
            self.assertEqual(int(invalid_item["valid"]), 0)
            self.assertEqual(invalid_item["status"], "invalid")

            # 3) 暂停态下配置 dead 故障（无 median 带 bias）与固定值立即生效，且连续多拍不漂移，清除后无损回退
            sim.set_local_settings(
                {
                    "measurement_faults": [
                        {
                            "meas_name": target_name,
                            "type": "dead",
                            "bias": 10.0,
                            "start_minute": 0,
                            "end_minute": 1440,
                        }
                    ],
                    "measurement_statuses": {},
                }
            )
            meas_dead = sim.measurements()
            dead_item = next(r for r in meas_dead["scada"] if r["name"] == target_name)
            self.assertAlmostEqual(float(dead_item["value"]), base_val + 10.0, places=6)

            # 连续多次调用 _apply_measurement_faults 不得每拍累加 bias 无限漂移
            sim._apply_measurement_faults(sim.clock.minute, sim.clock.absolute_minute + 1.0 / 60.0)
            sim._apply_measurement_faults(sim.clock.minute, sim.clock.absolute_minute + 2.0 / 60.0)
            v_after = float(next(r[7] for r in sim.latest_scada_rows if str(r[1]) == target_name))
            self.assertAlmostEqual(v_after, base_val + 10.0, places=6)

            # 暂停态切换为 fixed 状态与固定值立即生效
            sim.set_local_settings(
                {
                    "measurement_faults": [],
                    "measurement_statuses": {target_name: {"status": "fixed", "fixed_value": 88.5}},
                }
            )
            meas_fixed = sim.measurements()
            fixed_item = next(r for r in meas_fixed["scada"] if r["name"] == target_name)
            self.assertEqual(fixed_item["status"], "fixed")
            self.assertAlmostEqual(float(fixed_item["value"]), 88.5, places=6)

            # 清除故障与状态后立即回退至本拍原始 base_val
            sim.set_local_settings({"measurement_statuses": {}, "measurement_faults": []})
            meas_restored = sim.measurements()
            restored_item = next(r for r in meas_restored["scada"] if r["name"] == target_name)
            self.assertEqual(restored_item["status"], "valid")
            self.assertAlmostEqual(float(restored_item["value"]), base_val, places=6)

    def test_ghost_latched_strategy_command_deletable_and_empty_status_filtered(self) -> None:
        """验证策略换代/撤销后仍在锁存生效的自动指令可被教员删除，且空串 status 被过滤。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            gens = [str(r["name"]) for r in sim.source_model_book.data["ACGenerator"].data]
            self.assertTrue(gens)
            gen_name = gens[0]

            # 过滤空串 status
            filtered = sim._filter_defined_run_command_items(
                [{"dev_type": "ACGenerator", "dev_name": gen_name, "status": ""}]
            )
            self.assertEqual(filtered, [])

            # 下发一代自动策略指令，再标记该策略撤销但保留锁存语义，确认教员 delete_active_commands 可删除
            sim.apply_student_commands(
                {
                    "command_origin": "strategy",
                    "strategy_id": "strat-test",
                    "strategy_generation": 1,
                    "set_values": [
                        {"dev_type": "ACGenerator", "dev_name": gen_name, "set_type": "p_set", "set_value": 12.0}
                    ],
                },
                source="trainee-strategy",
            )
            with sim.lock:
                self.assertTrue(sim.command_history)
                entry = sim.command_history[-1]
                entry["strategy_cancelled"] = True
                entry["superseded_by_generation"] = 2
                self.assertTrue(sim._command_entry_is_active(entry, sim.clock.absolute_minute))
                self.assertTrue(sim._command_entry_can_be_cancelled(entry, sim.clock.absolute_minute))

            deleted = sim.delete_active_commands(
                {"cancel_commands": [{"dev_type": "ACGenerator", "dev_name": gen_name, "set_type": "p_set"}]},
                source="simulator-ui",
            )
            self.assertGreaterEqual(int(deleted.get("remote_adjustments", 0)), 1)
            self.assertNotIn(
                ("ACGenerator", gen_name, "p_set"),
                sim._active_remote_adjustment_keys(sim.clock.absolute_minute),
            )

    def test_restart_loads_manual_overrides_before_commands_and_tolerates_stale_measurement_group(self) -> None:
        """验证重启先加载人工修改再加载指令历史，且单个失效测点覆盖不销毁整份 manual_overrides.json。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_dir = _resolve_active_model_dir()
            runtime_dir = Path(tmp_dir) / "runtime"
            sim1 = service.PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=runtime_dir,
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
                random_seed=7,
            )
            gen_row = next(
                r for r in sim1.source_model_book.data["ACGenerator"].data
                if float(r.get("p_max", 0.0) or 0.0) > 0.0
            )
            gen_name = str(gen_row["name"])
            orig_p_max = float(gen_row["p_max"])
            raised_p_max = orig_p_max + 200.0
            target_p = orig_p_max + 100.0

            sim1.update_device_parameters(
                {
                    "block_name": "ACGenerator",
                    "row_key": {"name": gen_name},
                    "changes": {"p_max": raised_p_max},
                }
            )
            sim1.apply_student_commands(
                {
                    "command_origin": "manual",
                    "set_values": [
                        {"dev_type": "ACGenerator", "dev_name": gen_name, "set_type": "p_set", "set_value": target_p}
                    ],
                },
                source="trainee-ui",
            )

            # 在 manual_overrides.json 中人为注入一个已失效测点分组项，验证重启不整体丢弃合法修改
            overrides_path = runtime_dir / "manual_overrides.json"
            overrides_payload = json.loads(overrides_path.read_text(encoding="utf-8"))
            overrides_payload.setdefault("measurement_groups", {})["NON_EXISTENT_MEAS_GROUP"] = {"value": 999.0}
            overrides_path.write_text(json.dumps(overrides_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            # 重启构造第二个实例
            sim2 = service.PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=runtime_dir,
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
                random_seed=7,
            )
            reloaded_gen = next(
                r for r in sim2.definition_snapshot.model_book.data["ACGenerator"].data if str(r.get("name")) == gen_name
            )
            self.assertAlmostEqual(float(reloaded_gen["p_max"]), raised_p_max, places=6)
            reloaded_cmd = sim2.command_history[-1]["normalized"]["set_values"][0]
            self.assertAlmostEqual(float(reloaded_cmd["set_value"]), target_p, places=6)

    def test_hour_mode_external_realtime_indexing_and_sparse_curve_upsert(self) -> None:
        """验证 hour 模式 3600 个整秒点无浮点错格，且稀疏曲线外部实时输入按时间戳安全 upsert。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            orig_loads = dict(sim.curves.get("loads", {}))
            self.assertTrue(orig_loads)
            load_key = next(iter(orig_loads.keys()))
            sim.set_curves({"mode": "hour", "loads": {load_key: [{"minute": 0.0, "p_kw": 10.0}, {"minute": 30.0, "p_kw": 20.0}]}})
            with sim.lock:
                for sec in range(3600):
                    info = sim._external_realtime_target_locked(sec / 60.0)
                    self.assertEqual(int(info["index"]), sec, f"sec={sec} indexed wrong")

            # 稀疏 2 点负荷曲线上写入外部实时输入，验证不会破坏时间轴或截断曲线
            sim.clock.absolute_minute = 15.0
            sim.clock.minute = 15.0
            resp = sim.apply_external_realtime_inputs(
                {
                    "loads": {load_key: 42.5},
                    "advance_step": False,
                }
            )
            self.assertTrue(resp.get("ok", True))
            pts = sim.curves["loads"][load_key]
            minutes = [round(float(p["minute"]), 6) for p in pts]
            self.assertEqual(minutes, [0.0, 15.0, 30.0])
            self.assertAlmostEqual(float(pts[1]["p_kw"]), 42.5, places=6)

    def test_hydrogen_flow_set_safety_validation_checks_electric_bounds(self) -> None:
        """验证 FLOW 模式下氢能 flow_set 遥调反向换算电侧功率并执行安全限幅。"""
        from simu.model_semantics import HYDROGEN_CONVERSION_BLOCKS, validate_hydrogen_power_setpoint_safety

        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            book = simu_loop._clone_ebook(sim.source_model_book)
            # 将任意一台电氢耦合设备设为 FLOW 控制模式，验证氢端 flow_set 反向换算至电侧并限幅
            checked = False
            for block_name in HYDROGEN_CONVERSION_BLOCKS:
                block = book.data.get(block_name)
                if block is None or not block.data:
                    continue
                for row in block.data:
                    row["control_type"] = "FLOW"
            for hydro_type in ("HydroLoad", "HydroSource"):
                block = book.data.get(hydro_type)
                if block is None:
                    continue
                for row in block.data:
                    hydro_name = str(row.get("name") or "")
                    if not hydro_name:
                        continue
                    res = validate_hydrogen_power_setpoint_safety(
                        book,
                        hydro_type,
                        hydro_name,
                        "flow_set",
                        1e6,
                        clamp_to_bounds=True,
                    )
                    if res is not None:
                        checked = True
                        self.assertTrue(res["clamped"])
                        self.assertLess(float(res["flow_set"]), 1e6)
                        self.assertGreaterEqual(float(res["flow_set"]), 0.0)
                        break
                if checked:
                    break
            self.assertTrue(checked, "未能触发任意电氢耦合设备的 flow_set 反向电侧安全限幅")

    def test_hybrid_topology_keeps_dcdc_voltage_island_and_strips_dead_dcac_ghost_ref(self) -> None:
        """验证混合拓扑保留定压 DCDC 构网直流孤岛，且死岛 DCAC 不注入幽灵电压参考。"""
        import numpy as np
        from src.hybrid_power_system_analysis.model.ppc_topology import ensure_hybrid_ppc_topology
        from src.hybrid_power_system_analysis.model.ac_array_model import (
            BUS_COLS as AC_BUS_COLS,
            GEN_COLS as AC_GEN_COLS,
            LOAD_COLS as AC_LOAD_COLS,
            CTRL_SLACK as AC_CTRL_SLACK,
        )
        from src.hybrid_power_system_analysis.model.dc_array_model import (
            BUS_COLS as DC_BUS_COLS,
            DCDC_COLS as DC_DCDC_COLS,
            GEN_COLS as DC_GEN_COLS,
            LOAD_COLS as DC_LOAD_COLS,
            CTRL_V as DC_CTRL_V,
            CTRL_NONE as DC_CTRL_NONE,
        )
        from src.hybrid_power_system_analysis.model.hybrid_array_model import (
            DCAC_COLS,
            DCAC_AC_CONTROL_CODE,
            DCAC_DC_CONTROL_CODE,
        )

        # 1) 定压 DCDC 构网直流孤岛：DC1(有平衡机) --DCDC(j定压)--> DC2(无平衡机，有负荷)
        dc_bus = np.zeros((2, len(DC_BUS_COLS)), dtype=np.float64)
        dc_bus[0, [DC_BUS_COLS["idx"], DC_BUS_COLS["vbase"], DC_BUS_COLS["voltage"], DC_BUS_COLS["run_stat"]]] = [1, 0.75, 1.0, 1]
        dc_bus[1, [DC_BUS_COLS["idx"], DC_BUS_COLS["vbase"], DC_BUS_COLS["voltage"], DC_BUS_COLS["run_stat"]]] = [2, 0.75, 1.0, 1]
        dc_gen = np.zeros((1, len(DC_GEN_COLS)), dtype=np.float64)
        dc_gen[0, [DC_GEN_COLS["idx"], DC_GEN_COLS["node"], DC_GEN_COLS["control_type"], DC_GEN_COLS["v_set"], DC_GEN_COLS["run_stat"]]] = [1, 1, DC_CTRL_V, 1.0, 1]
        dc_load = np.zeros((1, len(DC_LOAD_COLS)), dtype=np.float64)
        dc_load[0, [DC_LOAD_COLS["idx"], DC_LOAD_COLS["node"], DC_LOAD_COLS["pbase"], DC_LOAD_COLS["pv0"], DC_LOAD_COLS["run_stat"]]] = [1, 2, 0.2, 1.0, 1]
        dc_dcdc = np.zeros((1, len(DC_DCDC_COLS)), dtype=np.float64)
        dc_dcdc[0, [
            DC_DCDC_COLS["idx"],
            DC_DCDC_COLS["i_node"],
            DC_DCDC_COLS["j_node"],
            DC_DCDC_COLS["i_control_type"],
            DC_DCDC_COLS["j_control_type"],
            DC_DCDC_COLS["v_set"],
            DC_DCDC_COLS["run_stat"],
        ]] = [1, 1, 2, DC_CTRL_NONE, DC_CTRL_V, 1.0, 1]

        ac_bus = np.zeros((1, len(AC_BUS_COLS)), dtype=np.float64)
        ac_bus[0, [AC_BUS_COLS["idx"], AC_BUS_COLS["vbase"], AC_BUS_COLS["voltage"], AC_BUS_COLS["run_stat"]]] = [1, 0.4, 1.0, 1]
        ac_gen = np.zeros((1, len(AC_GEN_COLS)), dtype=np.float64)
        ac_gen[0, [AC_GEN_COLS["idx"], AC_GEN_COLS["node"], AC_GEN_COLS["control_type"], AC_GEN_COLS["v_set"], AC_GEN_COLS["run_stat"]]] = [1, 1, AC_CTRL_SLACK, 1.0, 1]
        ac_load = np.zeros((1, len(AC_LOAD_COLS)), dtype=np.float64)
        ac_load[0, [AC_LOAD_COLS["idx"], AC_LOAD_COLS["node"], AC_LOAD_COLS["pbase"], AC_LOAD_COLS["pv0"], AC_LOAD_COLS["run_stat"]]] = [1, 1, 0.1, 1.0, 1]

        ppc = {
            "ac": {"bus": ac_bus, "gen": ac_gen, "load": ac_load, "shunt": np.zeros((0, 7)), "branch": np.zeros((0, 11)), "transformer": np.zeros((0, 15)), "three_winding_transformer": np.zeros((0, 20)), "zero_branch": np.zeros((0, 7)), "switch": np.zeros((0, 8)), "break": np.zeros((0, 8)), "acac": np.zeros((0, 15))},
            "dc": {"bus": dc_bus, "gen": dc_gen, "load": dc_load, "branch": np.zeros((0, 8)), "zero_branch": np.zeros((0, 7)), "switch": np.zeros((0, 8)), "break": np.zeros((0, 8)), "dcdc": dc_dcdc},
            "dcac": np.zeros((0, len(DCAC_COLS)), dtype=np.float64),
        }
        ensure_hybrid_ppc_topology(ppc)
        dc_topo = ppc["dc"]["_topology_arrays"]
        self.assertTrue(bool(np.all(dc_topo.node_alive_mask)), "定压 DCDC 构网的直流孤岛应全部存活")

        # 2) AC 侧死岛（无平衡机、仅 bus.run_stat=1），连着一台 DCAC(dc_ctrl=V) -> 必须剥离幽灵 DC 电压参考，DC 孤岛不得凭幽灵参考存活
        ac_bus_dead = np.zeros((1, len(AC_BUS_COLS)), dtype=np.float64)
        ac_bus_dead[0, [AC_BUS_COLS["idx"], AC_BUS_COLS["vbase"], AC_BUS_COLS["voltage"], AC_BUS_COLS["run_stat"]]] = [1, 0.4, 1.0, 1]
        dc_bus_iso = np.zeros((1, len(DC_BUS_COLS)), dtype=np.float64)
        dc_bus_iso[0, [DC_BUS_COLS["idx"], DC_BUS_COLS["vbase"], DC_BUS_COLS["voltage"], DC_BUS_COLS["run_stat"]]] = [1, 0.75, 1.0, 1]
        dc_load_iso = np.zeros((1, len(DC_LOAD_COLS)), dtype=np.float64)
        dc_load_iso[0, [DC_LOAD_COLS["idx"], DC_LOAD_COLS["node"], DC_LOAD_COLS["pbase"], DC_LOAD_COLS["pv0"], DC_LOAD_COLS["run_stat"]]] = [1, 1, 0.2, 1.0, 1]
        dcac_ghost = np.zeros((1, len(DCAC_COLS)), dtype=np.float64)
        dcac_ghost[0, [
            DCAC_COLS["idx"],
            DCAC_COLS["ac_node"],
            DCAC_COLS["dc_node"],
            DCAC_COLS["ac_control_type"],
            DCAC_COLS["dc_control_type"],
            DCAC_COLS["v_dc_set"],
            DCAC_COLS["run_stat"],
        ]] = [1, 1, 1, DCAC_AC_CONTROL_CODE["NONE"], DCAC_DC_CONTROL_CODE["V"], 1.0, 1]
        ppc_ghost = {
            "ac": {"bus": ac_bus_dead, "gen": np.zeros((0, len(AC_GEN_COLS))), "load": np.zeros((0, len(AC_LOAD_COLS))), "shunt": np.zeros((0, 7)), "branch": np.zeros((0, 11)), "transformer": np.zeros((0, 15)), "three_winding_transformer": np.zeros((0, 20)), "zero_branch": np.zeros((0, 7)), "switch": np.zeros((0, 8)), "break": np.zeros((0, 8)), "acac": np.zeros((0, 15))},
            "dc": {"bus": dc_bus_iso, "gen": np.zeros((0, len(DC_GEN_COLS))), "load": dc_load_iso, "branch": np.zeros((0, 8)), "zero_branch": np.zeros((0, 7)), "switch": np.zeros((0, 8)), "break": np.zeros((0, 8)), "dcdc": np.zeros((0, len(DC_DCDC_COLS)))},
            "dcac": dcac_ghost,
        }
        ensure_hybrid_ppc_topology(ppc_ghost)
        self.assertEqual(len(ppc_ghost["dc"].get("_external_voltage_reference_node_ids", ())), 0)
        self.assertFalse(bool(np.any(ppc_ghost["dc"]["_topology_arrays"].node_alive_mask)))

    def test_dead_fluid_island_zeroes_flow_and_empty_electric_with_single_hydro_node(self) -> None:
        """验证阀门隔离的无压源氢孤岛流量清零，且全电网失电含单节点氢网求解正常收敛不崩溃。"""
        from src.hybrid_power_system_analysis.model.fluid_model import build_fluid_network_from_model
        from src.hybrid_power_system_analysis.lfcore.fluid_lf import FluidPowerFlowCalc
        from src.hybrid_power_system_analysis.lfcore.hybrid_lf import HybridPowerFlowCalc
        from src.hybrid_power_system_analysis.model.hybrid_model import (
            ACPowerNetwork,
            DCPowerNetwork,
            HybridPowerNetwork,
        )

        # 1) 阀门断开将负荷侧隔离为无压力源孤岛 -> 孤岛负荷与定流源流量必须归零
        model = SimpleNamespace(
            HydroNode=[
                SimpleNamespace(idx=1, name="HN1", p_init=1.0, run_stat=1),
                SimpleNamespace(idx=2, name="HN2", p_init=1.0, run_stat=1),
            ],
            HydroSource=[
                SimpleNamespace(idx=1, name="HS1", node=1, control_type="PRESSURE", p_set=1.0, flow_set=0.0, run_stat=1),
                SimpleNamespace(idx=2, name="HS2", node=2, control_type="FLOW", p_set=1.0, flow_set=5.0, run_stat=1),
            ],
            HydroLoad=[
                SimpleNamespace(idx=1, name="HL2", node=2, flow_set=3.0, run_stat=1),
            ],
            HydroValve=[
                SimpleNamespace(idx=1, name="HV1", i_node=1, j_node=2, run_stat=0),
            ],
            HydroPipe=[],
            HydroCompressor=[],
            HydroStorage=[],
        )
        fluid_net = build_fluid_network_from_model(
            model,
            prefix="Hydro",
            potential_power=2,
            controller_suffix="Compressor",
        )
        self.assertAlmostEqual(float(fluid_net.load_flow_set[0]), 0.0, places=9)
        self.assertAlmostEqual(float(fluid_net.source_flow_set[1]), 0.0, places=9)
        fcalc = FluidPowerFlowCalc(fluid_net)
        self.assertEqual(fcalc.run(), 0)
        self.assertAlmostEqual(float(fcalc.source_flow[1]), 0.0, places=9)

        # 2) 全电网空系统 + 单定压节点氢网 -> _finish_empty_system 正确提交流体状态不崩溃
        single_model = SimpleNamespace(
            HydroNode=[SimpleNamespace(idx=1, name="HN1", p_init=1.0, run_stat=1)],
            HydroSource=[SimpleNamespace(idx=1, name="HS1", node=1, control_type="PRESSURE", p_set=1.0, flow_set=0.0, run_stat=1)],
            HydroLoad=[],
            HydroValve=[],
            HydroPipe=[],
            HydroCompressor=[],
            HydroStorage=[],
        )
        single_hydro = build_fluid_network_from_model(
            single_model,
            prefix="Hydro",
            potential_power=2,
            controller_suffix="Compressor",
        )
        from src.hybrid_power_system_analysis.model.multi_energy_model import MultiEnergyContext

        net = HybridPowerNetwork(
            ACPowerNetwork(),
            DCPowerNetwork(),
            [],
            [],
            fluid_networks={"hydro": single_hydro},
            multi_energy=MultiEnergyContext(fluid_networks={"hydro": single_hydro}),
        )
        hcalc = HybridPowerFlowCalc(net)
        rc = hcalc.run()
        self.assertEqual(rc, 0)
        self.assertTrue(hcalc.converged)
        self.assertTrue(hcalc.fluid_calcs["hydro"].converged)

    def test_dcdc_j_side_current_base_and_infeasible_loss_no_false_convergence(self) -> None:
        """验证 DCDCConverter j 端定电流按 j_node 基准标幺化，且无实根损耗不伪收敛。"""
        from src.hybrid_power_system_analysis.model.dc_array_model import build_dc_ppc_from_efile_rows, DCDC_COLS
        from src.hybrid_power_system_analysis.lfcore.dc_lf import DCPowerFlowCalc
        from src.hybrid_power_system_analysis.unit_system import UnitSettings, normalize_model_named_units

        # 1) DCDC j 端定电流：i_node=1.0 kV, j_node=0.5 kV, p_base=100 kW
        # j 端电流基准 = 100 / 0.5 = 200 A = 0.2 kA；i_set = 0.1 kA -> 标幺值应为 0.5
        rows = {
            "Model": {"header_list": ["p_base", "u_unit", "p_unit", "i_unit"], "rows": [["100", "kV", "kW", "kA"]]},
            "DCNode": {
                "header_list": ["idx", "name", "vbase", "voltage", "run_stat"],
                "rows": [
                    ["1", "DC1", "1.0", "1.0", "1"],
                    ["2", "DC2", "0.5", "0.5", "1"],
                ],
            },
            "DCGenerator": {
                "header_list": ["idx", "name", "node", "control_type", "v_set", "p_set", "run_stat"],
                "rows": [
                    ["1", "G1", "1", "V", "1.0", "0.0", "1"],
                    ["2", "G2", "2", "V", "0.5", "0.0", "1"],
                ],
            },
            "DCDCConverter": {
                "header_list": ["idx", "name", "i_node", "j_node", "r1", "r2", "i_control_type", "j_control_type", "p_set", "i_set", "v_set", "run_stat"],
                "rows": [
                    ["1", "DCDC1", "1", "2", "0.0", "0.0", "NONE", "I", "0.0", "0.1", "0.5", "1"],
                ],
            },
        }
        ppc = build_dc_ppc_from_efile_rows("mem.e", rows)
        self.assertAlmostEqual(float(ppc["dcdc"][0, DCDC_COLS["i_set"]]), 0.5, places=6)

        # unit_system.normalize_model_named_units 对象路径同样按 j_node 基准标幺化
        fake_model = SimpleNamespace(
            Model=[SimpleNamespace(p_base=100.0, u_unit="kV", p_unit="kW", i_unit="kA")],
            ACNode=[],
            DCNode=[
                SimpleNamespace(idx=1, vbase=1.0, voltage=1.0),
                SimpleNamespace(idx=2, vbase=0.5, voltage=0.5),
            ],
            DCDCConverter=[
                SimpleNamespace(
                    idx=1,
                    i_node=1,
                    j_node=2,
                    i_control_type="NONE",
                    j_control_type="I",
                    p_set=0.0,
                    i_set=0.1,
                    v_set=0.5,
                    i_p=0.0,
                    j_p=0.0,
                    i_c=0.0,
                    j_c=0.0,
                )
            ],
        )
        normalize_model_named_units(fake_model)
        self.assertAlmostEqual(float(fake_model.DCDCConverter[0].i_set), 0.5, places=6)

        # 2) DCDC 无实根损耗时 DCPowerFlowCalc 不得伪收敛
        rows_infeasible = {
            "Model": {"header_list": ["p_base", "u_unit", "p_unit", "i_unit"], "rows": [["100", "kV", "kW", "kA"]]},
            "DCNode": {
                "header_list": ["idx", "name", "vbase", "voltage", "run_stat"],
                "rows": [
                    ["1", "DC1", "1.0", "1.0", "1"],
                    ["2", "DC2", "1.0", "1.0", "1"],
                ],
            },
            "DCGenerator": {
                "header_list": ["idx", "name", "node", "control_type", "v_set", "p_set", "run_stat"],
                "rows": [
                    ["1", "G1", "1", "V", "1.0", "0.0", "1"],
                    ["2", "G2", "2", "V", "1.0", "0.0", "1"],
                ],
            },
            "DCDCConverter": {
                "header_list": ["idx", "name", "i_node", "j_node", "r1", "r2", "i_control_type", "j_control_type", "p_set", "i_set", "v_set", "run_stat"],
                "rows": [
                    ["1", "DCDC1", "1", "2", "0.0", "1.0", "P", "NONE", "-200.0", "0.0", "1.0", "1"],
                ],
            },
        }
        ppc_inf = build_dc_ppc_from_efile_rows("mem_inf.e", rows_infeasible)
        dc_calc = DCPowerFlowCalc(ppc_inf)
        rc = dc_calc.run()
        self.assertNotEqual(rc, 0)
        self.assertFalse(dc_calc.converged)
        self.assertIn("infeasible", dc_calc.failure_reason.lower())

    def test_http_routes_value_error_400_role_guard_and_cache_epoch(self) -> None:
        """验证 HTTP 写路由 ValueError 返回 400、教员台拒绝 receive-state 及缓存 epoch 防并发污染。"""
        import io
        from email.message import Message
        from simu.http_routes import EncodedResponseCache, PolarMicrogridHandler, StaticAssetCache, _ServerContext

        with tempfile.TemporaryDirectory() as tmp_dir:
            sim = _make_simulator(tmp_dir)
            ctx = _ServerContext(
                service=sim,
                role="simulator",
                static_root=APP_ROOT / "web",
                sim_url=None,
                exchange=None,
                renewable_manager=None,
                direct_simulator_ui=False,
                static_cache=StaticAssetCache(),
                response_cache=EncodedResponseCache(),
            )

            def invoke_post(path: str, body: dict) -> tuple[int, dict]:
                raw = json.dumps(body).encode("utf-8")
                handler = PolarMicrogridHandler.__new__(PolarMicrogridHandler)
                handler.server = SimpleNamespace(_ctx=ctx)
                handler.path = path
                handler.command = "POST"
                handler.request_version = "HTTP/1.1"
                headers = Message()
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(raw))
                handler.headers = headers
                handler.rfile = io.BytesIO(raw)
                handler.wfile = io.BytesIO()
                status_holder = {"code": 0}
                handler.send_response = lambda code, message=None: status_holder.__setitem__("code", int(code))  # type: ignore[method-assign]
                handler.send_header = lambda *_a, **_kw: None  # type: ignore[method-assign]
                handler.end_headers = lambda: None  # type: ignore[method-assign]
                handler.log_message = lambda *_a, **_kw: None  # type: ignore[method-assign]
                handler.do_POST()
                body_bytes = handler.wfile.getvalue()
                return status_holder["code"], json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

            # 1) 教员台拒绝 /api/trainee/receive-state
            status_recv, _ = invoke_post("/api/trainee/receive-state", {"step_count": 1})
            self.assertIn(status_recv, (403, 404))

            # 2) 运行态切换仿真模式触发 ValueError，/api/curves 返回 400 而非 500
            sim.clock.state = "running"
            status_curve, _ = invoke_post("/api/curves", {"mode": "hour"})
            self.assertEqual(status_curve, 400)
            sim.clock.state = "stopped"

            # 3) 成功写操作递增 _post_mutation_epoch 并使缓存键更新
            epoch_before = int(getattr(ctx, "_post_mutation_epoch", 0))
            status_ok, _ = invoke_post("/api/settings", {"measurement_statuses": {}})
            self.assertEqual(status_ok, 200)
            self.assertGreater(int(getattr(ctx, "_post_mutation_epoch", 0)), epoch_before)


if __name__ == "__main__":
    unittest.main()
