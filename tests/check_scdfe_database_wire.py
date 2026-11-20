"""Actual scdfe_s database watcher -> IEC104 loopback acceptance check.

python tests/check_scdfe_database_wire.py
Uses a temporary database and ephemeral port; no live SCADA service is changed.
"""
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from digital_twin import DigitalTwin  # noqa: E402
from scdfe_points import ScdfePointTableManager  # noqa: E402
from scdfe_realtime import ScdfeRealtimeWriter  # noqa: E402
from check_iec104_wire import read_frame, wait_yx  # noqa: E402


def wait_yc(client, address, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        frame = read_frame(client)
        if frame[2] & 1:
            continue
        sequence = ((int.from_bytes(frame[2:4], 'little') >> 1) + 1) % 32768
        client.sendall(b'\x68\x04\x01\x00' + (sequence << 1).to_bytes(2, 'little'))
        if frame[6] != 13:
            continue
        cursor, ioa = 12, 0
        for index in range(frame[7] & 0x7f):
            if not (frame[7] & 0x80) or index == 0:
                ioa = int.from_bytes(frame[cursor:cursor + 3], 'little')
                cursor += 3
            else:
                ioa += 1
            value, quality = struct.unpack_from('<fB', frame, cursor)
            cursor += 5
            if ioa == address and abs(value - expected) < .001:
                assert quality == 0
                return
    raise AssertionError('YC value not received')


def main():
    with tempfile.TemporaryDirectory() as directory:
        manager = ScdfePointTableManager(db_path=Path(directory) / 'scdfe_s.sqlite3', workspace_root=directory)
        # Load SCADA's package before importing its server (simulator also has server.py).
        manager._store_for()
        from scdfe_s.web.iec104_service import IEC104Service
        writer = ScdfeRealtimeWriter(manager)
        twin = DigitalTwin(model={'name': 'wire-test', 'devices': [
            {'id': 'breaker', 'name': 'breaker', 'type': 'switch', 'run': True, 'closed_status': True}]})
        twin.command_clock('pause')
        points = twin.points()
        yx = next(p for p in points if p['name'] == 'breaker_closed_status')
        yc = next(p for p in points if p['kind'] == 'yc')

        def commit(values=None):
            seq = writer.submit(points=points, model_name=twin.model['name'], rtu_id=104, channel_id=104,
                                values=values or twin.point_values(), clock=twin.clock())
            assert writer.wait_for(seq, 15), writer.status()

        service = None
        try:
            commit()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            service = IEC104Service(manager._store_for(), config_path=Path(directory) / 'iec104.json')
            service.configure({'bind_ip': '127.0.0.1', 'port': port, 'rtu_id': 104})
            service.start()
            with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
                client.sendall(b'\x68\x04\x07\x00\x00\x00')
                assert read_frame(client) == b'\x68\x04\x0b\x00\x00\x00'
                for action, expected in (('open', False), ('close', True)):
                    twin.operate_device('breaker', action)
                    commit()
                    wait_yx(client, yx['point_no'], expected)
                values = twin.point_values()
                values['yc'][yc['point_no']] = 123.25
                commit(values)
                wait_yc(client, 0x4001 + yc['point_no'] - 1, 123.25)
            print('PASS: simulator -> atomic scdfe_s SQLite -> existing database watcher -> IEC104 YC/YX with valid quality')
        finally:
            if service is not None:
                service.close()
            writer.close()
            manager.close()


if __name__ == '__main__':
    main()
