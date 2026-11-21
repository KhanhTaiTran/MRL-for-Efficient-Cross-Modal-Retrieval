package api

import (
	"bytes"
	"context"
	"errors"
	"image"
	_ "image/jpeg"
	"image/png"
	"io"
	"log"
	"net/http"
	"strconv"
	"time"

	"core-api/internal/admin"
	"core-api/internal/commerce"
	"github.com/gin-gonic/gin"
	"github.com/minio/minio-go/v7"
)

type AdminHandler struct {
	repo  *admin.Repository
	store *minio.Client
}

func NewAdminHandler(repo *admin.Repository, store *minio.Client) *AdminHandler {
	return &AdminHandler{repo, store}
}
func (h *AdminHandler) RegisterRoutes(r *gin.RouterGroup, auth *AuthHandler) {
	group := r.Group("/admin")
	group.Use(auth.originGuard, auth.RequireUser(), requireAdmin)
	group.Use(func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 25*time.Second)
		defer cancel()
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	})
	group.GET("/products", h.List)
	group.POST("/products", h.Create)
	group.GET("/products/:id", h.Get)
	group.PUT("/products/:id", h.Update)
	group.DELETE("/products/:id", h.Archive)
	group.POST("/products/:id/variants", h.SaveVariant)
	group.PUT("/products/:id/variants/:variant", h.SaveVariant)
	group.DELETE("/products/:id/variants/:variant", h.DisableVariant)
	group.POST("/products/:id/images", h.Upload)
	group.PUT("/products/:id/images/:image", h.EditImage)
	group.DELETE("/products/:id/images/:image", h.RetireImage)
	group.GET("/index/jobs", h.Jobs)
	group.POST("/index/jobs", h.Enqueue)
	group.GET("/index/versions", h.Versions)
}
func requireAdmin(c *gin.Context) {
	if c.MustGet("user").(User).Role != "admin" {
		c.AbortWithStatusJSON(403, gin.H{"error": "Administrator access is required.", "code": "admin_required"})
		return
	}
	c.Next()
}
func (h *AdminHandler) fail(c *gin.Context, err error) {
	var e *commerce.Error
	if errors.As(err, &e) {
		c.JSON(e.Status, gin.H{"error": e.Message, "code": e.Code})
		return
	}
	log.Printf("admin operation failed: %v", err)
	c.JSON(503, gin.H{"error": "Administration service is temporarily unavailable.", "code": "service_unavailable"})
}
func (h *AdminHandler) List(c *gin.Context) {
	page, err := strconv.Atoi(c.DefaultQuery("page", "1"))
	if err != nil || page < 1 || page > 100000 {
		c.JSON(400, gin.H{"error": "Invalid page."})
		return
	}
	limit, err := strconv.Atoi(c.DefaultQuery("limit", "12"))
	if err != nil || limit < 1 || limit > 100 || len(c.Query("q")) > 200 {
		c.JSON(400, gin.H{"error": "Invalid limit or query."})
		return
	}
	data, total, err := h.repo.List(c.Request.Context(), page, limit, c.Query("q"))
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": data, "pagination": gin.H{"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) / limit}})
}
func (h *AdminHandler) Get(c *gin.Context) {
	data, err := h.repo.Get(c.Request.Context(), c.Param("id"))
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": data})
}
func (h *AdminHandler) Create(c *gin.Context) {
	var in admin.ProductInput
	if !readCommerce(c, &in) {
		return
	}
	id, err := h.repo.Create(c.Request.Context(), in)
	if err != nil {
		h.fail(c, err)
		return
	}
	data, err := h.repo.Get(c.Request.Context(), id)
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(201, gin.H{"data": data})
}
func (h *AdminHandler) Update(c *gin.Context) {
	var in admin.ProductInput
	if !readCommerce(c, &in) {
		return
	}
	if err := h.repo.Update(c.Request.Context(), c.Param("id"), in); err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func (h *AdminHandler) Archive(c *gin.Context) {
	if err := h.repo.Archive(c.Request.Context(), c.Param("id")); err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func (h *AdminHandler) SaveVariant(c *gin.Context) {
	var in admin.VariantInput
	if !readCommerce(c, &in) {
		return
	}
	_, err := h.repo.SaveVariant(c.Request.Context(), c.Param("id"), c.Param("variant"), in)
	if err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func (h *AdminHandler) DisableVariant(c *gin.Context) {
	if err := h.repo.DisableVariant(c.Request.Context(), c.Param("id"), c.Param("variant")); err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func normalizeProductImage(data []byte) ([]byte, error) {
	config, _, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil || config.Width < 1 || config.Height < 1 || config.Width > 8000 || config.Height > 8000 || int64(config.Width)*int64(config.Height) > 20000000 {
		return nil, errors.New("Use a JPEG or PNG image with at most 20 million pixels and 8000 pixels per side.")
	}
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, errors.New("Invalid JPEG or PNG image.")
	}
	var out bytes.Buffer
	if err = png.Encode(&out, img); err != nil {
		return nil, err
	}
	if out.Len() > 10*1024*1024 {
		return nil, errors.New("Normalized image exceeds 10 MB.")
	}
	return out.Bytes(), nil
}
func (h *AdminHandler) Upload(c *gin.Context) {
	if h.store == nil {
		c.JSON(503, gin.H{"error": "Product storage is not configured."})
		return
	}
	if _, err := h.repo.Get(c.Request.Context(), c.Param("id")); err != nil {
		h.fail(c, err)
		return
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 11*1024*1024)
	file, _, err := c.Request.FormFile("image")
	if c.Request.MultipartForm != nil {
		defer c.Request.MultipartForm.RemoveAll()
	}
	if err != nil {
		c.JSON(400, gin.H{"error": "Upload a JPEG or PNG image up to 10 MB."})
		return
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, 10*1024*1024+1))
	if err != nil || len(data) > 10*1024*1024 {
		c.JSON(400, gin.H{"error": "Image exceeds 10 MB."})
		return
	}
	normalized, err := normalizeProductImage(data)
	if err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	alt := c.Request.FormValue("alt")
	if len(alt) > 200 {
		c.JSON(400, gin.H{"error": "Image description is too long."})
		return
	}
	var id string
	if err = h.repo.DB.QueryRow(c.Request.Context(), "SELECT gen_random_uuid()::text").Scan(&id); err != nil {
		h.fail(c, err)
		return
	}
	key := "catalog/" + c.Param("id") + "/" + id + ".png"
	if _, err = h.store.PutObject(c.Request.Context(), "products", key, bytes.NewReader(normalized), int64(len(normalized)), minio.PutObjectOptions{ContentType: "image/png"}); err != nil {
		h.fail(c, err)
		return
	}
	if err = h.repo.AddImage(c.Request.Context(), c.Param("id"), id, key, admin.ImageInput{Alt: alt, Primary: c.Request.FormValue("primary") == "true"}); err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func (h *AdminHandler) EditImage(c *gin.Context) {
	var in admin.ImageInput
	if !readCommerce(c, &in) {
		return
	}
	if err := h.repo.EditImage(c.Request.Context(), c.Param("id"), c.Param("image"), in, false); err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func (h *AdminHandler) RetireImage(c *gin.Context) {
	if err := h.repo.EditImage(c.Request.Context(), c.Param("id"), c.Param("image"), admin.ImageInput{}, true); err != nil {
		h.fail(c, err)
		return
	}
	h.Get(c)
}
func (h *AdminHandler) Jobs(c *gin.Context) {
	data, err := h.repo.Jobs(c.Request.Context())
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": data})
}
func (h *AdminHandler) Enqueue(c *gin.Context) {
	data, err := h.repo.Enqueue(c.Request.Context(), commerceUser(c))
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(202, gin.H{"data": data})
}
func (h *AdminHandler) Versions(c *gin.Context) {
	data, err := h.repo.Versions(c.Request.Context())
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": data})
}
