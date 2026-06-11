import json
import logging
import os
from io import BytesIO

import pika
from mrl_model import extract_embedding_from_bytes
from pika.exceptions import AMQPConnectionError
from PIL import Image

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ai-worker")

# ─── Config ───────────────────────────────────────────────────────────────────

RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME: str = os.getenv("RABBITMQ_QUEUE", "image_search_queue")

# Full embedding dimensionality produced by the backbone model.
# MRL allows us to *truncate* this to any smaller power-of-2 dimension.
FULL_EMBEDDING_DIM: int = 768


# ─── Message Handler ──────────────────────────────────────────────────────────

def on_message(channel, method, properties, body: bytes) -> None:
    """Callback invoked for every message delivered from the queue."""
    try:
        payload = json.loads(body.decode())
    except json.JSONDecodeError as exc:
        log.error("[AI Worker] Malformed message — could not parse JSON: %s", exc)
        # Reject without re-queue so the bad message doesn't loop forever.
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    task_id: str = payload.get("task_id", "unknown")
    mrl_dim: int = int(payload.get("mrl_dimension", 64))
    image_b64: str = payload.get("image_base64", "")

    log.info(
        "[AI Worker] Received image task  task_id=%s  dim=%d",
        task_id,
        mrl_dim,
    )
    log.info(
        "[AI Worker] Extracting %d-dim vector using MRL…",
        mrl_dim,
    )

    try:
        embedding = extract_embedding_from_bytes(image_b64, target_dim=mrl_dim)
    except Exception as exc:
        log.exception("[AI Worker] Failed to extract embedding for task_id=%s", task_id)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    log.info("[AI Worker] Done  task_id=%s  embedding_shape=%s  norm=%.4f", task_id, list(embedding.shape), embedding.norm().item())

    # In a real pipeline you would:
    #   • Store the embedding in a vector DB (e.g. Qdrant, Weaviate, pgvector).
    #   • Publish results to a reply queue or update a DB row.

    # Acknowledge → message removed from queue.
    channel.basic_ack(delivery_tag=method.delivery_tag)


# ─── RabbitMQ Connection with Retry ───────────────────────────────────────────

def connect_with_retry(url: str, max_attempts: int = 10) -> pika.BlockingConnection:
    params = pika.URLParameters(url)
    params.heartbeat = 60
    params.blocked_connection_timeout = 300

    for attempt in range(1, max_attempts + 1):
        try:
            conn = pika.BlockingConnection(params)
            log.info("[AI Worker] Connected to RabbitMQ (attempt %d)", attempt)
            return conn
        except AMQPConnectionError as exc:
            log.warning(
                "[AI Worker] RabbitMQ not ready (attempt %d/%d): %s — retrying in 3 s",
                attempt,
                max_attempts,
                exc,
            )
    raise RuntimeError("Could not connect to RabbitMQ after %d attempts" % max_attempts)


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    log.info("[AI Worker] Starting — queue=%s", QUEUE_NAME)

    connection = connect_with_retry(RABBITMQ_URL)
    channel = connection.channel()

    # Declare the queue (idempotent — safe if core-api already declared it).
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    # Process one message at a time so we don't overload the worker.
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=on_message,
        auto_ack=False,   # manual ack for reliability
    )

    log.info("[AI Worker] Waiting for messages on '%s'. CTRL+C to exit.", QUEUE_NAME)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        log.info("[AI Worker] Shutting down…")
        channel.stop_consuming()
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    main()
