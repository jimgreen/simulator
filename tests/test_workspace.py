import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

import test_external_api
from test_external_inputs import MODEL, SVG
from workspace import Workspace


class WorkspaceAPITest(unittest.TestCase):
    post = test_external_api.ExternalAPITest.post
    tearDown = test_external_api.ExternalAPITest.tearDown

    def setUp(self):
        test_external_api.ExternalAPITest.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        self.root.mkdir()
        self.server.app.workspace = Workspace(self.root)
        model_dir = self.root / 'simulation' / 'qinling'
        model_dir.mkdir(parents=True)
        (model_dir / 'model.e').write_bytes(MODEL)
        (model_dir / 'diagram.svg').write_bytes(SVG)
        (model_dir / 'weather.csv').write_text('time,temperature\n00:00,-8', encoding='utf-8')

    def test_relative_listing_imports_all_three_inputs(self):
        with urlopen(self.base + '/api/workspace?directory=simulation/qinling&kind=diagram') as response:
            listing = json.load(response)
        self.assertEqual(listing['entries'][0]['path'], 'simulation/qinling/diagram.svg')
        self.post('/api/model/import', {'path': 'simulation/qinling/model.e'})
        self.post('/api/boundary/import', {'path': 'simulation/qinling/weather.csv'})
        self.post('/api/diagram/import', {'path': 'simulation/qinling/diagram.svg'})
        self.assertEqual(self.twin.snapshot()['weather']['air_temp_c'], -8)
        self.assertEqual(self.twin.diagram()['source'], 'simulation/qinling/diagram.svg')

    def test_root_has_no_parent_and_files_are_paginated(self):
        self.assertIsNone(self.server.app.workspace.listing()['parent'])
        for n in range(13):
            (self.root / f'file-{n:02}.json').write_text('{}')
        data = self.server.app.workspace.listing(page=2, page_size=5)
        self.assertEqual((len(data['entries']), data['page'], data['pages']), (5, 2, 3))

    def test_invalid_paths_do_not_mutate_simulation(self):
        before = self.twin.model_summary()
        for path in ('../outside.e', '/outside.e', 'C:/outside.e', r'..\outside.e', 'simulation/../model.e'):
            with self.assertRaises(HTTPError) as error:
                self.post('/api/model/import', {'path': path})
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.twin.model_summary(), before)

    def test_external_link_is_not_listed_or_read(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'model.e').write_bytes(MODEL)
        link = self.root / 'escape'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
            self.addCleanup(link.rmdir)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(link.unlink)
        self.assertNotIn('escape', [item['name'] for item in self.server.app.workspace.listing()['entries']])
        with self.assertRaises(ValueError):
            self.server.app.workspace.read('escape/model.e', 'model')


if __name__ == '__main__':
    unittest.main()
