"""Exercise the product API contract without downloading model weights."""
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import faiss
import numpy as np
import torch
from fastapi.testclient import TestClient

from ai_worker.api import server
from ai_worker.indexing.search_documents import build_search_documents, write_search_documents


class FakeModel:
    def extract_text_features(self, *_):
        vector = torch.zeros((1, 512))
        vector[0, 0] = 1
        return vector


def engine(prefix="old", lexical=True):
    vectors = np.eye(2, 512, dtype="float32")
    index = faiss.IndexFlatIP(512)
    index.add(vectors)
    ids = [f"{prefix}-adidas", f"{prefix}-other"]
    rows = [
        dict(product_id=ids[0], name="Red dress", brand="adidas Originals", description="Red dress"),
        dict(product_id=ids[1], name="Blue jacket", brand="Other", description="Blue jacket"),
    ]
    payload = build_search_documents(rows) if lexical else None
    snapshot = dict(
        model=FakeModel(), tokenizer=lambda *a, **k: {
            "input_ids": torch.zeros((1, 1), dtype=torch.long),
            "attention_mask": torch.ones((1, 1), dtype=torch.long),
        }, device="cpu", image_indexes={512: index}, db_vecs_512=torch.from_numpy(vectors),
        captions=[f"{prefix} caption 0", f"{prefix} caption 1"],
        image_paths=[f"{prefix}-0.jpg", f"{prefix}-1.jpg"], product_ids=ids,
        active_version=f"{prefix}-version", supported_dims=[512], meta={},
        model_name="fake", search_documents=payload, reranker=None,
    )
    snapshot["product_retriever"] = server._product_retriever(snapshot, payload)
    return snapshot


