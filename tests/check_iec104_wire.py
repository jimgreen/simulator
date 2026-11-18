"""Optional loopback wire check against the installed scdfe_s implementation.

Run separately: python tests/check_iec104_wire.py
Uses an ephemeral loopback port and does not modify SCADA databases.
"""
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from digital_twin import DigitalTwin  # noqa: E402
from iec104_bridge import ScdfeIEC104Bridge  # noqa: E402


def read_exact(client, length):
    result = b""
    while len(result) < length:
        chunk = client.recv(length - len(result))
        if not chunk:
            raise RuntimeError("IEC104 connection closed")
        result += chunk
    return result


def read_frame(client):
    header = read_exact(client, 2)
    if header[0] != 0x68:
        raise AssertionError("Invalid APDU marker")
    return header + read_exact(client, header[1])


def wait_yx(client, address, expected):
    deadline = time.monotonic() + 5
    frames = 0
    while time.monotonic() < deadline:
        frame = read_frame(client)
        if frame[2] & 1:
            continue
        frames += 1
        sequence = ((int.from_bytes(frame[2:4], "little") >> 1) + 1) % 32768
        client.sendall(b"\x68\x04\x01\x00" + (sequence << 1).to_bytes(2, "little"))
        if frame[6] != 1 or int.from_bytes(frame[10:12], "little") != 1:
            continue
        count, sequential = frame[7] & 0x7F, bool(frame[7] & 0x80)
        cursor, ioa = 12, 0
        for index in range(count):
            if not sequential or index == 0:
                ioa = int.from_bytes(frame[cursor:cursor + 3], "little")
                cursor += 3
            else:
                ioa += 1
            value = frame[cursor]
            cursor += 1
            if ioa == address and bool(value & 1) == expected:
                assert value & 0xF0 == 0, "Invalid quality flags"
                return frames
    raise AssertionError("Actual switch state not received")


def main():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    twin = DigitalTwin(model={"name": "wire-test", "devices": [
        {"id": "breaker", "name": "breaker", "type": "switch", "run": True, "closed_status": True}
    ]})
    twin.command_clock("pause")
    bridge = ScdfeIEC104Bridge(twin, port=port)
    point = next(p for p in twin.points() if p["name"] == "breaker_closed_status")
    address = bridge._server.point_address("yx", point["point_no"])
    try:
        bridge.start()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(b"\x68\x04\x07\x00\x00\x00")
            assert read_frame(client) == b"\x68\x04\x0b\x00\x00\x00", "STARTDT confirmation"
            counts = []
            for action, expected in (("open", False), ("close", True)):
                twin.operate_device("breaker", action)
                result = bridge.publish(twin.snapshot(history_limit=1))
                assert result["published"], result
                counts.append(wait_yx(client, address, expected))
            print(f"PASS scdfe_s IEC104 STARTDT / paused open-close YX; IOA={address}; received I frames={counts}")
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
