"""HTTP server entry point and clock workers for the polar microgrid simulator and trainee consoles.

模型产物构建与预检逻辑已拆分至 ``simu.model_artifacts``，HTTP 请求处理与路由已拆分至
``simu.http_routes``，本模块保持所有公开及历史内部符号向后兼容。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import simu_loop

try:
    from .http_routes import (
        DEFINITION_EDIT_PATHS,
        EXTERNAL_REALTIME_INPUTS_PATH,
        LOCAL_DEFINITION_PATHS,
        LOCAL_RUNTIME_SETTINGS_PATH,
        MANUAL_DEFINITION_CHANGES_PATH,
        PACKAGE_DIR,
        PROCESS_STARTED_MONOTONIC,
        RENEWABLE_CONTROL_PATH,
        RENEWABLE_CONTROL_TREND_PATH,
        SIMULATOR_COMMAND_DELETE_PATH,
        TRAINEE_LOCAL_GET_PATHS,
        TRAINEE_LOCAL_POST_PATHS,
        TRAINEE_UI_FRAME_PATH,
        WEB_DIR,
        JsonApiError,
        ManagedThreadingHTTPServer,
        PolarMicrogridHandler,
        _current_process_memory,
        _process_health_payload,
        _require_active_service_instance_locked,
        make_http_server,
    )
    from .model_artifacts import *  # noqa: F401,F403
    from .model_artifacts import (
        CONTROL_DEFINITION_BLOCKS,
        ModelPreflightError,
        _apply_parsed_definition_archive,
        _apply_parsed_definition_archive_locked,
        _decode_optional_svg_payload,
        _decode_uploaded_definition_text,
        _merge_control_definition,
        _parse_definition_archive,
        _preflight_model_import,
        _preflight_parsed_definition_archive,
        _recover_incomplete_model_directory,
        _write_generated_model_artifacts,
        _write_json_file,
        _write_model_diagram,
        create_model_from_efile,
        import_definition_archive,
        import_definition_model,
        make_definition_archive,
        update_model_from_efile,
    )
    from .service import (
        DEFINITION_DEFAULTS_FILE,
        DIAGRAM_FILE_NAME,
        MultiModelSimulator,
        PolarMicrogridSimulator,
    )
except ImportError:  # pragma: no cover - direct module execution.
    from simu.http_routes import (
        DEFINITION_EDIT_PATHS,
        EXTERNAL_REALTIME_INPUTS_PATH,
        LOCAL_DEFINITION_PATHS,
        LOCAL_RUNTIME_SETTINGS_PATH,
        MANUAL_DEFINITION_CHANGES_PATH,
        PACKAGE_DIR,
        PROCESS_STARTED_MONOTONIC,
        RENEWABLE_CONTROL_PATH,
        RENEWABLE_CONTROL_TREND_PATH,
        SIMULATOR_COMMAND_DELETE_PATH,
        TRAINEE_LOCAL_GET_PATHS,
        TRAINEE_LOCAL_POST_PATHS,
        TRAINEE_UI_FRAME_PATH,
        WEB_DIR,
        JsonApiError,
        ManagedThreadingHTTPServer,
        PolarMicrogridHandler,
        _current_process_memory,
        _process_health_payload,
        _require_active_service_instance_locked,
        make_http_server,
    )
    from simu.model_artifacts import *  # noqa: F401,F403
    from simu.model_artifacts import (
        CONTROL_DEFINITION_BLOCKS,
        ModelPreflightError,
        _apply_parsed_definition_archive,
        _apply_parsed_definition_archive_locked,
        _decode_optional_svg_payload,
        _decode_uploaded_definition_text,
        _merge_control_definition,
        _parse_definition_archive,
        _preflight_model_import,
        _preflight_parsed_definition_archive,
        _recover_incomplete_model_directory,
        _write_generated_model_artifacts,
        _write_json_file,
        _write_model_diagram,
        create_model_from_efile,
        import_definition_archive,
        import_definition_model,
        make_definition_archive,
        update_model_from_efile,
    )
    from simu.service import (
        DEFINITION_DEFAULTS_FILE,
        DIAGRAM_FILE_NAME,
        MultiModelSimulator,
        PolarMicrogridSimulator,
    )

# 集群管理与代理网关属于 simulator 独占模块；学员台进程中不产生硬依赖。
try:
    from .simulator_cluster import SimulatorClusterManager
    from .simulator_proxy import make_simulator_proxy_server
except ImportError:
    SimulatorClusterManager = None  # type: ignore[misc,assignment]
    make_simulator_proxy_server = None  # type: ignore[misc,assignment]


CLOCK_BASE_INTERVAL_SECONDS = 1.0
ROLE_MODEL_DIRS = {
    "simulator": ("models", "simulator"),
    "trainee": ("models", "trainee"),
}


def _role_models_base_dir(sim_dir: Path, role: str) -> Path:
    parts = ROLE_MODEL_DIRS.get(role, ("models", role))
    return (sim_dir / Path(*parts)).resolve()


def _default_models_dir(sim_dir: Path, role: str) -> Path:
    return (_role_models_base_dir(sim_dir, role) / "source").resolve()


def _default_runtime_dir(sim_dir: Path, role: str) -> Path:
    return (_role_models_base_dir(sim_dir, role) / "runtime").resolve()


def _advance_clock_if_due(service: PolarMicrogridSimulator, last_step: float) -> float:
    clock = service.clock_state()
    now = time.monotonic()
    if clock["state"] != "running":
        return now
    interval_seconds = max(0.1, float(getattr(service, "compute_interval_seconds", CLOCK_BASE_INTERVAL_SECONDS) or CLOCK_BASE_INTERVAL_SECONDS))
    if now - last_step < interval_seconds:
        return last_step
    # 按理想节拍推进下次调度基线，消除求解耗时与 50ms 唤醒带来的系统性时钟漂移；严重落后时对齐当前时刻防止追赶风暴。
    scheduled_step = last_step + interval_seconds
    if now - scheduled_step > interval_seconds * 2.0:
        scheduled_step = now
    speed = max(1.0, float(clock.get("speed", 1) or 1))
    advance_seconds = max(1e-9, float(clock.get("effective_step_seconds", speed) or speed))
    try:
        service.step(advance_seconds=advance_seconds, return_snapshot=False)
    except Exception as exc:
        logging.getLogger("simu.web").exception(
            "Clock step failed for model %s; pausing simulation clock",
            getattr(service, "model_id", ""),
        )
        record_log = getattr(service, "_append_runtime_log", None)
        if callable(record_log):
            try:
                record_log(
                    "潮流计算",
                    "clock",
                    "步进异常已自动暂停",
                    f"仿真步进异常，已自动暂停时钟：{exc}",
                    level="error",
                )
            except TypeError:
                try:
                    record_log("error", "clock", f"仿真步进异常，已自动暂停时钟：{exc}")
                except Exception:
                    pass
            except Exception:
                logging.getLogger("simu.web").debug(
                    "Failed to record step exception log for model %s",
                    getattr(service, "model_id", ""),
                    exc_info=True,
                )
        try:
            if service.clock_state().get("state") == "running":
                service.control_clock({"action": "pause"})
        except Exception:
            logging.getLogger("simu.web").exception(
                "Failed to pause simulation clock after step error for model %s",
                getattr(service, "model_id", ""),
            )
        return time.monotonic()
    return scheduled_step


def start_clock_worker(service: PolarMicrogridSimulator, stop_event: threading.Event) -> threading.Thread:
    def worker() -> None:
        last_step = time.monotonic()
        while not stop_event.is_set():
            last_step = _advance_clock_if_due(service, last_step)
            stop_event.wait(0.05)

    thread = threading.Thread(target=worker, name=f"polar-microgrid-clock-{service.model_id}", daemon=True)
    thread.start()
    return thread


def start_multi_model_clock_worker(service: MultiModelSimulator, stop_event: threading.Event) -> threading.Thread:
    """并发推进多个模型的仿真时钟，避免单个慢模型串行阻塞其他模型。"""

    def worker() -> None:
        last_steps: dict[str, float] = {}
        inflight: dict[str, concurrent.futures.Future[float]] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="polar-clock"
        ) as pool:
            while not stop_event.is_set():
                current_ids = set()
                for item in service.iter_services():
                    model_id = item.model_id
                    current_ids.add(model_id)
                    future = inflight.get(model_id)
                    if future is not None:
                        if not future.done():
                            continue
                        inflight.pop(model_id, None)
                        try:
                            last_steps[model_id] = future.result()
                        except Exception:
                            logging.getLogger("simu.web").exception(
                                "Multi-model clock worker error for %s", model_id
                            )
                            last_steps[model_id] = time.monotonic()
                    clock = item.clock_state()
                    now = time.monotonic()
                    if clock["state"] != "running":
                        last_steps[model_id] = now
                        continue
                    interval_seconds = max(
                        0.1,
                        float(
                            getattr(item, "compute_interval_seconds", CLOCK_BASE_INTERVAL_SECONDS)
                            or CLOCK_BASE_INTERVAL_SECONDS
                        ),
                    )
                    prev = last_steps.setdefault(model_id, now)
                    if now - prev >= interval_seconds:
                        inflight[model_id] = pool.submit(_advance_clock_if_due, item, prev)
                for stale_id in set(last_steps) - current_ids:
                    last_steps.pop(stale_id, None)
                for stale_id in set(inflight) - current_ids:
                    if inflight[stale_id].done():
                        inflight.pop(stale_id, None)
                stop_event.wait(0.05)

    thread = threading.Thread(target=worker, name="polar-microgrid-clock-models", daemon=True)
    thread.start()
    return thread


def start_clock_workers(
    service: PolarMicrogridSimulator | MultiModelSimulator,
    stop_event: threading.Event,
) -> list[threading.Thread]:
    if hasattr(service, "iter_services"):
        return [start_multi_model_clock_worker(service, stop_event)]  # type: ignore[arg-type]
    return [start_clock_worker(service, stop_event)]  # type: ignore[arg-type]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve polar microgrid simulator or trainee console.")
    parser.add_argument(
        "--role",
        choices=("simulator", "simulator-service", "trainee"),
        default="simulator",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--sim-dir", default=str(simu_loop.SIMU_DIR))
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Directory whose direct subfolders are simulation models. Defaults to models/<role>/source.",
    )
    parser.add_argument("--model-id", default=None, help="Single model id for simulator-service mode.")
    parser.add_argument("--model-dir", default=None, help="Single source model directory for simulator-service mode.")
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--sim-url", default=None, help="Simulator API base URL for trainee proxy mode.")
    parser.add_argument("--static-root", default=None)
    parser.add_argument(
        "--service-host",
        default="127.0.0.1",
        help="Host assigned to per-model simulator services managed by the simulator proxy.",
    )
    parser.add_argument(
        "--first-service-port",
        type=int,
        default=8711,
        help="First stable port assigned to a per-model simulator service.",
    )
    parser.add_argument(
        "--service-startup-timeout-seconds",
        type=float,
        default=30.0,
        help="Maximum time for a per-model simulator service to become healthy.",
    )
    parser.add_argument("--no-worker", action="store_true", help="Do not start automatic clock worker.")
    parser.add_argument("--noise-std", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--compute-interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--power-flow-workers",
        type=int,
        default=0,
        help="Deprecated compatibility option; load flow is always embedded in simu_loop.",
    )
    parser.add_argument(
        "--power-flow-timeout-seconds",
        type=float,
        default=30.0,
        help="Deprecated compatibility option retained for existing launch scripts.",
    )
    parser.add_argument(
        "--disable-iec104",
        action="store_true",
        help="Disable the embedded IEC104 bridge inside the simulator proxy process.",
    )
    parser.add_argument(
        "--first-iec104-port",
        type=int,
        default=2405,
        help="First TCP port assigned to embedded IEC104 slave channels.",
    )
    parser.add_argument("--scada-root", default=None, help="Optional SCADA protocol library root directory.")
    parser.add_argument("--iec104-db", default=None, help="Optional SQLite database path for embedded IEC104 points.")
    parser.add_argument("--scada-web-url", default="", help="Optional external scdfe_s workbench URL.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    sim_dir = Path(args.sim_dir).resolve()
    if args.role == "simulator":
        port = args.port if args.port is not None else 8710
        runtime_dir = (
            Path(args.runtime_dir).resolve()
            if args.runtime_dir
            else _default_runtime_dir(sim_dir, "simulator")
        )
        models_dir = (
            Path(args.models_dir).resolve()
            if args.models_dir
            else _default_models_dir(sim_dir, "simulator")
        )
        static_root = Path(args.static_root).resolve() if args.static_root else WEB_DIR / "simulator"
        manager = SimulatorClusterManager(
            sim_dir=sim_dir,
            models_root=models_dir,
            runtime_root=runtime_dir,
            service_host=args.service_host,
            first_service_port=args.first_service_port,
            compute_interval_seconds=args.compute_interval_seconds,
            child_no_worker=args.no_worker,
            noise_std=args.noise_std,
            random_seed=args.seed,
            startup_timeout_seconds=args.service_startup_timeout_seconds,
            log_dir=simu_loop.ROOT_DIR / "log" / "models",
        )
        iec104_host = None
        if not args.disable_iec104:
            try:
                import scada104 as _scada104_mod

                iec104_host = _scada104_mod.create_embedded_scada104_host(
                    simulator_url=f"http://{args.host}:{port}",
                    catalog_provider=manager.models,
                    data_dir=runtime_dir.parent,
                    db_path=Path(args.iec104_db) if args.iec104_db else None,
                    scada_root=Path(args.scada_root) if args.scada_root else None,
                    first_iec104_port=args.first_iec104_port,
                    scada_web_url=args.scada_web_url,
                )
            except ImportError:
                iec104_host = None
            except Exception as exc:
                logging.getLogger("simu.web").warning("Embedded IEC104 startup skipped: %s", exc)
                iec104_host = None
        server = make_simulator_proxy_server(
            (args.host, port),
            manager,
            static_root=static_root,
            iec104_host=iec104_host,
        )
        print(f"simulator proxy: http://{args.host}:{port}/")
        print(f"iec104 console: http://{args.host}:{port}/simulator104")
        print(f"runtime dir: {runtime_dir}")
        print(f"models dir: {manager.models_root}")
        print(f"models: {', '.join(item['id'] for item in manager.models())}")
        print("data plane: browser and trainee services connect directly to per-model simulator services")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
        return 0

    if args.role == "simulator-service":
        if not str(args.model_id or "").strip():
            raise SystemExit("--model-id is required for simulator-service mode")
        if not str(args.model_dir or "").strip():
            raise SystemExit("--model-dir is required for simulator-service mode")
        port = args.port if args.port is not None else 8711
        runtime_dir = (
            Path(args.runtime_dir).resolve()
            if args.runtime_dir
            else _default_runtime_dir(sim_dir, "simulator") / str(args.model_id)
        )
        service = PolarMicrogridSimulator(
            sim_dir=Path(args.model_dir).resolve(),
            runtime_dir=runtime_dir,
            noise_std=args.noise_std,
            random_seed=args.seed,
            compute_interval_seconds=args.compute_interval_seconds,
            model_id=str(args.model_id),
            model_name=str(args.model_id),
            clear_commands_on_start_and_reset=True,
            enforce_runtime_setpoint_bounds=False,
        )
        server = make_http_server(
            (args.host, port),
            service,
            role="simulator",
            static_root=args.static_root,
            direct_simulator_ui=True,
        )
        stop_event = threading.Event()
        workers = [] if args.no_worker else start_clock_workers(service, stop_event)
        print(f"simulator service [{service.model_id}]: http://{args.host}:{port}/?ui=direct")
        print(f"runtime dir: {runtime_dir}")
        print(f"model dir: {service.sim_dir}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            for worker in workers:
                worker.join(timeout=2)
            server.shutdown()
            server.server_close()
        return 0

    port = args.port if args.port is not None else 8720
    runtime_dir = Path(args.runtime_dir).resolve() if args.runtime_dir else _default_runtime_dir(sim_dir, "trainee")
    models_dir = Path(args.models_dir).resolve() if args.models_dir else _default_models_dir(sim_dir, "trainee")
    service = MultiModelSimulator.discover(
        sim_dir=sim_dir,
        runtime_dir=runtime_dir,
        noise_std=args.noise_std,
        random_seed=args.seed,
        compute_interval_seconds=args.compute_interval_seconds,
        models_dir=models_dir,
        kernel_runner=None,
        runtime_role="trainee",
    )
    server = make_http_server(
        (args.host, port),
        service,
        role="trainee",
        static_root=args.static_root,
        sim_url=args.sim_url,
    )
    stop_event = threading.Event()
    workers = [] if args.no_worker else start_clock_workers(service, stop_event)
    print(f"trainee console: http://{args.host}:{port}/")
    print(f"runtime dir: {runtime_dir}")
    print(f"models dir: {service.models_root}")
    print(f"models: {', '.join(item['id'] for item in service.models())}")
    print("power-flow mode: embedded in simu_loop, resident model")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=2)
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
