import io
import json
import os
import sys
import time

import faiss
import numpy as np
import pika
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from transformers import AutoTokenizer
from model import MRL_CrossModal_Model
from reranker import TwoStageReranker
from query_expansion import AlphaQueryExpander

RABBITMQ_HOST    = "localhost"
CHECKPOINT_PATH  = "./checkpoints/mrl_clip_epoch_3.pt"
VECTOR_DB_DIR    = "./vector_db"
IMG_BASE_DIR     = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"

SUPPORTED_DIMENSIONS = [8, 16, 32, 64, 128, 256, 512]
DEFAULT_DIMENSION    = 512
MAX_LENGTH           = 77
TOKENIZER_NAME       = 'openai/clip-vit-base-patch32'

# ── Retrieval quality config ──────────────────────────────────────────
# Two-stage reranking: use 64-dim for fast first-stage retrieval,
# then rerank with full 512-dim cosine similarity.
USE_RERANKING        = True      # Enable two-stage reranking
RERANK_STAGE1_DIM    = 64       # Dimension for fast Stage-1 retrieval
RERANK_POOL_SIZE     = 50       # Candidates to retrieve in Stage 1
RERANK_MODE          = 'cosine' # 'cosine' or 'cross_encoder'

# Alpha Query Expansion: refine text query before searching.
USE_AQE              = True      # Enable AQE (text queries only)
AQE_ALPHA            = 0.7       # Weight for original query (vs. top-k mean)
AQE_TOP_K            = 5         # Number of retrieved items used for expansion
# ─────────────────────────────────────────────────────────────────

def setup_system():
    print("[1] Initialize system...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"    -> Using device: {device}")
    
    model = MRL_CrossModal_Model().to(device)
    if os.path.exists(CHECKPOINT_PATH):
        model.load_state_dict(torch.load(CHECKPOINT_PATH, map_location=device))
        print(f"    -> Load model from {CHECKPOINT_PATH}")
    else:
        print(f"    -> WARNING: Could not find checkpoint at {CHECKPOINT_PATH}, using original model.")
        
    model.eval()

    print("[2] Initialize FAISS Indices and Metadata...")
    img_index_path = os.path.join(VECTOR_DB_DIR, "image_embeddings.index")
    if os.path.exists(img_index_path):
        base_img_index = faiss.read_index(img_index_path)
        print(f"    -> Load Image FAISS Index: {base_img_index.ntotal} vectors.")
    else:
        print("    -> ERROR: Could not find image_embeddings.index!")
        base_img_index = None

    indexes = {}
    if base_img_index is not None:
        full_vectors = _extract_raw_vectors(base_img_index)
            
        for dim in SUPPORTED_DIMENSIONS:
            vec_dim = full_vectors[:, :dim].copy()
            faiss.normalize_L2(vec_dim)
            idx = faiss.IndexFlatIP(dim)
            idx.add(vec_dim)
            indexes[dim] = idx
            
    print(f"    -> Initialized {len(indexes)} FAISS indices for MRL Dimensions.")

    txt_index_path = os.path.join(VECTOR_DB_DIR, "text_embeddings.index")
    base_txt_index = None
    if os.path.exists(txt_index_path):
        base_txt_index = faiss.read_index(txt_index_path)
        print(f"    -> Load Text FAISS Index: {base_txt_index.ntotal} vectors.")

    image_paths_list = []
    with open(os.path.join(VECTOR_DB_DIR, "image_paths.json"), "r", encoding="utf-8") as f:
        image_paths_list = json.load(f)
        
    captions_list = []
    with open(os.path.join(VECTOR_DB_DIR, "captions.json"), "r", encoding="utf-8") as f:
        captions_list = json.load(f)

    transform = transforms.Compose([
        transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073), std=(0.26862954, 0.26130258, 0.27577711))
    ])
    
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)

    # ── Retrieval quality components ─────────────────────────────────
    # Keep raw 512-dim DB vectors in memory for cosine reranking
    db_vecs_512 = None
    if base_img_index is not None:
        raw = _extract_raw_vectors(base_img_index)  # [N, 512]
        db_vecs_512 = torch.tensor(raw, dtype=torch.float32)

    reranker   = TwoStageReranker(mode=RERANK_MODE) if USE_RERANKING else None
    expander   = AlphaQueryExpander(alpha=AQE_ALPHA, top_k=AQE_TOP_K) if USE_AQE else None
    print(f"    -> Reranking: {'ON (' + RERANK_MODE + ')' if USE_RERANKING else 'OFF'}")
    print(f"    -> AQE:       {'ON (alpha=' + str(AQE_ALPHA) + ', top_k=' + str(AQE_TOP_K) + ')' if USE_AQE else 'OFF'}")
    # ─────────────────────────────────────────────────────────────────

    return (
        model, transform, tokenizer,
        indexes, base_txt_index,
        image_paths_list, captions_list,
        device,
        db_vecs_512, reranker, expander,
    )

(
    model, transform, tokenizer,
    image_indexes, base_txt_index,
    image_paths, captions,
    device,
    db_vecs_512, reranker, aqe_expander,
) = setup_system()

# helper function to extract raw vectors from FAISS index
def _extract_raw_vectors(index):
    n, dim = index.ntotal, index.d  # index.d auto return the dimension of the index
    try:
        return faiss.rev_swig_ptr(index.get_xb(), n * dim).reshape(n, dim)
    except Exception:
        return np.vstack([index.reconstruct(i) for i in range(n)])

def get_requested_dimension(props):
    headers = props.headers or {}
    raw_dimension = headers.get("mrl_dimension", DEFAULT_DIMENSION)
    try:
        dimension = int(raw_dimension)
    except (TypeError, ValueError):
        dimension = DEFAULT_DIMENSION

    if dimension not in SUPPORTED_DIMENSIONS:
        dimension = DEFAULT_DIMENSION

    return dimension

