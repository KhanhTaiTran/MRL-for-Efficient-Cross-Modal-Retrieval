import io
import json
import os
import sys
import time

import faiss
import numpy as np
import pika
import torch
from PIL import Image
from torchvision import transforms
from transformers import AutoTokenizer
from model import MRL_CrossModal_Model # load model 

RABBITMQ_HOST = "localhost"
CHECKPOINT_PATH = "./checkpoints/mrl_clip_epoch_3.pt"
VECTOR_DB_DIR = "./vector_db"
IMG_BASE_DIR = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"

SUPPORTED_DIMENSIONS = [8, 16, 32, 64, 128, 256, 512]
DEFAULT_DIMENSION = 512
MAX_LENGTH = 77
TOKENIZER_NAME = 'openai/clip-vit-base-patch32'

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
        try:
            full_vectors = faiss.rev_swig_ptr(base_img_index.get_xb(), base_img_index.ntotal * 512).reshape(base_img_index.ntotal, 512)
        except Exception:
            full_vectors = np.vstack([base_img_index.reconstruct(i) for i in range(base_img_index.ntotal)])
            
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

    return model, transform, tokenizer, indexes, base_txt_index, image_paths_list, captions_list, device

model, transform, tokenizer, image_indexes, base_txt_index, image_paths, captions, device = setup_system()

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
    img_tensor = transform(img).unsqueeze(0).to(device)

    with torch.no_grad():
        features_512 = model.extract_image_features(img_tensor)
        query_vector = features_512[:, :target_dim].cpu().numpy().astype(np.float32)

    faiss.normalize_L2(query_vector)

    search_started = time.perf_counter()
    distances, indices = image_indexes[target_dim].search(query_vector, k=10)
    search_latency_ms = round((time.perf_counter() - search_started) * 1000, 2)

    results = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        if idx != -1:
            full_path = os.path.join(IMG_BASE_DIR, image_paths[idx])
            results.append({
                "product_id": image_paths[idx],
                "file_path": full_path,
                "caption": captions[idx],
                "distance": float(distances[0][i]),
            })
    return results, search_latency_ms

def process_query_text(text_query, target_dim):
    tokens = tokenizer(
        text_query, 
        padding='max_length', 
        truncation=True, 
        max_length=MAX_LENGTH, 
        return_tensors='pt'
    )
    input_ids = tokens['input_ids'].to(device)
    attention_mask = tokens['attention_mask'].to(device)
    
    with torch.no_grad():
        features_512 = model.extract_text_features(input_ids, attention_mask)
        query_vector = features_512[:, :target_dim].cpu().numpy().astype(np.float32)
        
    faiss.normalize_L2(query_vector)
    
    search_started = time.perf_counter()
    distances, indices = image_indexes[target_dim].search(query_vector, k=10)
    search_latency_ms = round((time.perf_counter() - search_started) * 1000, 2)
    
    results = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        if idx != -1:
            full_path = os.path.join(IMG_BASE_DIR, image_paths[idx])
            results.append({
                "product_id": image_paths[idx],
                "file_path": full_path,
                "caption": captions[idx],
                "distance": float(distances[0][i]),
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
