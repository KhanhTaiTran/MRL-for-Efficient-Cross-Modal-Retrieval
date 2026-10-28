package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"core-api/internal/api"
	"core-api/internal/broker"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func main() {
	inferAPIURL := os.Getenv("INFER_API_URL")
	if inferAPIURL == "" {
		inferAPIURL = "http://localhost:8001"
	}

	inferTimeoutStr := os.Getenv("INFER_TIMEOUT")
	inferTimeout := 15 * time.Second
	if inferTimeoutStr != "" {
		if d, err := time.ParseDuration(inferTimeoutStr); err == nil {
			inferTimeout = d
		}
	}

	imgBaseDir := os.Getenv("IMG_BASE_DIR")
	if imgBaseDir == "" {
		imgBaseDir = "./data/sample_images"
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Initialize HTTP client to Python inference service
	inferClient := broker.NewInferClient(inferAPIURL, inferTimeout)

	// Router and CORS Configuration
	r := gin.Default()
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"http://localhost:3000"},
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	// Ensure Vary: Origin header
	r.Use(func(c *gin.Context) {
		c.Header("Vary", "Origin")
		c.Next()
	})

	// Static images server
	r.Static("/images", imgBaseDir)

	// Health check
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":  "ok",
			"service": "core-api",
		})
	})

	// Register API Routes
	apiGroup := r.Group("/api")
	searchHandler := api.NewSearchHandler(inferClient)
	searchHandler.RegisterRoutes(apiGroup)

	log.Printf("[*] Core API server running on :%s (Infer API: %s)", port, inferAPIURL)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server startup failed: %v", err)
	}
}
