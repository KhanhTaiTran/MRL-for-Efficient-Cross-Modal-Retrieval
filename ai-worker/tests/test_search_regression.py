import io,json,copy,unittest,hashlib,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import torch
from PIL import Image
from fastapi.testclient import TestClient
from ai_worker.api import server

class PhaseMinusOne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.client.__enter__()
    @classmethod
    def tearDownClass(cls): cls.client.__exit__(None,None,None)
    def test_modes_and_dimensions(self):
        for dim in server.state['supported_dims']:
            r=self.client.post('/infer/search/text',data={'query':'red dress','mrl_dimension':dim,'search_mode':'direct'})
            self.assertEqual(r.status_code,200,r.text)
            p=r.json(); self.assertEqual(p['search_config']['stage1_dim'],dim)
            self.assertIsNone(p['search_config']['stage2_dim'])
            self.assertFalse(p['search_config']['aqe_enabled'])
            self.assertTrue(p['data'])
            for item in p['data']:
                self.assertEqual(item['product_id'],server.state['image_paths'][item['vector_id']])
                self.assertTrue(-1.0001 <= item['similarity_score'] <= 1.0001)
        p=self.client.post('/infer/search/text',data={'query':'red dress','mrl_dimension':256,'search_mode':'adaptive'}).json()
        self.assertEqual(p['search_config']['stage1_dim'],64)
        self.assertEqual(p['search_config']['stage2_dim'],512)
        self.assertTrue(p['search_config']['aqe_enabled'])
        self.assertGreater(p['timing']['worker_total_ms'],0)
    def test_image_modes(self):
        b=io.BytesIO(); Image.new('RGB',(224,224),'red').save(b,format='PNG')
        for mode in ['direct','adaptive']:
            r=self.client.post('/infer/search/image',data={'mrl_dimension':64,'search_mode':mode},files={'image':('test.png',b.getvalue(),'image/png')})
            self.assertEqual(r.status_code,200,r.text)
            self.assertFalse(r.json()['search_config']['aqe_enabled'])
    def test_bad_inputs(self):
        for fields in [dict(query='red',mrl_dimension=8),dict(query=' ',mrl_dimension=64),dict(query='red',mrl_dimension=64,search_mode='invalid')]:
            self.assertEqual(self.client.post('/infer/search/text',data=fields).status_code,400)
    def test_concurrent(self):
        def search(i):
            dim=server.state['supported_dims'][i%6]
            r=self.client.post('/infer/search/text',data={'query':f'red dress {i}','mrl_dimension':dim,'search_mode':'direct'})
            return r.status_code,r.json().get('search_config',{}).get('stage1_dim'),dim
        with ThreadPoolExecutor(max_workers=10) as pool:
            for code,actual,expected in pool.map(search,range(10)):
                self.assertEqual(code,200); self.assertEqual(actual,expected)
    def test_validation_rejects_mismatch(self):
        meta=server.state['meta']
        for key,value in [('checkpoint_sha256','0'*64),('tokenizer_name','wrong'),('image_size',123),('num_vectors',0),('supported_dims',[8,512])]:
            bad=copy.deepcopy(meta); bad[key]=value
            with self.assertRaises(RuntimeError):
                server.validate_model_index_consistency(bad,server.CHECKPOINT_PATH,meta['num_vectors'],server.state['model_name'])

if __name__=='__main__': unittest.main(verbosity=2)
