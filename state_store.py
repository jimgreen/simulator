"""Transactional SQLite storage for simulator settings, checkpoints and edits."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import sqlite3
import threading

from rtdb_schema import STATE_DEFINITIONS, apply_schema, physical, read_definitions, schema_api


DEFAULT_STATE_DIRECTORY = 'simulation/qinling/sqldb/simulator'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class SimulatorStateStore:
    def __init__(self, workspace, directory=DEFAULT_STATE_DIRECTORY):
        configured = Path(directory)
        if configured.is_absolute():
            try:
                directory = configured.relative_to(workspace.root).as_posix()
            except ValueError as exc:
                raise ValueError('仿真状态库必须位于工作区根目录内') from exc
        if (not isinstance(directory, str) or not directory or '\\' in directory or ':' in directory
                or PureWindowsPath(directory).drive or PurePosixPath(directory).is_absolute()
                or any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in directory.split('/'))):
            raise ValueError('仿真状态库目录必须是根目录内的相对目录')
        relative = []
        for part in directory.split('/'):
            relative.append(part)
            folder = workspace.root.joinpath(*relative)
            if not folder.exists():
                folder.mkdir()
            workspace.resolve('/'.join(relative))
        self.path = workspace.root / directory / 'simulator.sqlite3'
        for suffix in ('', '-wal', '-shm', '-journal'):
            file = self.path.with_name(self.path.name + suffix)
            if file.exists() or file.is_symlink():
                workspace.resolve(file.relative_to(workspace.root).as_posix())
        self.relative_path = self.path.relative_to(workspace.root).as_posix()
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._schema_version = None
        try:
            self._con.execute('PRAGMA journal_mode=WAL')
            self._con.execute('PRAGMA synchronous=FULL')
            with self._transaction(write=True):
                existing = read_definitions(self._con, self.path)
                desired = []
                for mapping in STATE_DEFINITIONS:
                    previous = existing.get(mapping['head']['eng_name'])
                    # Preserve user-added columns, order and labels on restart.
                    desired.append(previous.to_mapping() if previous else mapping)
                self._validate_owned(desired)
                apply_schema(self._con, self.path, desired)
                self._refresh_schema()
        except BaseException:
            self._con.close()
            raise

    @contextmanager
    def _transaction(self, *, write=False):
        self._con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield
            self._con.commit()
        except BaseException:
            self._con.rollback()
            raise

    def _validate_owned(self, mappings):
        types, _ = schema_api()
        required = {item['head']['eng_name']: item for item in STATE_DEFINITIONS}
        for mapping in mappings:
            definition = types.TableDefinition.from_mapping(mapping, self.path.parent)
            expected = required.get(definition.eng_name)
            if not expected:
                continue
            fields = {col.eng_name: col for col in definition.columns}
            for item in expected['columns']:
                actual = fields.get(item['eng_name'])
                if actual is None or actual.data_type != item['data_type'] or actual.primary_key != item['primary_key']:
                    raise ValueError(f'{definition.eng_name}.{item["eng_name"]} 是仿真必需字段，不能删除或改变类型/主键')
            expected_keys = {item['eng_name'] for item in expected['columns'] if item['primary_key']}
            if set(definition.primary_keys) != expected_keys:
                raise ValueError(f'{definition.eng_name} 不能改变仿真使用的主键')

    def _refresh_schema(self):
        version = self._con.execute('PRAGMA schema_version').fetchone()[0]
        if version != self._schema_version:
            definitions = read_definitions(self._con, self.path)
            self._validate_owned([definition.to_mapping() for definition in definitions.values()])
            if not {'simulator_state', 'simulator_operations'} <= definitions.keys():
                raise ValueError('仿真状态库缺少必需表的内置定义')
            self._definitions = definitions
            self._fields = {name: {field: f'c{i}' for i, field in enumerate(definition.column_names)}
                            for name, definition in definitions.items()}
            self._schema_version = version

    def update_schema(self, mappings):
        """The sole DDL entry point: data and embedded RTDB definitions commit together."""
        mappings = list(mappings)
        self._validate_owned(mappings)
        with self._lock, self._transaction(write=True):
            apply_schema(self._con, self.path, mappings)
        self._schema_version = None

    def _insert(self, name, rows, suffix=''):
        definition = self._definitions[name]
        fields = ','.join(self._fields[name].values())
        sql = f'INSERT INTO {physical(name)} ({fields}) VALUES ({",".join("?" for _ in definition.columns)})' + suffix
        prepared = [definition.apply_defaults(row) for row in rows]
        definition.validate_rows(prepared)
        self._con.executemany(sql, [tuple(row.get(field) for field in definition.column_names) for row in prepared])

    def load(self, scope):
        with self._lock, self._transaction():
            self._refresh_schema()
            fields = self._fields['simulator_state']
            return {section: json.loads(document) for section, document in
                    self._con.execute(f'SELECT {fields["section"]},{fields["document"]} FROM rtdb_data_simulator_state '
                                      f'WHERE {fields["scope"]}=?', (scope,))}

    def save(self, scope, sections, *, settings=None, action=None, detail=None):
        now = datetime.now(timezone.utc).isoformat()
        rows = [(scope, key, encode(value), now) for key, value in sections.items()]
        if settings is not None:
            rows.extend(('global', key, encode(value), now) for key, value in settings.items())
        # Serialization precedes BEGIN; no partial updates survive a failed write.
        operation = encode(detail or {}) if action else None
        with self._lock, self._transaction(write=True):
            self._refresh_schema()
            fields = self._fields['simulator_state']
            scope_field, section, document, updated = (fields[key] for key in ('scope', 'section', 'document', 'updated_at'))
            suffix = (f' ON CONFLICT({scope_field},{section}) DO UPDATE SET {document}=excluded.{document},{updated}=excluded.{updated} '
                      f'WHERE rtdb_data_simulator_state.{document} != excluded.{document}')
            self._insert('simulator_state', [dict(zip(('scope', 'section', 'document', 'updated_at'), row)) for row in rows], suffix)
            if action:
                id_field = self._fields['simulator_operations']['id']
                # Keep legacy AUTOINCREMENT high-water marks even after deletion.
                next_id = self._con.execute(f'SELECT max(coalesce((SELECT max({id_field}) FROM rtdb_data_simulator_operations),0),'
                                           "coalesce((SELECT seq FROM sqlite_sequence WHERE name='rtdb_data_simulator_operations'),0))+1").fetchone()[0]
                self._insert('simulator_operations', [{'id': next_id, 'created_at': now, 'scope': scope,
                                                      'action': action, 'detail': operation}])
                self._con.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='rtdb_data_simulator_operations'", (next_id,))

    def status(self):
        with self._lock, self._transaction():
            self._refresh_schema()
            updated = self._fields['simulator_state']['updated_at']
            last = self._con.execute(f'SELECT max({updated}) FROM rtdb_data_simulator_state').fetchone()[0]
            count = self._con.execute('SELECT row_count FROM rtdb_metadata_simulator_operations WHERE version=1').fetchone()[0]
        return {'database': self.relative_path, 'engine': 'SQLite', 'last_saved_at': last,
                'operation_count': count, 'checkpoint_seconds': 5, 'schema_format': 'rtdb-embedded', 'schema_version': 2}

    def operations(self, limit=50):
        with self._lock, self._transaction():
            self._refresh_schema()
            fields = self._fields['simulator_operations']
            selected = ','.join(fields[key] for key in ('id', 'created_at', 'action', 'detail'))
            rows = self._con.execute(f'SELECT {selected} FROM rtdb_data_simulator_operations ORDER BY {fields["id"]} DESC LIMIT ?',
                                     (min(200, max(1, int(limit))),)).fetchall()
        return [{'id': row[0], 'created_at': row[1], 'action': row[2], 'detail': json.loads(row[3])} for row in rows]

    def close(self):
        with self._lock:
            self._con.close()
