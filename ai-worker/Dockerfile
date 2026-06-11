# ── Base image ───────────────────────────────────────────────────────────────
FROM python:3.10-slim

# Keeps Python from buffering stdout/stderr so logs appear in real-time
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install OS-level deps (gcc needed for some pika / torch wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cache pip layer separately from application code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create a non-root user
RUN useradd -m -u 1001 appuser
USER appuser

CMD ["python", "main.py"]
