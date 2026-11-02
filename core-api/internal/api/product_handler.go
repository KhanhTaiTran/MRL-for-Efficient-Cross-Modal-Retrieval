package api

import (
	"errors"
	"math"
	"net/http"
	"strconv"

	"core-api/internal/catalog"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
)

type ProductHandler struct{ repo *catalog.Repository }

func NewProductHandler(repo *catalog.Repository) *ProductHandler { return &ProductHandler{repo} }
func (h *ProductHandler) RegisterRoutes(r *gin.RouterGroup) {
	r.GET("/products", h.List)
	r.GET("/products/categories", h.Categories)
	r.GET("/products/:handle", h.Get)
}
func (h *ProductHandler) List(c *gin.Context) {
	page, err := strconv.Atoi(c.DefaultQuery("page", "1"))
	if err != nil || page < 1 || page > 100000 {
		c.JSON(400, gin.H{"error": "Invalid page"})
		return
	}
	limit, err := strconv.Atoi(c.DefaultQuery("limit", "12"))
	if err != nil || limit < 1 || limit > 100 {
		c.JSON(400, gin.H{"error": "Limit must be between 1 and 100"})
		return
	}
	f := catalog.Filter{Page: page, Limit: limit, Category: c.Query("category"), Q: c.Query("q"), Sort: c.DefaultQuery("sort", "newest")}
	if len(f.Q) > 200 || len(f.Category) > 100 {
		c.JSON(400, gin.H{"error": "Filter is too long"})
		return
	}
	if f.Sort != "newest" && f.Sort != "price_asc" && f.Sort != "price_desc" && f.Sort != "name" {
		c.JSON(400, gin.H{"error": "Unsupported sort"})
		return
	}
	if raw := c.Query("featured"); raw != "" {
		f.Featured, err = strconv.ParseBool(raw)
		if err != nil {
			c.JSON(400, gin.H{"error": "Invalid featured filter"})
			return
		}
	}
	for key, target := range map[string]**float64{"min_price": &f.Min, "max_price": &f.Max} {
		if raw := c.Query(key); raw != "" {
			value, err := strconv.ParseFloat(raw, 64)
			if err != nil || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
				c.JSON(400, gin.H{"error": "Invalid price filter"})
				return
			}
			*target = &value
		}
	}
	if f.Min != nil && f.Max != nil && *f.Min > *f.Max {
		c.JSON(400, gin.H{"error": "Minimum price exceeds maximum price"})
		return
	}
	items, total, err := h.repo.List(c.Request.Context(), f)
	if err != nil {
		c.JSON(503, gin.H{"error": "Catalog is temporarily unavailable"})
		return
	}
	c.JSON(200, gin.H{"data": items, "pagination": gin.H{"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) / limit}})
}
func (h *ProductHandler) Categories(c *gin.Context) {
	items, err := h.repo.Categories(c.Request.Context())
	if err != nil {
		c.JSON(503, gin.H{"error": "Catalog is temporarily unavailable"})
		return
	}
	c.JSON(200, gin.H{"data": items})
}
func (h *ProductHandler) Get(c *gin.Context) {
	item, err := h.repo.Get(c.Request.Context(), c.Param("handle"))
	if errors.Is(err, pgx.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error": "Product not found"})
		return
	}
	if err != nil {
		c.JSON(503, gin.H{"error": "Catalog is temporarily unavailable"})
		return
	}
	c.JSON(200, gin.H{"data": item})
}
