import io
import json
import os
import time

import faiss
import numpy as np
import pika
import torch
import torchvision.models as models
from MRL import MRL_Linear_Layer
from PIL import Image
from torchvision import transforms

RABBITMQ_HOST = "localhost"
WEIGHT_PATH = "mrl-model/resnet18_mrl_cifar100.pt"
MOCK_DATA_DIR = "mock_data"
SUPPORTED_DIMENSIONS = [8, 16, 32, 64, 128, 256, 512]
DEFAULT_DIMENSION = 64


def setup_system():
    print("[1] Loading MRL ResNet18 model...")
    device = torch.device("cpu")
    model = models.resnet18(weights=None)

    nesting_list = [8, 16, 32, 64, 128, 256, 512]
    model.fc = MRL_Linear_Layer(nesting_list, num_classes=100, efficient=False)
    model.load_state_dict(torch.load(WEIGHT_PATH, map_location=device))

    model.fc = torch.nn.Identity()
    model.eval()

    print("[2] Initializing FAISS Index and Mock DB...")
    indexes = {dim: faiss.IndexFlatL2(dim) for dim in SUPPORTED_DIMENSIONS}
    product_mapping = {}

    transform = transforms.Compose([
        transforms.Resize((32, 32)),
        transforms.ToTensor(),
        transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761)),
    ])

    if os.path.exists(MOCK_DATA_DIR):
        img_files = [f for f in os.listdir(MOCK_DATA_DIR) if f.endswith((".png", ".jpg", ".jpeg"))]
        for i, file_name in enumerate(img_files):
            img_path = os.path.join(MOCK_DATA_DIR, file_name)
            img = Image.open(img_path).convert("RGB")
            img_tensor = transform(img).unsqueeze(0)

            with torch.no_grad():
                features_512 = model(img_tensor)
                vector_512 = features_512.numpy().astype(np.float32)

            for dim, index in indexes.items():
                vector_dim = vector_512[:, :dim].copy()
                faiss.normalize_L2(vector_dim)
                index.add(vector_dim)

            product_mapping[i] = file_name

        print(f"    -> embedded {len(indexes)} FAISS indexes with {len(product_mapping)} products.")
    else:
        print("    -> WARNING: mock_data directory not found. Please create and add images.")

    return model, transform, indexes, product_mapping


model, transform, indexes, product_mapping = setup_system()


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
    img_tensor = transform(img).unsqueeze(0)

    with torch.no_grad():
        features_512 = model(img_tensor)
        query_vector = features_512[:, :target_dim].numpy().astype(np.float32)

    faiss.normalize_L2(query_vector)

    search_started = time.perf_counter()
    distances, indices = indexes[target_dim].search(query_vector, k=3)
    search_latency_ms = round((time.perf_counter() - search_started) * 1000, 2)

    results = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        if idx != -1:
            results.append({
                "product_id": product_mapping.get(idx, "unknown"),
                "distance": float(distances[0][i]),
            })
    return results, search_latency_ms


def on_request(ch, method, props, body):
    print(f"\n[x] Received search request for image (Size: {len(body)} bytes)")

    try:
        target_dim = get_requested_dimension(props)
        top_results, search_latency_ms = process_query_image(body, target_dim)
        response = json.dumps({
            "status": "success",
            "data": top_results,
            "mrl_dimension": target_dim,
            "search_latency_ms": search_latency_ms,
        })
    except Exception as e:
        print("Error processing image:", str(e))
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

print(" [*] AI Worker is waiting for requests. Press CTRL+C to exit.")
channel.start_consuming()