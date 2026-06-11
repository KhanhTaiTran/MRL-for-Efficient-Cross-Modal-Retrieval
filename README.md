# Enhancing Multimodal Retrieval with Matryoshka Representation Learning

This project is a pre-thesis prototype that explores how Matryoshka Representation Learning (MRL) can improve visual search and cross-modal retrieval for an e-commerce experience.

Instead of relying on a single fixed-size embedding, MRL makes it possible to use nested representations at multiple dimensions. That lets the system trade off speed and accuracy by truncating the embedding to smaller sizes without retraining the full pipeline.

## Overview

The demo focuses on a "search by image" workflow for product discovery. A user uploads an image, the backend enqueues a retrieval task, and the worker processes that task to simulate MRL-based feature extraction.

The current implementation is a prototype, so the AI worker uses a mocked embedding extractor rather than a production MRL model. The repository is structured so the pipeline can later be replaced with a real vision encoder and vector database.

## Tech Stack

### Frontend

- Next.js App Router
- React
- Tailwind CSS
- Based on the Vercel Commerce template

### Core API

- Go 1.22
- Gin web framework
- RabbitMQ message publishing

### AI Worker

- Python 3
- FastAPI-compatible environment for future expansion
- Pika for RabbitMQ consumption
- PyTorch for embedding simulation and tensor operations

### Infrastructure

- Docker and Docker Compose
- RabbitMQ as the message broker

## Project Structure

- `frontend/`: User-facing web application with the visual search interface.
- `core-api/`: Go service that accepts upload requests and publishes retrieval tasks to RabbitMQ.
- `ai-worker/`: Python worker that consumes search tasks and simulates MRL embedding extraction.
- `docker-compose.yml`: Local orchestration for RabbitMQ, the API, and the worker.

## Architecture

1. The frontend sends an image and an MRL dimension to the core API.
2. The core API validates the request and publishes a task to RabbitMQ.
3. The AI worker consumes the task, extracts an embedding, and acknowledges the message.
4. The prototype currently logs the result instead of writing to a vector database, but the worker is designed to support that next step.

## Getting Started

### Option 1: Run with Docker Compose

Use Docker Compose to start the message broker, API, and worker together.

```bash
docker compose up --build
```

Expected services:

- RabbitMQ Management UI: http://localhost:15672
- Core API: http://localhost:8080
- Frontend: http://localhost:3000

### Option 2: Run the frontend locally

```bash
cd frontend
pnpm install
pnpm dev
```

Then open http://localhost:3000.

### Option 3: Run the core API locally

```bash
cd core-api
go run ./cmd/server
```

The API listens on port `8080` by default.

### Option 4: Run the AI worker locally

```bash
cd ai-worker
pip install -r requirements.txt
python main.py
```

The worker connects to RabbitMQ and waits for image search tasks.

## API

### Health Check

- `GET /health`

Returns a simple status payload to confirm the service is running.

### Enqueue Image Search Task

- `POST /api/upload-image`

Example request body:

```json
{
  "image_base64": "...",
  "mrl_dimension": 64
}
```

The endpoint returns `202 Accepted` when the task is successfully queued.

## Demo Features

- Upload an image to simulate product search.
- Adjust the embedding dimension to explore the MRL tradeoff between latency and accuracy.
- Trace the full request path from frontend to queue to worker.

## References

- Kusupati, A. et al. "Matryoshka Representation Learning." NeurIPS 2022. https://arxiv.org/abs/2205.13147
- Original MRL repository: https://github.com/RAIVNLab/MRL
