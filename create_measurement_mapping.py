"""Create an independent simulation device/measurement catalog using scdfe_d."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4


def create_mapping(*, workspace_root, scada_root, source, model, output, reference=None):
    root = Path(workspace_root).resolve(strict=True)
    source_path = (root / source).resolve(strict=True)
    output_path = (root / output).resolve()
    if not source_path.is_relative_to(root) or not output_path.is_relative_to(root):
        raise ValueError('输入输出必须位于工作区根目录内')
    if output_path.exists() or any(Path(str(output_path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise FileExistsError('目标数据库或 SQLite 边车文件已存在，拒绝覆盖')
    sys.path.insert(0, str(Path(scada_root).resolve()))
    from scdfe_d.service import DeviceStore, validate_database
    from tools.rebuild_scdfe_d import rebuild
    stage_dir = output_path.parent / ('.simulator-mapping-' + uuid4().hex)
    if not stage_dir.resolve().is_relative_to(root):
        raise ValueError('暂存目录越界')
    stage_dir.mkdir()
    stage = stage_dir / output_path.name
    try:
        result = rebuild(source_path.relative_to(root), model, stage.relative_to(root), workspace_root=root)
        store = DeviceStore(stage, workspace_root=root)
        try:
            with store.connection() as connection:
                connection.execute('BEGIN IMMEDIATE')
                for row in connection.execute('SELECT DISTINCT source_database FROM scada_point_mapping').fetchall():
                    old = row[0]
                    new = 'simulation/' + old[len('realtime/'):] if old.startswith('realtime/') else old
                    destination = (root / new).resolve(strict=True)
                    if not destination.is_relative_to(root / 'simulation'):
                        raise ValueError('副本不能继续引用 realtime 或工作区外的采集库')
                    connection.execute('UPDATE scada_point_mapping SET source_database=? WHERE source_database=?', (new, old))
                # This is a mapping catalog, not a copy of production measurement history.
                connection.execute('DELETE FROM measurement_value')
                connection.execute('DELETE FROM measurement_refresh')
                connection.execute('DELETE FROM input_change_log')
                store._tables(connection, sync_schema=True)
                store._write_tables(connection)
                store._audit(connection, 'simulation_mapping_created', None, {}, {'source': reference or source, 'model': model})
        finally:
            store.close()
        checked = validate_database(stage)
        if not checked['valid']:
            raise ValueError(checked['message'])
        with closing(sqlite3.connect(stage)) as connection:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not connection.execute('PRAGMA foreign_key_check').fetchone()
            result['sources'] = [r[0] for r in connection.execute('SELECT DISTINCT source_database FROM scada_point_mapping')]
        os.link(stage, output_path)  # Atomic publication; fails if another writer created the target.
        result['output'] = str(output_path)
        return result
    finally:
        # Only the explicitly named staging files are removed; no recursive deletion.
        for name in (stage.name, stage.name + '-wal', stage.name + '-shm', stage.name + '-journal'):
            stage.with_name(name).unlink(missing_ok=True)
        stage_dir.rmdir()


if __name__ == '__main__':
    root = Path(r'D:\codex\workspace').resolve()
    source = 'realtime/qinling/sqldb/scada/scdfe_d.sqlite3'
    outputs = ['simulation/qinling/sqldb/simulator/scdfe_s.sqlite3',
               'simulation/qinling/sqldb/scada/scdfe_d.sqlite3']
    for output in outputs:
        if (root / output).exists():
            raise FileExistsError(f'目标已存在，拒绝覆盖: {output}')
    snapshot = root / 'simulation/qinling/sqldb/scada' / ('.mapping-source-' + uuid4().hex + '.sqlite3')
    if not snapshot.resolve().is_relative_to(root):
        raise ValueError('参考快照越界')
    try:
        with closing(sqlite3.connect((root / source).as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(snapshot)) as destination:
                original.backup(destination)
        results = [create_mapping(workspace_root=root, scada_root=r'D:\codex\scada',
                                  source=snapshot.relative_to(root).as_posix(), reference=source,
                                  model='simulation/qinling/sqldb/model/devices.sqlite3', output=output)
                   for output in outputs]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        for suffix in ('', '-wal', '-shm', '-journal'):
            snapshot.with_name(snapshot.name + suffix).unlink(missing_ok=True)
