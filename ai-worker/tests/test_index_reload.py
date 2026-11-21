"""Reload candidates are validated off to the side; requests pin one engine."""
import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase, main
from unittest.mock import patch

import faiss
import numpy as np
import torch
from ai_worker.api import server


class FakeModel:
    def extract_text_features(self, *_):
        return torch.ones((1, 512))


def engine():
    index = faiss.IndexFlatIP(512)
    index.add(np.ones((1, 512), dtype='float32') / np.sqrt(512))
    return dict(model=FakeModel(), tokenizer=lambda *a, **k: {'input_ids': torch.zeros((1, 1), dtype=torch.long), 'attention_mask': torch.ones((1, 1), dtype=torch.long)}, device='cpu', image_indexes={512: index}, db_vecs_512=None, reranker=None, aqe_expander=None, captions=['old-caption'], image_paths=['old.png'], product_ids=['old-product'], active_version='old-version', supported_dims=[512], meta={}, model_name='fake')


class IndexReloadTests(TestCase):
    def test_inflight_search_pins_its_version_and_mappings(self):
        original = engine()
        entered, release = threading.Event(), threading.Event()
        encode = original['model'].extract_text_features
        def blocked(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test synchronization failed')
            return encode(*args)
        with patch.object(server, 'state', original), patch.object(original['model'], 'extract_text_features', blocked):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(server.execute_text_search, 'test', 512, 'direct')
                self.assertTrue(entered.wait(5))
                candidate = dict(original, active_version='new-version', captions=['new-caption'], image_paths=['new.png'], product_ids=['new-product'])
                server.state = candidate
                release.set()
                result = future.result(timeout=5)
                self.assertEqual(result['index_version'], 'old-version')
                self.assertEqual(result['data'][0]['product_id'], 'old.png')
                self.assertEqual(result['data'][0]['caption'], 'old-caption')
                current = server.execute_text_search('test', 512, 'direct')
                self.assertEqual(current['index_version'], 'new-version')
                self.assertEqual(current['data'][0]['catalog_product_id'], 'new-product')

    def test_valid_candidate_and_corruption_leave_live_state_untouched(self):
        live = engine()
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'state', live):
            root = Path(folder)
            checkpoint = root / 'checkpoint.pt'; checkpoint.write_bytes(b'fixture checkpoint')
            sha = server._sha256_file(checkpoint)
            live['meta'] = {'checkpoint_sha256': sha}
            for filename in ('image_embeddings.index', 'text_embeddings.index'):
                faiss.write_index(live['image_indexes'][512], str(root / filename))
            for filename, value in [('image_paths.json', ['new.png']), ('captions.json', ['new-caption']), ('product_ids.json', ['new-product'])]:
                (root / filename).write_text(json.dumps(value))
            meta = dict(index_version='new-version', checkpoint_path=str(checkpoint), checkpoint_sha256=sha, clip_model_name='fake', tokenizer_name='fake', image_size=224, full_dim=512, num_vectors=1, supported_dims=[512], normalize_mean=[0.48145466,0.4578275,0.40821073], normalize_std=[0.26862954,0.26130258,0.27577711])
            for filename, key in [('image_embeddings.index','image_index_sha256'),('text_embeddings.index','text_index_sha256'),('image_paths.json','image_paths_sha256'),('captions.json','captions_sha256'),('product_ids.json','product_ids_sha256')]:
                meta[key] = server._sha256_file(root / filename)
            (root / 'index_meta.json').write_text(json.dumps(meta))
            candidate = server.load_catalog_snapshot(folder)
            self.assertIs(server.state, live)
            self.assertEqual(candidate['active_version'], 'new-version')
            (root / 'captions.json').write_text('["corrupted"]')
            with self.assertRaises(RuntimeError):
                server.load_catalog_snapshot(folder)
            self.assertIs(server.state, live)


if __name__ == '__main__':
    main(verbosity=2)
