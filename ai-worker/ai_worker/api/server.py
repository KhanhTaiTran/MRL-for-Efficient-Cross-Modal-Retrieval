import io
import os
import sys
import json
import time
import hashlib
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple

import faiss
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, UnidentifiedImageError
from torchvision import transforms
from transformers import AutoTokenizer

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from fastapi.responses import JSONResponse

from ai_worker.models.mrl import MRL_CrossModal_Model
from ai_worker.retrieval.reranker import TwoStageReranker
from ai_worker.retrieval.query_expansion import AlphaQueryExpander
from ai_worker.paths import worker_path

# Environment & Constants
DEFAULT_CKPT = "checkpoints/mrl_fashiongen_latest.pt"
CHECKPOINT_PATH = str(worker_path(os.environ.get("CHECKPOINT_PATH", DEFAULT_CKPT)))
VECTOR_DB_DIR = str(worker_path(os.environ.get("VECTOR_DB_DIR", "vector_db")))
DEFAULT_DIMENSION = 512
MAX_LENGTH = 77
TOKENIZER_NAME = "openai/clip-vit-base-patch32"

USE_RERANKING = True
RERANK_STAGE1_DIM = 64
RERANK_POOL_SIZE = 50
RERANK_MODE = "cosine"

USE_AQE = True
AQE_ALPHA = 0.7
AQE_TOP_K = 5

INFERENCE_CONCURRENCY = int(os.environ.get("INFERENCE_CONCURRENCY", "4"))
semaphore: Optional[asyncio.Semaphore] = None

# Global Service State
state: Dict[str, Any] = {
    "model": None,
    "transform": None,
    "tokenizer": None,
    "image_indexes": {},
    "db_vecs_512": None,
    "image_paths": [],
    "captions": [],
    "reranker": None,
    "aqe_expander": None,
    "device": "cpu",
    "meta": {},
    "supported_dims": [16, 32, 64, 128, 256, 512],
    "active_version": "v1-default",
}


def _sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _extract_raw_vectors(index: faiss.Index) -> np.ndarray:
    n, dim = index.ntotal, index.d
    try:
        return faiss.rev_swig_ptr(index.get_xb(), n * dim).reshape(n, dim)
    except Exception:
        return np.vstack([index.reconstruct(i) for i in range(n)])


def validate_model_index_consistency(meta: Dict[str, Any], checkpoint_path: str, actual_ntotal: int, current_model_name: str = ""):
    expected = {
        "clip_model_name": current_model_name, "tokenizer_name": current_model_name,
        "image_size": 224, "full_dim": 512, "num_vectors": actual_ntotal,
        "normalize_mean": [0.48145466, 0.4578275, 0.40821073],
        "normalize_std": [0.26862954, 0.26130258, 0.27577711],
    }
    errors = [f"{k} mismatch: {meta.get(k)!r} != {v!r}" for k,v in expected.items() if meta.get(k) != v]
    dims = meta.get("supported_dims")
    if (not isinstance(dims, list) or not dims or
        any(type(d) is not int or d not in [16,32,64,128,256,512] for d in dims) or
        dims != sorted(set(dims)) or 512 not in dims):
        errors.append("Invalid supported_dims")
    if not meta.get("index_version"):
        errors.append("Missing index_version")
    h = meta.get("checkpoint_sha256", "")
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        errors.append("Missing or invalid checkpoint SHA-256")
    elif not os.path.isfile(checkpoint_path):
        errors.append("Checkpoint not found")
    elif _sha256_file(checkpoint_path) != h:
        errors.append("Checkpoint SHA-256 mismatch")
    if errors:
        raise RuntimeError("Model/index validation failed:\n" + "\n".join(errors))


