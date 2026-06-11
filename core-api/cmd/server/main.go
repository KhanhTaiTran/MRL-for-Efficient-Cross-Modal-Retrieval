package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	amqp "github.com/rabbitmq/amqp091-go"
)

// ─── Domain Types ─────────────────────────────────────────────────────────────

// UploadRequest is the JSON body the client sends to POST /api/upload-image.
type UploadRequest struct {
	// Base64-encoded image string (in a real service, use multipart/form-data).
	ImageBase64 string `json:"image_base64" binding:"required"`
	// MRL truncation dimension (e.g. 64, 128, 256, 512, 768).
	MRLDimension int `json:"mrl_dimension" binding:"required,min=1"`
}

// SearchTask is the message published to the RabbitMQ queue.
type SearchTask struct {
	TaskID       string    `json:"task_id"`
	ImageBase64  string    `json:"image_base64"`
	MRLDimension int       `json:"mrl_dimension"`
	EnqueuedAt   time.Time `json:"enqueued_at"`
}

// ─── RabbitMQ Publisher ───────────────────────────────────────────────────────

type Publisher struct {
	conn    *amqp.Connection
	channel *amqp.Channel
	queue   string
}

func NewPublisher(url, queueName string) (*Publisher, error) {
	conn, err := amqp.Dial(url)
	if err != nil {
		return nil, err
	}

	ch, err := conn.Channel()
	if err != nil {
		conn.Close()
		return nil, err
	}

	// Declare the queue — idempotent, safe to call multiple times.
	_, err = ch.QueueDeclare(
		queueName,
		true,  // durable  — survives broker restart
		false, // auto-delete
		false, // exclusive
		false, // no-wait
		nil,
	)
	if err != nil {
		ch.Close()
		conn.Close()
		return nil, err
	}

	return &Publisher{conn: conn, channel: ch, queue: queueName}, nil
}

func (p *Publisher) Publish(ctx context.Context, task SearchTask) error {
	body, err := json.Marshal(task)
	if err != nil {
		return err
	}

	return p.channel.PublishWithContext(ctx,
		"",      // default exchange
		p.queue, // routing key == queue name
		false,   // mandatory
		false,   // immediate
		amqp.Publishing{
			ContentType:  "application/json",
			DeliveryMode: amqp.Persistent, // survive broker restart
			Body:         body,
		},
	)
}

func (p *Publisher) Close() {
	p.channel.Close()
	p.conn.Close()
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

func mustEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func generateTaskID() string {
	return time.Now().Format("20060102150405.000000000")
}

// ─── Main ─────────────────────────────────────────────────────────────────────

func main() {
	rabbitURL := mustEnv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
	queueName := mustEnv("RABBITMQ_QUEUE", "image_search_queue")
	port := mustEnv("PORT", "8080")

	// Retry connecting to RabbitMQ — it may not be ready immediately.
	var pub *Publisher
	for attempts := 1; attempts <= 10; attempts++ {
		var err error
		pub, err = NewPublisher(rabbitURL, queueName)
		if err == nil {
			log.Printf("[core-api] Connected to RabbitMQ (attempt %d)", attempts)
			break
		}
		log.Printf("[core-api] RabbitMQ not ready (attempt %d/10): %v — retrying in 3s", attempts, err)
		time.Sleep(3 * time.Second)
	}
	if pub == nil {
		log.Fatal("[core-api] Could not connect to RabbitMQ after 10 attempts — exiting")
	}
	defer pub.Close()

	// ── Router ────────────────────────────────────────────────────────────────
	r := gin.Default()

	// Health probe (used by load-balancers / Docker health-checks)
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	// POST /api/upload-image
	// Accepts a JSON body with { "image_base64": "...", "mrl_dimension": 64 }
	// Publishes a SearchTask message to the image_search_queue.
	r.POST("/api/upload-image", func(c *gin.Context) {
		var req UploadRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{
				"error":   "invalid request body",
				"details": err.Error(),
			})
			return
		}

		task := SearchTask{
			TaskID:       generateTaskID(),
			ImageBase64:  req.ImageBase64,
			MRLDimension: req.MRLDimension,
			EnqueuedAt:   time.Now().UTC(),
		}

		ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
		defer cancel()

		if err := pub.Publish(ctx, task); err != nil {
			log.Printf("[core-api] Failed to publish task %s: %v", task.TaskID, err)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": "failed to enqueue image search task",
			})
			return
		}

		log.Printf("[core-api] Task %s enqueued → queue=%s dim=%d",
			task.TaskID, queueName, task.MRLDimension)

		c.JSON(http.StatusAccepted, gin.H{
			"message":       "Image search task accepted",
			"task_id":       task.TaskID,
			"mrl_dimension": task.MRLDimension,
			"queue":         queueName,
		})
	})

	log.Printf("[core-api] Listening on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("[core-api] Server error: %v", err)
	}
}
