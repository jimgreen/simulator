"""Atomic schema changes using RTDB's own embedded-definition format."""
from functools import lru_cache
import importlib
from pathlib import Path
import sys
from types import ModuleType
from uuid import uuid4


@lru_cache(maxsize=1)
def schema_api():
    # SCADA also has a top-level `core`; keep RTDB's schema helpers isolated.
    root = Path(__file__).resolve().parent.parent / 'rtdb' / 'core'
    if not (root / 'sqlite_schema.py').is_file():
        raise RuntimeError(f'找不到 RTDB 内置结构接口：{root / "sqlite_schema.py"}')
    package = '_simulator_rtdb_schema'
    module = ModuleType(package)
    module.__path__ = [str(root)]
    sys.modules[package] = module
    return (importlib.import_module(package + '.table_schema'),
            importlib.import_module(package + '.sqlite_schema'))


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def physical(name):
    return 'rtdb_data_' + name


def read_definitions(con, path):
    _, api = schema_api()
    document = api._read_embedded_database(con, Path(path))
    return {table.eng_name: table for table in document.tables} if document else {}


def sql_type(column):
    kind = column.data_type.lower()
    if kind in {'int', 'integer', 'long', 'bool', 'boolean'}:
        return 'INTEGER'
    if kind in {'float', 'double', 'number', 'decimal'}:
        return 'REAL'
    if kind in {'str', 'string', 'text', 'varchar', 'char', 'datetime', 'date', 'time'}:
        return 'TEXT'
    raise ValueError(f'simulator 结构迁移不支持字段类型：{column.data_type}')


def _create_data(con, table_name, definition):
    parts = ['_pos INTEGER PRIMARY KEY AUTOINCREMENT']
    for i, col in enumerate(definition.columns):
        default = ''
        if col.default_value is not None:
            default = ' DEFAULT ' + con.execute('SELECT quote(?)', (col.default_value,)).fetchone()[0]
        parts.append(f'c{i} {sql_type(col)}' + (' NOT NULL' if col.primary_key else '') + default)
    con.execute(f'CREATE TABLE {quote(table_name)} ({",".join(parts)})')


def _finish_table(con, definition, database_name, label):
    _, api = schema_api()
    name, data = definition.eng_name, physical(definition.eng_name)
    columns = {name: f'c{i}' for i, name in enumerate(definition.column_names)}
    pk = ','.join(columns[key] for key in definition.primary_keys)
    con.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS {quote(data + "_primary_key")} ON {quote(data)} ({pk})')
    indexes = importlib.import_module(api.__package__ + '.sqlite_indexes')
    indexes.reconcile_indexes(con, data, definition)
    metadata = quote('rtdb_metadata_' + name)
    con.execute(f'CREATE TABLE IF NOT EXISTS {metadata} (version INTEGER PRIMARY KEY CHECK(version=1), '
                'fingerprint TEXT NOT NULL, row_count INTEGER NOT NULL)')
    count = con.execute(f'SELECT count(*) FROM {quote(data)}').fetchone()[0]
    fingerprint = api.definition_fingerprint(definition)
    con.execute(f'INSERT INTO {metadata} VALUES (1,?,?) ON CONFLICT(version) DO UPDATE SET '
                'fingerprint=excluded.fingerprint,row_count=excluded.row_count', (fingerprint, count))
    for event, delta in (('INSERT', '+1'), ('DELETE', '-1')):
        trigger = quote(data + '_count_' + event.lower())
        con.execute(f'DROP TRIGGER IF EXISTS {trigger}')
        con.execute(f'CREATE TRIGGER {trigger} AFTER {event} ON {quote(data)} BEGIN '
                    f'UPDATE {metadata} SET row_count=row_count{delta} WHERE version=1; END')
    api.write_embedded_definition(con, definition, database_name, label)


