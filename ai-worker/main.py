import io
import json
import os

import faiss
import numpy as np
import pika
import torch
import torchvision.models as models
# import MRL of paper
from MRL import MRL_Linear_Layer
from PIL import Image
from torchvision import transforms

# --- Configuration ---
RABBITMQ_HOST = 'localhost' 
WEIGHT_PATH = "mrl-model/resnet18_mrl_cifar100.pt"
MOCK_DATA_DIR = "mock_data"
DIMENSION = 64  #use the 64-dim output from MRL as default for retrieval

# ---Initialization---
def setup_system():
    print("[1] Loading MRL ResNet18 model...")
    device = torch.device("cpu")
    model = models.resnet18(weights=None)
    
    #load weights 
    nesting_list = [8, 16, 32, 64, 128, 256, 512]
    model.fc = MRL_Linear_Layer(nesting_list, num_classes=100, efficient=False)
    model.load_state_dict(torch.load(WEIGHT_PATH, map_location=device))

    model.fc = torch.nn.Identity() # We only want the embedding, not the classification output
    model.eval()
    

    print("[2] Initializing FAISS Index and Mock DB...")
    index = faiss.IndexFlatL2(DIMENSION)
    product_mapping = {} # mapping from FAISS index to product info (here we just use file names as product IDs)
    
    transform = transforms.Compose([
        transforms.Resize((32, 32)), # Resize to CIFAR-100 size
        transforms.ToTensor(),
        transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761)),
    ])

    # Scan mock_data directory, embed images using MRL, and add to FAISS index
    if os.path.exists(MOCK_DATA_DIR):
        img_files = [f for f in os.listdir(MOCK_DATA_DIR) if f.endswith(('.png', '.jpg', '.jpeg'))]
        for i, file_name in enumerate(img_files):
            img_path = os.path.join(MOCK_DATA_DIR, file_name)
            img = Image.open(img_path).convert('RGB')
            img_tensor = transform(img).unsqueeze(0)
            
            with torch.no_grad():
                features_512 = model(img_tensor)
                vector_64 = features_512[:, :DIMENSION].numpy().astype(np.float32)
            
            faiss.normalize_L2(vector_64) # Normalize vector for more accurate search
            index.add(vector_64)
            product_mapping[i] = file_name # File name is used as Product ID
            
        print(f"    -> embedded {index.ntotal} products into FAISS.")
    else:
        print("    -> WARNING: mock_data directory not found. Please create and add images.")

    return model, transform, index, product_mapping

model, transform, index, product_mapping = setup_system()

# --- Process Query Image ---
def process_query_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img_tensor = transform(img).unsqueeze(0)
    
    with torch.no_grad():
        features_512 = model(img_tensor)
        query_vector = features_512[:, :DIMENSION].numpy().astype(np.float32)
        
    faiss.normalize_L2(query_vector)
    
    # Find top 3 nearest neighbors in FAISS index
    distances, indices = index.search(query_vector, k=3)
    
    results = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        if idx != -1:
            results.append({
                "product_id": product_mapping.get(idx, "unknown"),
                "distance": float(distances[0][i])
            })
    return results

# --- Listen for RabbitMQ Messages ---
def on_request(ch, method, props, body):
    print(f"\n[x] Received search request for image (Size: {len(body)} bytes)")
    
    try:
        # Receive image as bytes from Go, process it
        top_results = process_query_image(body)
        response = json.dumps({"status": "success", "data": top_results})
    except Exception as e:
        print("Error processing image:", str(e))
        response = json.dumps({"status": "error", "message": str(e)})

    # Send result back to Go in the queue (Reply_To)
    ch.basic_publish(
        exchange='',
        routing_key=props.reply_to,
        properties=pika.BasicProperties(correlation_id=props.correlation_id),
        body=response
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)
    print(" [v] Sent results back to Core API.")

connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
channel = connection.channel()
channel.queue_declare(queue='search_queue')

channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue='search_queue', on_message_callback=on_request)

print(" [*] AI Worker is waiting for requests. Press CTRL+C to exit.")
channel.start_consuming()