FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
COPY ai-worker/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY ai-worker/ ./
COPY infra/ ./infra/
RUN useradd -m -u 1001 appuser && mkdir -p /data/vector_db /data/huggingface /data/images && chown -R appuser:appuser /data
USER appuser
EXPOSE 8001
CMD ["uvicorn", "ai_worker.api.server:app", "--host", "0.0.0.0", "--port", "8001"]
