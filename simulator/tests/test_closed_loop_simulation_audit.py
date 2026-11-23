"""针对模拟台时序闭环仿真 6 项改造的专项回归测试。"""

from __future__ import annotations

import json
import random
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
