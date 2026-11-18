import base64
import json
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from digital_twin import DigitalTwin
from model_import import load_model_bytes
from server import AppServer, Handler
from test_external_inputs import MODEL, SVG


class ExternalAPITest(unittest.TestCase):
    def setUp(self):
        self.twin = DigitalTwin(model=load_model_bytes(MODEL))
        self.bridge = Mock()
        self.server = AppServer(('127.0.0.1', 0), Handler)
        self.server.app = SimpleNamespace(twin=self.twin, bridge=self.bridge)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def post(self, path, body):
        request = Request(self.base + path, json.dumps(body).encode(),
                          {'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_operate_updates_real_yx_and_publishes_while_paused(self):
        self.twin.command_clock('pause')
        result = self.post('/api/devices/operate', {'device_id': 'ACBreak:1', 'action': 'open'})
        self.assertTrue(result['accepted'])
        published = self.bridge.publish.call_args.args[0]
        point = next(p for p in self.twin.points() if p['name'] == 'ACBreak:1_closed_status')
        self.assertFalse(published['point_values']['yx'][point['point_no']])
        self.assertEqual(published['events'][0]['kind'], 'switch')
        self.assertFalse(published['topology']['edges'][0]['closed'])

    def test_boundary_api_publishes_and_invalid_import_is_atomic(self):
        payload = {'filename': 'weather.csv', 'data_base64': base64.b64encode(b'time,temperature\n00:00,-8').decode()}
        self.post('/api/boundary/import', payload)
        self.assertEqual(self.bridge.publish.call_count, 1)
        self.assertEqual(self.twin.snapshot()['weather']['air_temp_c'], -8)
        previous = self.twin.curves.copy()
        payload['data_base64'] = base64.b64encode(b'time,temperature\ninvalid,5').decode()
        with self.assertRaises(HTTPError) as caught:
            self.post('/api/boundary/import', payload)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.twin.curves, previous)
        self.assertEqual(self.bridge.publish.call_count, 1)

    def test_svg_upload_and_invalid_model_keeps_previous(self):
        self.post('/api/diagram/import', {'filename': 'diagram.svg', 'data_base64': base64.b64encode(SVG).decode()})
        before = self.twin.diagram()
        with self.assertRaises(HTTPError):
            self.post('/api/model/import', {'model': {'name': 'bad'}})
        self.assertEqual(self.twin.diagram(), before)
        with urlopen(self.base + '/diagram.js') as response:
            self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
