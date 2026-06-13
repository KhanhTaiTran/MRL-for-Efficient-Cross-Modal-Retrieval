package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
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

func failOnError(err error, msg string) {
	if err != nil {
		log.Panicf("%s: %s", msg, err)
	}
}

// ─── Main ─────────────────────────────────────────────────────────────────────

func main() {
	// Connect to RabbitMQ
	conn, err := amqp.Dial("amqp://guest:guest@localhost:5672/")
	failOnError(err, "Can't connect to RabbitMQ")
	defer conn.Close()

	ch, err := conn.Channel()
	failOnError(err, "Can't open channel")
	defer ch.Close()

	// declare a temporary reply queue for receiving results from Python
	q, err := ch.QueueDeclare(
		"",    // name (empty = auto-generate a unique name)
		false, // durable
		false, // delete when unused
		true,  // exclusive (only this connection can consume)
		false, // noWait
		nil,   // arguments
	)
	failOnError(err, "Can't declare reply queue")

	msgs, err := ch.Consume(
		q.Name, // queue
		"",     // consumer
		true,   // auto-ack
		false,  // exclusive
		false,  // no-local
		false,  // no-wait
		nil,    // args
	)
	failOnError(err, "Can't register consumer")

	// Set up Gin server with CORS
	r := gin.Default()

	// Allow CORS from frontend (adjust origin as needed)
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"http://localhost:3000"}, // allow frontend origin
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	r.POST("/api/search", func(c *gin.Context) {
		// Lấy file ảnh từ request
		file, _, err := c.Request.FormFile("image")
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Please upload an image with key 'image'"})
			return
		}
		defer file.Close()

		// img -> bytes
		imageBytes, err := io.ReadAll(file)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Cannot read image file"})
			return
		}

		// create a unique correlation ID for this request
		corrId := uuid.New().String()

		// Publish img + MRL dimension to RabbitMQ
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()

		err = ch.PublishWithContext(ctx,
			"",             // exchange
			"search_queue", // routing key (queue name)
			false,          // mandatory
			false,          // immediate
			amqp.Publishing{
				ContentType:   "image/jpeg",
				CorrelationId: corrId,
				ReplyTo:       q.Name, // Notify Python to send the result back to this queue
				Body:          imageBytes,
			})
		failOnError(err, "Error publishing message")

		// Wait for the result from Python
		for d := range msgs {
			if corrId == d.CorrelationId {
				// Receive the result matching the request ID
				c.Data(http.StatusOK, "application/json", d.Body)
				return
			}
		}

		c.JSON(http.StatusRequestTimeout, gin.H{"error": "Timed out waiting for search results"})
	})

	log.Println("Core API is running at http://localhost:8080")
	r.Run(":8080")
}
