"""Read the business model from devices.sqlite3 without modifying its contents."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from model_import import model_from_tables


MODEL_FILENAME = 'devices.sqlite3'
DEFAULT_MODEL_DIRECTORY = 'simulation/qinling/sqldb/model'
MAX_MODEL_ROWS = 200_000


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def read_model_database(workspace, directory):
    folder = workspace.resolve(directory)
    if not folder.is_dir():
        raise ValueError('请选择电网数据库所在目录')
    relative = (folder / MODEL_FILENAME).relative_to(workspace.root).as_posix()
    path = workspace.resolve(relative)
    if not path.is_file():
        raise ValueError('目录内必须存在 devices.sqlite3 数据库')
    # SQLite may consult WAL/SHM files even when the main database is read-only.
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            workspace.resolve(sidecar.relative_to(workspace.root).as_posix())
    started = time.perf_counter()
    blocks, counts = {}, []
    total = 0
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA trusted_schema=OFF')
            con.set_progress_handler(lambda: time.perf_counter() - started > 10, 10000)
            con.execute('BEGIN')  # One consistent snapshot across all model tables.
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            embedded = {'rtdb_schema_tables', 'rtdb_schema_columns'}.issubset(tables)
            if embedded:
                names = [r[0] for r in con.execute('SELECT table_name FROM rtdb_schema_tables ORDER BY ordinal')]
                definitions = {}
                for name, ordinal, field in con.execute('SELECT table_name,ordinal,eng_name FROM rtdb_schema_columns ORDER BY table_name,ordinal'):
                    definitions.setdefault(name, []).append((ordinal, field))
            else:
                names = sorted(name for name in tables if not name.startswith(('sqlite_', 'rtdb_')))
            for name in names:
                physical = 'rtdb_data_' + name if embedded else name
                if physical not in tables:
                    raise ValueError(f'模型数据表缺失：{name}')
                actual = [r[1] for r in con.execute('PRAGMA table_info(' + _quote(physical) + ')')]
                if embedded:
                    fields = definitions.get(name, [])
                    if not fields or [x[0] for x in fields] != list(range(len(fields))):
                        raise ValueError(f'模型字段定义无效：{name}')
                    columns = ['c' + str(i) for i in range(len(fields))]
                    labels = [x[1] for x in fields]
                    if len(set(labels)) != len(labels) or not set(columns + ['_pos']).issubset(actual):
                        raise ValueError(f'模型字段与数据库不一致：{name}')
                    order = ' ORDER BY _pos'
                else:
                    columns = labels = actual
                    order = ' ORDER BY idx' if 'idx' in actual else ''
                rows = con.execute('SELECT ' + ','.join(map(_quote, columns)) + ' FROM ' + _quote(physical) + order).fetchmany(MAX_MODEL_ROWS - total + 1)
                total += len(rows)
                if total > MAX_MODEL_ROWS:
                    raise ValueError('模型记录数超过 200000 条限制')
                blocks[name] = [dict(zip(labels, row)) for row in rows]
                counts.append({'name': name, 'rows': len(rows)})
            con.rollback()
    except sqlite3.Error as exc:
        raise ValueError('devices.sqlite3 无法读取、结构无效或数据库正忙') from exc
    if not blocks.get('ACNode') and not blocks.get('DCNode'):
        raise ValueError('devices.sqlite3 缺少有效的 ACNode / DCNode 电网节点表')
    model = model_from_tables(blocks, source_name=relative, source_format='sqlite-business-model')
    model['metadata']['database'] = {'filename': MODEL_FILENAME, 'tables': counts, 'table_count': len(counts),
                                      'row_count': total, 'layout': 'rtdb-embedded-schema' if embedded else 'named-tables'}
    return model, {'directory': folder.relative_to(workspace.root).as_posix(), 'database': relative,
                   'filename': MODEL_FILENAME, 'engine': 'SQLite', 'read_only': True,
                   **model['metadata']['database'], 'device_count': len(model['devices']),
                   'node_count': len(model['topology']['nodes']), 'edge_count': len(model['topology']['edges']),
                   'warnings': model['metadata'].get('warnings', []),
                   'loaded_at': datetime.now(timezone.utc).isoformat(),
                   'load_ms': round((time.perf_counter() - started) * 1000, 3)}


class ModelDatabaseSource:
    def __init__(self, workspace, *, directory=None, config_file=None):
        self.workspace = workspace
        self.config_file = Path(config_file) if config_file else None
        self.directory = directory
        if self.directory is None and self.config_file and self.config_file.is_file():
            saved = json.loads(self.config_file.read_text(encoding='utf-8'))
            if Path(saved.get('workspace_root', '')).resolve() == workspace.root:
                self.directory = saved['directory']
        if self.directory is None:
            self.directory = DEFAULT_MODEL_DIRECTORY
        configured = Path(self.directory)
        if configured.is_absolute():
            try:
                self.directory = configured.resolve().relative_to(workspace.root).as_posix()
            except ValueError as exc:
                raise ValueError('电网数据库目录必须位于工作区根目录内') from exc
        else:
            self.directory = str(self.directory).replace(os.sep, '/')
        self.info = None

    def prepare(self, directory=None):
        return read_model_database(self.workspace, self.directory if directory is None else directory)

    def remember(self, directory):
        if self.config_file is None:
            return
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_name(self.config_file.name + '.' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'workspace_root': str(self.workspace.root), 'directory': directory,
                                            'filename': MODEL_FILENAME}, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.config_file)
        finally:
            temporary.unlink(missing_ok=True)

    def activate(self, info):
        self.directory = info['directory']
        self.info = info

    def status(self):
        return dict(self.info or {}, directory=self.directory, filename=MODEL_FILENAME,
                    default_directory=DEFAULT_MODEL_DIRECTORY, engine='SQLite', read_only=True)
