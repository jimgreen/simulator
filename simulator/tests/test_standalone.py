import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import contextlib, io, json, os, runpy, sys
from pathlib import Path
script, forbidden, mode = sys.argv[1:]
forbidden = Path(forbidden).resolve()
def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).resolve()
        if path.is_relative_to(forbidden) or 'power_simu_web' in str(path).lower():
            raise RuntimeError('Access outside the relocated app: ' + str(path))
sys.addaudithook(guard)
namespace = runpy.run_path(script, run_name='console_probe')
output = io.StringIO()
with contextlib.redirect_stdout(output):
    namespace['main'](['--check'])
info = json.loads(output.getvalue())
if mode == 'flow':
    from simu.service import PolarMicrogridSimulator
    models = Path(info['models_dir'])
    candidates = sorted(p.parent for p in models.glob('*/model.e'))
    model = models / '秦岭站' if (models / '秦岭站' / 'model.e').is_file() else candidates[0]
    service = PolarMicrogridSimulator(
        sim_dir=model, runtime_dir=Path(info['runtime_dir']) / model.name,
        model_id=model.name, model_name=model.name, noise_std=0,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot = service.step()
    info['result'] = snapshot['result']
    info['compute'] = snapshot['compute']
    info['summary'] = snapshot['summary']
print(json.dumps(info, ensure_ascii=False))
'''


class StandaloneTests(unittest.TestCase):
    def probe(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / 'relocated console'
            shared_src = ROOT.parent / 'shared'
            shared_dst = root / 'shared'
            shutil.copytree(ROOT, app, ignore=shutil.ignore_patterns(
                'data', '__pycache__', 'log', 'runtime', '.venv', '*.pyc', '.ruff_cache'))
            shutil.copytree(shared_src, shared_dst, ignore=shutil.ignore_patterns(
                '__pycache__', '*.pyc', '.ruff_cache'))
            settings = json.loads((ROOT / 'startup.json').read_text(encoding='utf-8'))
            source = (ROOT / settings.get('data_dir', 'data')).resolve()
            source_models = (ROOT / settings['models_dir']).resolve() if 'models_dir' in settings else source / 'models'
            data = root / 'external data'
            shutil.copytree(source / 'lf', data / 'lf')
            shutil.copytree(source_models, data / 'models')
            settings.pop('models_dir', None)
            settings.pop('runtime_dir', None)
            settings['data_dir'] = '../external data'
            (app / 'startup.json').write_text(json.dumps(settings), encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-I', '-X', 'utf8', '-c', PROBE,
                 str(app / 'run.py'), str(ROOT.parent), mode],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(result.stdout)
            self.assertEqual(Path(info['data_dir']), data)
            self.assertEqual(Path(info['models_dir']), data / 'models')
            self.assertEqual(Path(info['runtime_dir']), data / 'runtime')
            self.assertEqual(Path(info['lf_parameters']), data / 'lf/lf.para')
            for name in ('simu_loop', 'simu.server', 'simu.service', 'ac_lf', 'dc_lf', 'hybrid_lf'):
                mod_path = Path(info['modules'][name])
                self.assertTrue(
                    mod_path.is_relative_to(app) or mod_path.is_relative_to(shared_dst),
                    f"{name}: {mod_path}",
                )
            self.assertTrue(
                all(
                    Path(p).is_relative_to(app) or Path(p).is_relative_to(shared_dst)
                    for p in info['modules'].values()
                )
            )
            if mode == 'flow':
                self.assertEqual(info['compute']['status'], 'ok')
                self.assertGreater(info['result']['updated'], 0)
                self.assertEqual(info['result']['missing'], 0)
                self.assertEqual(info['summary']['valid_scada_count'], info['summary']['scada_count'])
                for field in ('real_file', 'scada_file'):
                    self.assertTrue(Path(info['result'][field]).is_relative_to(data / 'runtime'))
            return info

    def test_relocated_dependencies(self):
        info = self.probe('check')
        settings = json.loads((ROOT / 'startup.json').read_text(encoding='utf-8'))
        self.assertEqual(info['port'], settings['port'])

    def test_relocated_power_flow_without_repository_access(self):
        self.probe('flow')


if __name__ == '__main__':
    unittest.main()