def process_query_image(image_bytes, target_dim):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_tensor = transform(img).unsqueeze(0).to(device) # type: ignore

    with torch.no_grad():
        features_512 = model.extract_image_features(img_tensor)   # [1, 512]

    search_started = time.perf_counter()

    if USE_RERANKING and db_vecs_512 is not None and RERANK_STAGE1_DIM in image_indexes:
        # Stage 1: fast 64-dim search
        query_64 = features_512[:, :RERANK_STAGE1_DIM].cpu().numpy().astype(np.float32)
        faiss.normalize_L2(query_64)
        _, stage1_raw = image_indexes[RERANK_STAGE1_DIM].search(query_64, RERANK_POOL_SIZE)
        candidates = [c for c in stage1_raw[0].tolist() if c != -1]

        # Stage 2: 512-dim cosine rerank
        ranked = reranker.rerank_with_cosine( # type: ignore
            features_512.squeeze(0).cpu(), db_vecs_512, candidates, top_k=10
        )
        indices_scores = ranked
    else:
        # Fallback: direct search at target_dim
        query_vec = features_512[:, :target_dim].cpu().numpy().astype(np.float32)
        faiss.normalize_L2(query_vec)
        distances, raw_idx = image_indexes[target_dim].search(query_vec, k=10)
        indices_scores = [
            (int(raw_idx[0][i]), float(distances[0][i]))
            for i in range(len(raw_idx[0]))
        ]

    search_latency_ms = round((time.perf_counter() - search_started) * 1000, 2)

    results = []
    for idx, score in indices_scores:
        if idx != -1 and idx < len(image_paths):
            results.append({
                "product_id": image_paths[idx],
                "file_path":  os.path.join(IMG_BASE_DIR, image_paths[idx]),
                "caption":    captions[idx],
                "distance":   score,
            })
    return results, search_latency_ms


def process_query_text(text_query, target_dim):
    tokens = tokenizer(
        text_query, padding='max_length', truncation=True,
        max_length=MAX_LENGTH, return_tensors='pt'
    )
    input_ids      = tokens['input_ids'].to(device)
    attention_mask = tokens['attention_mask'].to(device)

    with torch.no_grad():
        features_512 = model.extract_text_features(input_ids, attention_mask)  # [1, 512]

    search_started = time.perf_counter()

    if USE_RERANKING and db_vecs_512 is not None and RERANK_STAGE1_DIM in image_indexes:
        query_vec_512 = features_512.squeeze(0).cpu()  # [512]

        # AQE: refine text query (text queries benefit most from expansion)
        if USE_AQE and aqe_expander is not None:
            refined_vec = aqe_expander.expand(
                query_vec_512, db_vecs_512
            ).squeeze(0)  # [512], L2-normalized
        else:
            refined_vec = F.normalize(query_vec_512, dim=-1)

        # Stage 1: 64-dim fast search on (possibly AQE-refined) query
        query_64 = refined_vec[:RERANK_STAGE1_DIM].unsqueeze(0).numpy().astype(np.float32)
        faiss.normalize_L2(query_64)
        _, stage1_raw = image_indexes[RERANK_STAGE1_DIM].search(query_64, RERANK_POOL_SIZE)
        candidates = [c for c in stage1_raw[0].tolist() if c != -1]

        # Stage 2: 512-dim cosine rerank on refined query
        ranked = reranker.rerank_with_cosine( # type: ignore
            refined_vec, db_vecs_512, candidates, top_k=10
        )
        indices_scores = ranked
    else:
        # Fallback: direct search at target_dim
        query_vec = features_512[:, :target_dim].cpu().numpy().astype(np.float32)
        faiss.normalize_L2(query_vec)
        distances, raw_idx = image_indexes[target_dim].search(query_vec, k=10)
        indices_scores = [
            (int(raw_idx[0][i]), float(distances[0][i]))
            for i in range(len(raw_idx[0]))
        ]

    search_latency_ms = round((time.perf_counter() - search_started) * 1000, 2)

    results = []
    for idx, score in indices_scores:
        if idx != -1 and idx < len(image_paths):
            results.append({
                "product_id": image_paths[idx],
                "file_path":  os.path.join(IMG_BASE_DIR, image_paths[idx]),
                "caption":    captions[idx],
                "distance":   score,
            })
    return results, search_latency_ms

def on_request(ch, method, props, body):
    search_type = "image"
    if props.headers and "search_type" in props.headers:
        if isinstance(props.headers["search_type"], bytes):
            search_type = props.headers["search_type"].decode('utf-8')
        else:
            search_type = props.headers["search_type"]
        
    print(f"\n[x] Received search request: Type={search_type}")

    try:
        target_dim = get_requested_dimension(props)
        
        if search_type == "text":
            text_query = body.decode("utf-8")
            top_results, search_latency_ms = process_query_text(text_query, target_dim)
        else:
            top_results, search_latency_ms = process_query_image(body, target_dim)
            
        response = json.dumps({
            "status": "success",
            "data": top_results,
            "mrl_dimension": target_dim,
            "search_latency_ms": search_latency_ms,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("Error processing query:", str(e))
        response = json.dumps({"status": "error", "message": str(e)})

    ch.basic_publish(
        exchange="",
        routing_key=props.reply_to,
        properties=pika.BasicProperties(correlation_id=props.correlation_id),
        body=response,
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)
    print(" [v] Sent results back to Core API.")



connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
channel = connection.channel()
channel.queue_declare(queue="search_queue")

channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue="search_queue", on_message_callback=on_request)

print(" [*] Semantic Search AI Worker is waiting for requests. Press CTRL+C to exit.")
channel.start_consuming()
