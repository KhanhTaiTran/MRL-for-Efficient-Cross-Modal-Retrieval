package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"strconv"
	"time"

	"core-api/internal/commerce"
	"github.com/gin-gonic/gin"
)

type CommerceHandler struct{ repo *commerce.Repository }

func NewCommerceHandler(repo *commerce.Repository) *CommerceHandler { return &CommerceHandler{repo} }
func (h *CommerceHandler) RegisterRoutes(r *gin.RouterGroup, auth *AuthHandler) {
	group := r.Group("")
	group.Use(auth.originGuard, auth.RequireUser())
	group.Use(func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Second)
		defer cancel()
		c.Request = c.Request.WithContext(ctx)
		c.Header("Cache-Control", "no-store")
		c.Next()
	})
	group.GET("/cart", h.Cart)
	group.PUT("/cart/items/:variant_id", h.SetItem)
	group.DELETE("/cart/items/:variant_id", h.RemoveItem)
	group.POST("/checkout", h.Checkout)
	group.GET("/orders", h.Orders)
	group.GET("/orders/:id", h.Order)
}
func (h *CommerceHandler) fail(c *gin.Context, err error) {
	var e *commerce.Error
	if errors.As(err, &e) {
		c.JSON(e.Status, gin.H{"error": e.Message, "code": e.Code})
		return
	}
	log.Printf("commerce operation failed: %v", err)
	c.JSON(503, gin.H{"error": "Shopping service is temporarily unavailable. Please try again.", "code": "service_unavailable"})
}
func readCommerce(c *gin.Context, out any) bool {
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 64*1024)
	decoder := json.NewDecoder(c.Request.Body)
	decoder.DisallowUnknownFields()
	if c.ContentType() != "application/json" || decoder.Decode(out) != nil || decoder.Decode(&struct{}{}) != io.EOF {
		c.JSON(400, gin.H{"error": "A valid JSON request is required.", "code": "invalid_request"})
		return false
	}
	return true
}
func commerceUser(c *gin.Context) string { return c.MustGet("user").(User).ID }
func (h *CommerceHandler) Cart(c *gin.Context) {
	cart, err := h.repo.Cart(c.Request.Context(), commerceUser(c))
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": cart})
}
func (h *CommerceHandler) SetItem(c *gin.Context) {
	var input struct {
		Quantity int `json:"quantity"`
	}
	if !readCommerce(c, &input) {
		return
	}
	if err := h.repo.SetItem(c.Request.Context(), commerceUser(c), c.Param("variant_id"), input.Quantity); err != nil {
		h.fail(c, err)
		return
	}
	h.Cart(c)
}
func (h *CommerceHandler) RemoveItem(c *gin.Context) {
	if err := h.repo.RemoveItem(c.Request.Context(), commerceUser(c), c.Param("variant_id")); err != nil {
		h.fail(c, err)
		return
	}
	h.Cart(c)
}
func (h *CommerceHandler) Checkout(c *gin.Context) {
	var input commerce.CheckoutInput
	if !readCommerce(c, &input) {
		return
	}
	order, replayed, err := h.repo.Checkout(c.Request.Context(), commerceUser(c), c.GetHeader("Idempotency-Key"), input)
	if err != nil {
		h.fail(c, err)
		return
	}
	status := 201
	if replayed {
		status = 200
	}
	c.JSON(status, gin.H{"data": order, "replayed": replayed})
}
func (h *CommerceHandler) Orders(c *gin.Context) {
	page, err := strconv.Atoi(c.DefaultQuery("page", "1"))
	if err != nil || page < 1 || page > 100000 {
		c.JSON(400, gin.H{"error": "Invalid page.", "code": "invalid_page"})
		return
	}
	limit, err := strconv.Atoi(c.DefaultQuery("limit", "12"))
	if err != nil || limit < 1 || limit > 100 {
		c.JSON(400, gin.H{"error": "Limit must be between 1 and 100.", "code": "invalid_limit"})
		return
	}
	orders, total, err := h.repo.Orders(c.Request.Context(), commerceUser(c), page, limit)
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": orders, "pagination": gin.H{"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) / limit}})
}
func (h *CommerceHandler) Order(c *gin.Context) {
	order, err := h.repo.Order(c.Request.Context(), commerceUser(c), c.Param("id"))
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": order})
}
