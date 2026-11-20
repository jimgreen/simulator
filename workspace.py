"""Read model inputs only from a configured workspace, using relative paths."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat


DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent / 'workspace'
INPUT_TYPES = {
    'database': {'.sqlite3'},
    'model': {'.e', '.json', '.zip'},
    'boundary': {'.e', '.csv', '.tsv', '.json', '.zip'},
    'diagram': {'.svg'},
}


class Workspace:
    def __init__(self, root=DEFAULT_WORKSPACE_ROOT):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('工作区根目录不存在')

    def resolve(self, relative):
        if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
                or '\x00' in relative or PureWindowsPath(relative).drive
                or PurePosixPath(relative).is_absolute()
                or (relative != '.' and any(p in ('', '.', '..') or p.endswith((' ', '.'))
                                           for p in relative.split('/')))):
            raise ValueError('请使用根目录内的相对路径，以 / 分隔，不能包含 .. 或绝对路径')
        candidate = self.root / relative
        for item in (candidate, *candidate.parents):
            if item == self.root:
                break
            try:
                info = item.lstat()
            except OSError as exc:
                raise ValueError('路径不存在或不可访问') from exc
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('工作目录不能使用符号链接或联接点')
        path = candidate.resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('文件路径不能超出工作区根目录')
        return path

    def listing(self, directory='.', kind='model', page=1, page_size=8, query=''):
        if kind not in INPUT_TYPES:
            raise ValueError('未知文件类型')
        folder = self.resolve(directory)
        if not folder.is_dir():
            raise ValueError('目录不存在')
        page_size = min(50, max(1, int(page_size)))
        rows = []
        for path in folder.iterdir():
            if path.name.startswith('.') or path.name in {'__pycache__', 'node_modules', 'rtdb-operation-logs', 'logs'}:
                continue
            if query.casefold() not in path.name.casefold():
                continue
            try:
                safe = self.resolve(path.relative_to(self.root).as_posix())
                is_directory = safe.is_dir()
                if not is_directory and (not safe.is_file() or safe.suffix.lower() not in INPUT_TYPES[kind]):
                    continue
                if not is_directory and kind == 'database' and path.name != 'devices.sqlite3':
                    continue
                rows.append({'name': path.name, 'path': path.relative_to(self.root).as_posix(),
                             'directory': is_directory, 'bytes': None if is_directory else safe.stat().st_size})
            except (OSError, ValueError):
                continue
        rows.sort(key=lambda r: (not r['directory'], r['name'].casefold()))
        pages = max(1, (len(rows) + page_size - 1) // page_size)
        page = min(pages, max(1, int(page)))
        return {'directory': directory, 'parent': None if folder == self.root else folder.parent.relative_to(self.root).as_posix(),
                'entries': rows[(page - 1) * page_size:page * page_size],
                'page': page, 'pages': pages, 'total': len(rows), 'page_size': page_size, 'kind': kind}

    def read(self, relative, kind):
        if kind not in INPUT_TYPES:
            raise ValueError('未知文件类型')
        path = self.resolve(relative)
        if not path.is_file() or path.suffix.lower() not in INPUT_TYPES[kind]:
            raise ValueError('请选择支持的输入文件')
        limit = (4 if kind == 'diagram' else 32) * 1024 * 1024
        try:
            with path.open('rb') as stream:
                data = stream.read(limit + 1)
        except OSError as exc:
            raise ValueError('文件不可访问') from exc
        if len(data) > limit:
            raise ValueError(f'文件不能超过 {limit // 1024 // 1024} MB')
        return data, path.relative_to(self.root).as_posix()