class HybridAPITests(TestCase):
    def test_backbone_is_selected_from_actual_patch_shape(self):
        key = "clip.vision_model.embeddings.patch_embedding.weight"
        for dim in (16, 32):
            self.assertEqual(server.checkpoint_model_name({key: torch.empty(1, 1, dim, dim)}, "wrong"),
                             f"openai/clip-vit-base-patch{dim}")
        self.assertEqual(server.checkpoint_model_name({}, "custom"), "custom")
        with self.assertRaises(RuntimeError):
            server.checkpoint_model_name({key: torch.empty(1, 1, 14, 14)}, "custom")

    def test_candidate_json_eligibility_and_modes(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}), patch.object(server, "state", engine()), \
                patch.object(server, "setup_inference_engine"), TestClient(server.app) as client:
            body = dict(query="adidas", retrieval_mode="hybrid", search_mode="direct", mrl_dimension=512)
            response = client.post("/infer/search/candidates", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["index_version"], "old-version")
            self.assertEqual(result["search_config"]["effective_retrieval_mode"], "hybrid")
            self.assertEqual(result["data"][0]["catalog_product_id"], "old-adidas")
            self.assertIn("image_candidates", result["data"][0])
            self.assertEqual(client.post("/infer/search/candidates", json={**body, "eligible_product_ids": []}).json()["data"], [])
            for change in (dict(query=" "), dict(mrl_dimension=8), dict(search_mode="bad"), dict(retrieval_mode="bad")):
                self.assertEqual(client.post("/infer/search/candidates", json={**body, **change}).status_code, 400)

    def test_public_form_hybrid_and_legacy_default(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}), patch.object(server, "state", engine()), \
                patch.object(server, "setup_inference_engine"), TestClient(server.app) as client:
            body = dict(query="adidas", mrl_dimension=512, search_mode="direct")
            dense = client.post("/infer/search/text", data=body).json()
            hybrid = client.post("/infer/search/text", data={**body, "retrieval_mode": "hybrid"}).json()
            self.assertEqual(dense["search_config"]["effective_retrieval_mode"], "dense")
            self.assertEqual(hybrid["search_config"]["effective_retrieval_mode"], "hybrid")
            self.assertLessEqual(len(hybrid["data"]), 10)
            self.assertEqual(client.post("/infer/search/text", data={**body, "retrieval_mode": "bad"}).status_code, 400)

    def test_legacy_fallback_and_promoted_default_can_be_disabled(self):
        with patch.object(server, "state", engine(lexical=False)), patch.dict(os.environ, {"HYBRID_SEARCH_ENABLED": "1"}):
            result = server.execute_candidate_search("adidas", 512, "direct", "hybrid")
            self.assertEqual(result["search_config"]["effective_retrieval_mode"], "dense")
            self.assertTrue(result["search_config"]["fallback_reason"])
            self.assertEqual(server.default_text_retrieval_mode(), "dense")
        with patch.object(server, "state", engine()), patch.dict(os.environ, {"HYBRID_SEARCH_ENABLED": "0"}):
            self.assertEqual(server.default_text_retrieval_mode(), "dense")
        with patch.object(server, "state", engine()), patch.dict(os.environ, {"HYBRID_SEARCH_ENABLED": "1"}):
            self.assertEqual(server.default_text_retrieval_mode(), "hybrid")
        with patch.object(server, "state", engine()), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server.default_text_retrieval_mode(), "hybrid")
        with patch.object(server, "state", engine(lexical=False)), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server.default_text_retrieval_mode(), "dense")

    def test_inflight_hybrid_search_pins_lexical_vectors_and_mapping(self):
        original = engine()
        entered, release = threading.Event(), threading.Event()
        encode = original["model"].extract_text_features

        def blocked(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test synchronization failed")
            return encode(*args)

        with patch.object(server, "state", original), patch.object(original["model"], "extract_text_features", blocked):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(server.execute_candidate_search, "adidas", 512, "direct", "hybrid")
                self.assertTrue(entered.wait(5))
                server.state = engine("new")
                release.set()
                result = future.result(timeout=5)
        self.assertEqual(result["index_version"], "old-version")
        self.assertEqual(result["data"][0]["catalog_product_id"], "old-adidas")
        self.assertEqual(result["data"][0]["product_id"], "old-0.jpg")

    def test_bad_lexical_candidate_keeps_old_engine(self):
        live = engine()
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "state", live):
            root = Path(folder)
            checkpoint = root / "checkpoint.pt"
            checkpoint.write_bytes(b"fixture")
            sha = server._sha256_file(checkpoint)
            live["meta"] = {"checkpoint_sha256": sha}
            for filename in ("image_embeddings.index", "text_embeddings.index"):
                faiss.write_index(live["image_indexes"][512], str(root / filename))
            meta = dict(index_version="new", checkpoint_path=str(checkpoint), checkpoint_sha256=sha,
                        clip_model_name="fake", tokenizer_name="fake", image_size=224, full_dim=512,
                        num_vectors=2, supported_dims=[512], normalize_mean=[0.48145466, 0.4578275, 0.40821073],
                        normalize_std=[0.26862954, 0.26130258, 0.27577711])
            for filename, value in (("image_paths.json", live["image_paths"]), ("captions.json", live["captions"]), ("product_ids.json", live["product_ids"])):
                (root / filename).write_text(json.dumps(value))
            for name, key in (("image_embeddings.index", "image_index_sha256"), ("text_embeddings.index", "text_index_sha256"),
                              ("image_paths.json", "image_paths_sha256"), ("captions.json", "captions_sha256"), ("product_ids.json", "product_ids_sha256")):
                meta[key] = server._sha256_file(root / name)
            meta.update(write_search_documents(root, live["search_documents"]))
            (root / "index_meta.json").write_text(json.dumps(meta))
            candidate = server.load_catalog_snapshot(root)
            self.assertIs(server.state, live)
            self.assertIsNotNone(candidate["search_documents"])
            (root / "search_documents.json").write_text("{}")
            with self.assertRaises((ValueError, RuntimeError)):
                server.load_catalog_snapshot(root)
            self.assertIs(server.state, live)


if __name__ == "__main__":
    main(verbosity=2)
