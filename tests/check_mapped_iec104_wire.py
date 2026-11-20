"""Loopback check of catalog RTU/point bindings and inverse scale through scdfe_s."""
from pathlib import Path
import socket
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from measurement_mapping import MeasurementMapping  # noqa: E402
from scdfe_points import ScdfePointTableManager  # noqa: E402
from scdfe_realtime import ScdfeRealtimeWriter  # noqa: E402
from test_measurement_mapping import catalog  # noqa: E402
from test_device_results import snapshot  # noqa: E402
from check_scdfe_database_wire import wait_yc  # noqa: E402
from check_iec104_wire import read_frame, wait_yx  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        catalog(root / 'devices.sqlite3')
        mapping = MeasurementMapping(root / 'devices.sqlite3', workspace_root=root)
        manager = ScdfePointTableManager(db_path=root / 'scdfe_s.sqlite3', workspace_root=root)
        manager.generate([dict(kind='yc', point_no=42, name='active'), dict(kind='yc', point_no=43, name='reactive'),
                          dict(kind='yx', point_no=84, name='switch')], model_name='mapped', rtu_id=1, channel_id=1)
        from scdfe_s.web.iec104_service import IEC104Service
        writer = ScdfeRealtimeWriter(manager, measurement_mapping=mapping)
        service = IEC104Service(manager._store_for(), config_path=root / 'iec104.json')
        data = snapshot()

        def publish():
            seq = writer.submit(points=[], model_name='mapped', rtu_id=104, channel_id=104,
                                values={}, clock=data['clock'], device_results=data)
            assert writer.wait_for(seq, 5), writer.status()
        try:
            publish()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            service.configure({'bind_ip': '127.0.0.1', 'port': port, 'rtu_id': 1})
            service.start()
            with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
                client.sendall(b'\x68\x04\x07\x00\x00\x00')
                assert read_frame(client) == b'\x68\x04\x0b\x00\x00\x00'
                data['devices'][0]['p_kw'] = 23
                publish()
                wait_yc(client, 0x4001 + 42 - 1, 10)  # 23 = source 10 * scale 2 + offset 3
                data['devices'][1]['closed_status'] = False
                publish()
                wait_yx(client, 84, False)
            print('PASS: catalog RTU 1 / YC 42 / YX 84 -> scdfe_s SQLite -> IEC104, including inverse scale/offset')
        finally:
            service.close()
            writer.close()
            manager.close()


if __name__ == '__main__':
    main()