def apply_schema(con, path, mappings, *, allow_drop_columns=False):
    """Create/migrate data, keys, counts and embedded definitions in one transaction.

    Columns are mapped by logical name, so reordering is lossless. Existing
    values must already satisfy the target type. Dropping populated columns
    requires an explicit allow_drop_columns flag; failures roll back all tables.
    """
    types, api = schema_api()
    path = Path(path)
    definitions = [types.TableDefinition.from_mapping(item, path.parent) for item in mappings]
    if len({item.eng_name for item in definitions}) != len(definitions):
        raise ValueError('同一次迁移不能重复定义同一张表')
    for definition in definitions:
        for column in definition.columns:
            sql_type(column)
    savepoint = 'schema_' + uuid4().hex
    con.execute('SAVEPOINT ' + savepoint)
    try:
        existing = read_definitions(con, path)
        database_row = (con.execute('SELECT chn_name FROM rtdb_schema_database WHERE version=1').fetchone()
                        if existing else None)
        label = database_row[0] if database_row else '仿真配置与运行状态'
        api.ensure_embedded_schema(con, path.stem, label)
        for definition in definitions:
            name = definition.eng_name
            data = physical(name)
            old = existing.get(name)
            native = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if old and native:
                raise ValueError(f'{name} 同时存在旧表和 RTDB 表，请先确认数据来源')
            if old and old.to_mapping() == definition.to_mapping():
                fields = [row[1] for row in con.execute(f'PRAGMA table_info({quote(data)})')]
                if fields != ['_pos', *(f'c{i}' for i in range(len(definition.columns)))]:
                    raise ValueError(f'{name} 数据字段与内置结构不一致，拒绝覆盖')
                _finish_table(con, definition, path.stem, label)
                continue
            if old:
                old_columns = list(old.column_names)
                source_fields = [f'c{i}' for i in range(len(old_columns))]
                source, position = data, '_pos'
            elif native:
                old_columns = [row[1] for row in con.execute(f'PRAGMA table_info({quote(name)})')]
                source_fields = list(map(quote, old_columns))
                source, position = name, 'rowid'
            else:
                old_columns, source_fields, source, position = [], [], None, None
                if con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (data,)).fetchone():
                    raise ValueError(f'{data} 存在但缺少结构定义，拒绝覆盖')
            removed = set(old_columns) - set(definition.column_names)
            if removed and not allow_drop_columns:
                raise ValueError(f'{name} 删除字段需要明确迁移：{sorted(removed)}')
            stage = data + '_migration_' + uuid4().hex
            _create_data(con, stage, definition)
            if source:
                cursor = con.execute(f'SELECT {quote(position)},' + ','.join(source_fields) + f' FROM {quote(source)} ORDER BY {quote(position)}')
                insert = f'INSERT INTO {quote(stage)} VALUES ({",".join("?" for _ in range(len(definition.columns)+1))})'
                while batch := cursor.fetchmany(500):
                    new_rows = []
                    for row in batch:
                        previous = dict(zip(old_columns, row[1:]))
                        new = definition.apply_defaults({key: previous[key] for key in definition.column_names if key in previous})
                        # SQLite stores booleans as integers; validate their semantic value.
                        for column in definition.columns:
                            if column.data_type in {'bool', 'boolean'} and new.get(column.eng_name) in (0, 1):
                                new[column.eng_name] = bool(new[column.eng_name])
                        definition.validate_rows([new])
                        new_rows.append((row[0], *(new.get(key) for key in definition.column_names)))
                    con.executemany(insert, new_rows)
                cursor.close()
                sequence = con.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (source,)).fetchone()
                if sequence:
                    found = con.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (stage,)).fetchone()
                    if found:
                        con.execute('UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name=?', (sequence[0], stage))
                    else:
                        con.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)', (stage, sequence[0]))
                con.execute(f'DROP TABLE {quote(source)}')
            con.execute(f'ALTER TABLE {quote(stage)} RENAME TO {quote(data)}')
            _finish_table(con, definition, path.stem, label)
        con.execute('PRAGMA user_version=2')
        con.execute('RELEASE ' + savepoint)
    except BaseException:
        con.execute('ROLLBACK TO ' + savepoint)
        con.execute('RELEASE ' + savepoint)
        raise
    return read_definitions(con, path)


def column(name, label, kind='str', *, primary=False):
    return {'eng_name': name, 'chn_name': label, 'data_type': kind, 'primary_key': primary,
            'disp_type': '整数' if kind == 'int' else '文本', 'disp_menu': ''}


STATE_DEFINITIONS = [
    {'head': {'eng_name': 'simulator_state', 'chn_name': '仿真配置与状态'}, 'columns': [
        column('scope', '模型或全局范围', primary=True), column('section', '配置分区', primary=True),
        column('document', '配置内容 JSON'), column('updated_at', '保存时间')]},
    {'head': {'eng_name': 'simulator_operations', 'chn_name': '仿真操作日志'}, 'columns': [
        column('id', '操作编号', 'int', primary=True), column('created_at', '操作时间'),
        column('scope', '模型范围'), column('action', '操作接口'), column('detail', '操作内容 JSON')]},
]
