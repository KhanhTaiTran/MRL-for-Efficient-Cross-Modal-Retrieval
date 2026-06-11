# ── Stage 1: Build ───────────────────────────────────────────────────────────
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install git (needed by some Go modules)
RUN apk add --no-cache git

# Cache dependencies first
COPY go.mod go.sum* ./
RUN go mod download

# Copy source and build a statically-linked binary
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o server ./cmd/server

# ── Stage 2: Run ─────────────────────────────────────────────────────────────
FROM alpine:3.20

WORKDIR /app

# Create a non-root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

COPY --from=builder /app/server .

USER appuser

EXPOSE 8080

ENTRYPOINT ["./server"]
