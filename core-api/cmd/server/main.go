package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	amqp "github.com/rabbitmq/amqp091-go"
)

var supportedMRLDimensions = map[int]struct{}{
	8:   {},
	16:  {},
	32:  {},
	64:  {},
	128: {},
	256: {},
	512: {},
}

func failOnError(err error, msg string) {
	if err != nil {
		log.Panicf("%s: %s", msg, err)
	}
}

func main() {
	conn, err := amqp.Dial("amqp://guest:guest@localhost:5672/")
	failOnError(err, "Can't connect to RabbitMQ")
	defer conn.Close()

	ch, err := conn.Channel()
	failOnError(err, "Can't open channel")
	defer ch.Close()

	q, err := ch.QueueDeclare(
		"",
		false,
		false,
		true,
		false,
		nil,
	)
	failOnError(err, "Can't declare reply queue")

	msgs, err := ch.Consume(
		q.Name,
		"",
		true,
		false,
		false,
		false,
		nil,
	)
	failOnError(err, "Can't register consumer")

	// Router and CORS Config
	r := gin.Default()
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"http://localhost:3000"},
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	// Add middleware to ensure Vary: Origin is always set to prevent browser caching issues
	// where an <img> load caches the response without CORS headers, breaking subsequent fetch() calls.
	r.Use(func(c *gin.Context) {
		c.Header("Vary", "Origin")
		c.Next()
	})

	// static file server (using for display the images from other directory)
	r.Static("/images", "D:/Pre-thesis/Thesis Dataset-20260617T002927Z-3-002/Thesis Dataset/data_images")

	// Helper function for common RabbitMQ Publish & Wait logic
	publishAndWait := func(c *gin.Context, body []byte, contentType string, searchType string, mrlDimension int, requestStartedAt time.Time) {
		corrID := uuid.New().String()
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second) // Increased timeout for 22k search
		defer cancel()

		err = ch.PublishWithContext(ctx,
			"",
			"search_queue",
			false,
			false,
			amqp.Publishing{
				ContentType:   contentType,
				CorrelationId: corrID,
				ReplyTo:       q.Name,
				Headers: amqp.Table{
					"mrl_dimension": int32(mrlDimension),
					"search_type":   searchType,
				},
				Body: body,
			},
		)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Error publishing message to worker"})
			return
		}

		for d := range msgs {
			if d.CorrelationId != corrID {
				continue
			}

			var payload map[string]any
			if err := json.Unmarshal(d.Body, &payload); err != nil {
				c.Data(http.StatusOK, "application/json", d.Body)
				return
			}

			payload["mrl_dimension"] = mrlDimension
			payload["request_latency_ms"] = time.Since(requestStartedAt).Milliseconds()

			responseBody, err := json.Marshal(payload)
			if err != nil {
				c.Data(http.StatusOK, "application/json", d.Body)
				return
			}

			c.Data(http.StatusOK, "application/json", responseBody)
			return
		}

		c.JSON(http.StatusRequestTimeout, gin.H{"error": "Timed out waiting for search results from worker"})
	}

	// 1. Image-to-Image Search API
	r.POST("/api/search/image", func(c *gin.Context) {
		requestStartedAt := time.Now()

		file, _, err := c.Request.FormFile("image")
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Please upload an image with key 'image'"})
			return
		}
		defer file.Close()

		dimensionValue := c.Request.FormValue("mrl_dimension")
		mrlDimension, err := strconv.Atoi(dimensionValue)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Please provide a valid mrl_dimension"})
			return
		}
		if _, ok := supportedMRLDimensions[mrlDimension]; !ok {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Unsupported mrl_dimension. Use 8, 16, 32, 64, 128, 256, or 512."})
			return
		}

		imageBytes, err := io.ReadAll(file)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Cannot read image file"})
			return
		}

		publishAndWait(c, imageBytes, "image/jpeg", "image", mrlDimension, requestStartedAt)
	})

	// 2. Text-to-Image Search API
	r.POST("/api/search/text", func(c *gin.Context) {
		requestStartedAt := time.Now()

		query := c.Request.FormValue("query")
		if query == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Please provide a search text with key 'query'"})
			return
		}

		dimensionValue := c.Request.FormValue("mrl_dimension")
		mrlDimension, err := strconv.Atoi(dimensionValue)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Please provide a valid mrl_dimension"})
			return
		}
		if _, ok := supportedMRLDimensions[mrlDimension]; !ok {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Unsupported mrl_dimension. Use 8, 16, 32, 64, 128, 256, or 512."})
			return
		}

		textBytes := []byte(query)
		publishAndWait(c, textBytes, "text/plain", "text", mrlDimension, requestStartedAt)
	})

	log.Println("Core API is running at http://localhost:8080")
	if err := r.Run(":8080"); err != nil {
		log.Fatal(err)
	}
}
