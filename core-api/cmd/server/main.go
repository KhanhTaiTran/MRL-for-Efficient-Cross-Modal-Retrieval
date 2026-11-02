package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"core-api/internal/admin"
	"core-api/internal/api"
	"core-api/internal/auth"
	"core-api/internal/broker"
	"core-api/internal/catalog"
	"core-api/internal/commerce"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

func main() {
	var db *pgxpool.Pool
	if databaseURL := os.Getenv("DATABASE_URL"); databaseURL != "" {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		var err error
		db, err = pgxpool.New(ctx, databaseURL)
		if err == nil {
			err = db.Ping(ctx)
		}
		cancel()
		if err != nil {
			log.Fatal("Database unavailable: ", err)
		}
		defer db.Close()
	}

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
	origins := strings.Split(os.Getenv("CORS_ORIGINS"), ",")
	if len(origins) == 1 && origins[0] == "" {
		origins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}
	}
	r := gin.Default()
	r.SetTrustedProxies(nil)
	r.Use(cors.New(cors.Config{
		AllowOrigins:     origins,
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization", "Idempotency-Key"},
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

	r.GET("/health/live", func(c *gin.Context) { c.JSON(200, gin.H{"status": "ok"}) })
	r.GET("/health/ready", func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		defer cancel()
		if db != nil {
			if err := db.Ping(ctx); err != nil {
				c.JSON(503, gin.H{"status": "not_ready", "dependency": "database"})
				return
			}
		}
		health, err := inferClient.Health(ctx)
		if err != nil || health["model_loaded"] != true || health["index_loaded"] != true {
			c.JSON(503, gin.H{"status": "not_ready", "dependency": "inference"})
			return
		}
		c.JSON(200, gin.H{"status": "ok", "database_configured": db != nil})
	})

	// Register API Routes
	apiGroup := r.Group("/api")
	searchHandler := api.NewSearchHandler(inferClient)
	if db != nil {
		mediaBase := os.Getenv("PUBLIC_MEDIA_BASE_URL")
		if mediaBase == "" {
			mediaBase = "http://localhost:9000/products"
		}
		repo := &catalog.Repository{DB: db, MediaBase: mediaBase}
		api.NewProductHandler(repo).RegisterRoutes(apiGroup)
		searchHandler.WithCatalog(repo)
		value := func(key, fallback string) string {
			if v := os.Getenv(key); v != "" {
				return v
			}
			return fallback
		}
		authHandler, err := api.NewAuthHandler(db, os.Getenv("JWT_SECRET"), os.Getenv("COOKIE_SECURE") == "true", origins, auth.Mailer{
			Host: value("SMTP_HOST", "localhost"), Port: value("SMTP_PORT", "1025"), From: value("SMTP_FROM", "AuraFind <noreply@aurafind.local>"), Username: os.Getenv("SMTP_USERNAME"), Password: os.Getenv("SMTP_PASSWORD"),
		})
		if err != nil {
			log.Fatal(err)
		}
		authHandler.RegisterRoutes(apiGroup)
		var store *minio.Client
		if endpoint := os.Getenv("MINIO_ENDPOINT"); endpoint != "" {
			store, err = minio.New(endpoint, &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ACCESS_KEY"), os.Getenv("MINIO_SECRET_KEY"), ""), Secure: os.Getenv("MINIO_SECURE") == "true"})
			if err != nil {
				log.Fatal(err)
			}
		}
		api.NewAdminHandler(&admin.Repository{DB: db, MediaBase: mediaBase}, store).RegisterRoutes(apiGroup, authHandler)
		api.NewCommerceHandler(&commerce.Repository{DB: db, MediaBase: mediaBase}).RegisterRoutes(apiGroup, authHandler)
	} else {
		apiGroup.Any("/products", func(c *gin.Context) { c.JSON(503, gin.H{"error": "Catalog requires DATABASE_URL"}) })
		apiGroup.Any("/products/*path", func(c *gin.Context) { c.JSON(503, gin.H{"error": "Catalog requires DATABASE_URL"}) })
		apiGroup.Any("/auth/*path", func(c *gin.Context) { c.JSON(503, gin.H{"error": "Accounts require DATABASE_URL"}) })
		apiGroup.Any("/admin/*path", func(c *gin.Context) { c.JSON(503, gin.H{"error": "Administration requires DATABASE_URL"}) })
		for _, path := range []string{"/cart", "/cart/*path", "/checkout", "/orders", "/orders/*path"} {
			apiGroup.Any(path, func(c *gin.Context) {
				c.JSON(503, gin.H{"error": "Shopping requires DATABASE_URL", "code": "service_unavailable"})
			})
		}
	}
	searchHandler.RegisterRoutes(apiGroup)

	log.Printf("[*] Core API server running on :%s (Infer API: %s)", port, inferAPIURL)
	server := &http.Server{Addr: ":" + port, Handler: r, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 35 * time.Second, IdleTimeout: 60 * time.Second}
	if err := server.ListenAndServe(); err != nil {
		log.Fatalf("Server startup failed: %v", err)
	}
}