def setup_inference_engine():
    global CHECKPOINT_PATH
    if not os.path.isfile(os.path.join(VECTOR_DB_DIR, "image_embeddings.index")):
        state["model"] = None
        state["image_indexes"] = {}
        print("No index yet; inference is live but not ready. Seed and restart to load it.")
        return
    print("=" * 60)
    print("[*] Initializing Semantic Search Inference Engine...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"    -> Compute Device: {device}")
    state["device"] = device

    # Load Metadata
    meta_path = os.path.join(VECTOR_DB_DIR, "index_meta.json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            print(f"    -> Loaded index metadata: version={meta.get('index_version')}")
        except Exception as e:
            print(f"    -> [!] Warning: Failed to read index_meta.json: {e}")

    if not os.environ.get("CHECKPOINT_PATH"):
        CHECKPOINT_PATH = str(worker_path(meta.get("checkpoint_path", DEFAULT_CKPT)))
    state["meta"] = meta
    for filename, hash_key in [("image_embeddings.index", "image_index_sha256"), ("text_embeddings.index", "text_index_sha256"), ("image_paths.json", "image_paths_sha256"), ("captions.json", "captions_sha256")]:
        if meta.get(hash_key) and _sha256_file(os.path.join(VECTOR_DB_DIR, filename)) != meta[hash_key]:
            raise RuntimeError(f"Index artifact hash mismatch: {filename}")
    state["active_version"] = meta.get("index_version", "v1-production")
    if "supported_dims" in meta and isinstance(meta["supported_dims"], list):
        state["supported_dims"] = meta["supported_dims"]

    # Load Model
    ckpt_raw = None
    model_name = os.environ.get("CLIP_MODEL_NAME", meta.get("clip_model_name", "openai/clip-vit-base-patch16"))
    if os.path.exists(CHECKPOINT_PATH):
        ckpt_raw = torch.load(CHECKPOINT_PATH, map_location=device)
        sd = ckpt_raw.get("model_state_dict", ckpt_raw) if isinstance(ckpt_raw, dict) else ckpt_raw
        patch_weight = sd.get("clip.vision_model.embeddings.patch_embedding.weight")
        if patch_weight is not None:
            if patch_weight.shape[-1] == 16:
                model_name = "openai/clip-vit-base-patch16"
            elif patch_weight.shape[-1] == 32:
                model_name = "openai/clip-vit-base-patch32"

    print(f"    -> Using backbone model: {model_name}")
    model = MRL_CrossModal_Model(model_name=model_name).to(device)
    if ckpt_raw is not None:
        sd = ckpt_raw.get("model_state_dict", ckpt_raw) if isinstance(ckpt_raw, dict) else ckpt_raw
        model.load_state_dict(sd)
        print(f"    -> Loaded checkpoint from: {CHECKPOINT_PATH}")
    else:
        print(f"    -> [!] Warning: Checkpoint not found at {CHECKPOINT_PATH}. Using uninitialized/base CLIP.")
    model.eval()
    state["model"] = model
    state["model_name"] = model_name

    # Load FAISS Index
    img_index_path = os.path.join(VECTOR_DB_DIR, "image_embeddings.index")
    if not os.path.exists(img_index_path):
        raise FileNotFoundError(f"FAISS image index not found at: {img_index_path}")

    base_img_index = faiss.read_index(img_index_path)
    actual_ntotal = base_img_index.ntotal
    if base_img_index.d != 512 or actual_ntotal == 0:
        raise RuntimeError("Index must contain non-empty 512D vectors")
    print(f"    -> Loaded base FAISS index ({actual_ntotal} vectors).")

    # Validate Consistency
    validate_model_index_consistency(meta, CHECKPOINT_PATH, actual_ntotal, model_name)

    # Slice Index for MRL dimensions
    full_vectors = _extract_raw_vectors(base_img_index)
    state["db_vecs_512"] = torch.tensor(full_vectors, dtype=torch.float32)

    image_indexes = {}
    for dim in state["supported_dims"]:
        vec_dim = full_vectors[:, :dim].copy()
        faiss.normalize_L2(vec_dim)
        idx = faiss.IndexFlatIP(dim)
        idx.add(vec_dim)
        image_indexes[dim] = idx
    state["image_indexes"] = image_indexes
    print(f"    -> Multi-dimension indices built for dims: {state['supported_dims']}")

    # Load paths and captions
    paths_file = os.path.join(VECTOR_DB_DIR, "image_paths.json")
    if os.path.exists(paths_file):
        with open(paths_file, "r", encoding="utf-8") as f:
            state["image_paths"] = json.load(f)

    captions_file = os.path.join(VECTOR_DB_DIR, "captions.json")
    if os.path.exists(captions_file):
        with open(captions_file, "r", encoding="utf-8") as f:
            state["captions"] = json.load(f)

    if len(state["image_paths"]) != actual_ntotal or len(state["captions"]) != actual_ntotal:
        raise RuntimeError("Index/path/caption mapping counts differ")

    ids_path = os.path.join(VECTOR_DB_DIR, "product_ids.json")
    if os.path.isfile(ids_path):
        with open(ids_path, encoding="utf-8") as source:
            state["product_ids"] = json.load(source)
        if len(state["product_ids"]) != actual_ntotal:
            raise RuntimeError("Product ID mapping count differs from index")

    state["transform"] = transforms.Compose([
        transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073),
                             std=(0.26862954, 0.26130258, 0.27577711))
    ])
    state["tokenizer"] = AutoTokenizer.from_pretrained(state.get("model_name", TOKENIZER_NAME))

    if USE_RERANKING:
        state["reranker"] = TwoStageReranker(mode=RERANK_MODE)
    if USE_AQE:
        state["aqe_expander"] = AlphaQueryExpander(alpha=AQE_ALPHA, top_k=AQE_TOP_K)

    print("[+] Semantic Search Inference Engine Ready!")
    print("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global semaphore
    semaphore = asyncio.Semaphore(INFERENCE_CONCURRENCY)
    setup_inference_engine()
    yield
    print("[*] Shutting down Inference Engine...")


app = FastAPI(title="AuraFind AI Inference Engine", version="2.0", lifespan=lifespan)

# Synchronous Inference Workers (executed in thread pool)

def execute_text_search(text_query: str, target_dim: int, search_mode: str) -> Dict[str, Any]:
    t_start = time.perf_counter()
    model = state["model"]
    tokenizer = state["tokenizer"]
    device = state["device"]
    image_indexes = state["image_indexes"]
    db_vecs_512 = state["db_vecs_512"]
    reranker = state["reranker"]
    aqe_expander = state["aqe_expander"]
    captions = state["captions"]

    # 1. Tokenize & Encode
    t_enc_start = time.perf_counter()
    tokens = tokenizer(
        text_query, padding="max_length", truncation=True,
        max_length=MAX_LENGTH, return_tensors="pt"
    )
    input_ids = tokens["input_ids"].to(device)
    attention_mask = tokens["attention_mask"].to(device)

    with torch.no_grad():
        features_512 = model.extract_text_features(input_ids, attention_mask)  # [1, 512]
    if device == "cuda":
        torch.cuda.synchronize()
    encode_ms = round((time.perf_counter() - t_enc_start) * 1000, 2)

    aqe_ms = 0.0
    stage1_ms = 0.0
    rerank_ms = 0.0
    stage2_dim: Optional[int] = None
    indices_scores: List[Tuple[int, float]] = []

    if search_mode == "adaptive" and USE_RERANKING and db_vecs_512 is not None and RERANK_STAGE1_DIM in image_indexes:
        stage2_dim = 512
        query_vec_512 = features_512.squeeze(0).cpu()  # [512]

        # AQE Expansion
        if USE_AQE and aqe_expander is not None:
            t_aqe_start = time.perf_counter()
            refined_vec = aqe_expander.expand(query_vec_512, db_vecs_512).squeeze(0)
            aqe_ms = round((time.perf_counter() - t_aqe_start) * 1000, 2)
        else:
            refined_vec = F.normalize(query_vec_512, dim=-1)

        # Stage 1: Fast FAISS retrieval with 64D
        t_s1_start = time.perf_counter()
        query_64 = refined_vec[:RERANK_STAGE1_DIM].unsqueeze(0).numpy().astype(np.float32)
        faiss.normalize_L2(query_64)
        _, stage1_raw = image_indexes[RERANK_STAGE1_DIM].search(query_64, RERANK_POOL_SIZE)
        candidates = [c for c in stage1_raw[0].tolist() if c != -1]
        stage1_ms = round((time.perf_counter() - t_s1_start) * 1000, 2)

        # Stage 2: 512D Cosine Reranking
        t_rr_start = time.perf_counter()
        indices_scores = reranker.rerank_with_cosine(
            refined_vec, db_vecs_512, candidates, top_k=10
        )
        rerank_ms = round((time.perf_counter() - t_rr_start) * 1000, 2)
    else:
        # Direct mode
        t_s1_start = time.perf_counter()
        query_vec = features_512[:, :target_dim].cpu().numpy().astype(np.float32)
        faiss.normalize_L2(query_vec)
        distances, raw_idx = image_indexes[target_dim].search(query_vec, k=10)
        stage1_ms = round((time.perf_counter() - t_s1_start) * 1000, 2)

        indices_scores = [
            (int(raw_idx[0][i]), float(distances[0][i]))
            for i in range(len(raw_idx[0]))
            if raw_idx[0][i] != -1
        ]

    data = []
    for idx, score in indices_scores:
        caption = captions[idx] if idx < len(captions) else ""
        data.append({
            "vector_id": idx,
            "product_id": state["image_paths"][idx],
            "catalog_product_id": state.get("product_ids", state["image_paths"])[idx],
            "similarity_score": round(float(score), 4),
            "caption": caption
        })

    worker_total_ms = round((time.perf_counter() - t_start) * 1000, 2)
    return {
        "status": "success",
        "index_version": state["active_version"],
        "data": data,
        "search_config": {
            "requested_dim": target_dim,
            "search_mode": "adaptive" if stage2_dim is not None else "direct",
            "stage1_dim": RERANK_STAGE1_DIM if stage2_dim is not None else target_dim,
            "stage2_dim": stage2_dim,
            "aqe_enabled": (USE_AQE and stage2_dim is not None and aqe_expander is not None),
        },
        "timing": {
            "encode_ms": encode_ms,
            "aqe_ms": aqe_ms,
            "stage1_ms": stage1_ms,
            "rerank_ms": rerank_ms,
            "worker_total_ms": worker_total_ms
        }
    }


def execute_image_search(image_bytes: bytes, target_dim: int, search_mode: str) -> Dict[str, Any]:
    t_start = time.perf_counter()
    model = state["model"]
    transform = state["transform"]
    device = state["device"]
    image_indexes = state["image_indexes"]
    db_vecs_512 = state["db_vecs_512"]
    reranker = state["reranker"]
    captions = state["captions"]

    # 1. Decode & Preprocess & Encode
    t_enc_start = time.perf_counter()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_tensor = transform(img).unsqueeze(0).to(device)

    with torch.no_grad():
        features_512 = model.extract_image_features(img_tensor)   # [1, 512]
    if device == "cuda":
        torch.cuda.synchronize()
    encode_ms = round((time.perf_counter() - t_enc_start) * 1000, 2)

    stage1_ms = 0.0
    rerank_ms = 0.0
    stage2_dim: Optional[int] = None
    indices_scores: List[Tuple[int, float]] = []

    if search_mode == "adaptive" and USE_RERANKING and db_vecs_512 is not None and RERANK_STAGE1_DIM in image_indexes:
        stage2_dim = 512
        # Stage 1: Fast FAISS retrieval with 64D
        t_s1_start = time.perf_counter()
        query_64 = features_512[:, :RERANK_STAGE1_DIM].cpu().numpy().astype(np.float32)
        faiss.normalize_L2(query_64)
        _, stage1_raw = image_indexes[RERANK_STAGE1_DIM].search(query_64, RERANK_POOL_SIZE)
        candidates = [c for c in stage1_raw[0].tolist() if c != -1]
        stage1_ms = round((time.perf_counter() - t_s1_start) * 1000, 2)

        # Stage 2: 512D Cosine Reranking
        t_rr_start = time.perf_counter()
        indices_scores = reranker.rerank_with_cosine(
            features_512.squeeze(0).cpu(), db_vecs_512, candidates, top_k=10
        )
        rerank_ms = round((time.perf_counter() - t_rr_start) * 1000, 2)
    else:
        # Direct mode
        t_s1_start = time.perf_counter()
        query_vec = features_512[:, :target_dim].cpu().numpy().astype(np.float32)
        faiss.normalize_L2(query_vec)
        distances, raw_idx = image_indexes[target_dim].search(query_vec, k=10)
        stage1_ms = round((time.perf_counter() - t_s1_start) * 1000, 2)

        indices_scores = [
            (int(raw_idx[0][i]), float(distances[0][i]))
            for i in range(len(raw_idx[0]))
            if raw_idx[0][i] != -1
        ]

    data = []
    for idx, score in indices_scores:
        caption = captions[idx] if idx < len(captions) else ""
        data.append({
            "vector_id": idx,
            "product_id": state["image_paths"][idx],
            "catalog_product_id": state.get("product_ids", state["image_paths"])[idx],
            "similarity_score": round(float(score), 4),
            "caption": caption
        })

    worker_total_ms = round((time.perf_counter() - t_start) * 1000, 2)
    return {
        "status": "success",
        "index_version": state["active_version"],
        "data": data,
        "search_config": {
            "requested_dim": target_dim,
            "search_mode": "adaptive" if stage2_dim is not None else "direct",
            "stage1_dim": RERANK_STAGE1_DIM if stage2_dim is not None else target_dim,
            "stage2_dim": stage2_dim,
            "aqe_enabled": False,  # AQE not applied to image queries
        },
        "timing": {
            "encode_ms": encode_ms,
            "aqe_ms": 0.0,
            "stage1_ms": stage1_ms,
            "rerank_ms": rerank_ms,
            "worker_total_ms": worker_total_ms
        }
    }


# -------------------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------------------

def inference_ready():
    return state["model"] is not None and bool(state["image_indexes"])


@app.get("/health/live")
async def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/infer/health")
async def health_check():
    ready = inference_ready()
    return JSONResponse(status_code=200 if ready else 503, content={
        "status": "ok" if ready else "not_ready",
        "model_loaded": state["model"] is not None,
        "index_loaded": bool(state["image_indexes"]),
        "active_index_version": state["active_version"],
        "device": state["device"],
    })


@app.get("/infer/config")
async def get_config():
    if not inference_ready():
        raise HTTPException(status_code=503, detail="Search index is not ready")
    return {
        "status": "success",
        "supported_dims": state["supported_dims"],
        "active_index_version": state["active_version"],
        "search_mode_default": "adaptive",
        "default_dim": DEFAULT_DIMENSION,
        "dataset_name": state["meta"].get("dataset_name", "legacy"),
        "dataset_split": state["meta"].get("dataset_split"),
        "num_vectors": state["meta"].get("num_vectors"),
        "num_products": state["meta"].get("num_products"),
    }


@app.post("/infer/search/text")
async def search_by_text(
    query: str = Form(...),
    mrl_dimension: int = Form(DEFAULT_DIMENSION),
    search_mode: str = Form("adaptive"),
):
    if not inference_ready():
        raise HTTPException(status_code=503, detail="Search index is not ready")
    if not query.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query text cannot be empty.")

    if mrl_dimension not in state["supported_dims"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported mrl_dimension: {mrl_dimension}. Supported: {state['supported_dims']}"
        )

    mode = search_mode.lower()
    if mode not in ("direct", "adaptive"):
        raise HTTPException(status_code=400, detail="Invalid search_mode")

    loop = asyncio.get_running_loop()
    async with semaphore:
        try:
            result = await loop.run_in_executor(None, execute_text_search, query, mrl_dimension, mode)
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"status": "error", "message": str(e)}
            )


@app.post("/infer/search/image")
async def search_by_image(
    image: UploadFile = File(...),
    mrl_dimension: int = Form(DEFAULT_DIMENSION),
    search_mode: str = Form("adaptive"),
):
    if not inference_ready():
        raise HTTPException(status_code=503, detail="Search index is not ready")
    if mrl_dimension not in state["supported_dims"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported mrl_dimension: {mrl_dimension}. Supported: {state['supported_dims']}"
        )

    mode = search_mode.lower()
    if mode not in ("direct", "adaptive"):
        raise HTTPException(status_code=400, detail="Invalid search_mode")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded image file is empty.")

    loop = asyncio.get_running_loop()
    async with semaphore:
        try:
            result = await loop.run_in_executor(None, execute_image_search, image_bytes, mrl_dimension, mode)
            return JSONResponse(content=result)
        except (UnidentifiedImageError, OSError) as e:
            raise HTTPException(status_code=400, detail="Invalid image") from e
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"status": "error", "message": str(e)}
            )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ai_worker.api.server:app", host="0.0.0.0", port=8001, reload=False)
