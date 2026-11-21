"""Readiness must fail closed before an index has been seeded."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from ai_worker.api import server
class ReadinessTests(unittest.TestCase):
    def test_live_but_not_ready_without_index(self):
        original_model=server.state['model'];original_indexes=server.state['image_indexes']
        def empty_engine():
            server.state['model']=None;server.state['image_indexes']={}
        try:
            with patch.object(server,'setup_inference_engine',empty_engine):
                with TestClient(server.app) as client:
                    self.assertEqual(client.get('/health/live').status_code,200)
                    for path in ['/health/ready','/infer/health','/infer/config']:
                        self.assertEqual(client.get(path).status_code,503)
                    self.assertEqual(client.post('/infer/search/text',data={'query':'shirt','mrl_dimension':512}).status_code,503)
                    self.assertEqual(client.post('/infer/search/image',data={'mrl_dimension':512},files={'image':('test.png',b'test','image/png')}).status_code,503)
        finally:
            server.state['model']=original_model;server.state['image_indexes']=original_indexes

if __name__=='__main__':unittest.main(verbosity=2)
