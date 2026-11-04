package api

import (
	"context"
	"errors"
	"log"
	"strconv"
	"strings"
	"time"

	"core-api/internal/catalog"
	"core-api/internal/commerce"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type EngagementHandler struct {
	db    *pgxpool.Pool
	media *catalog.Repository
}

func NewEngagementHandler(db *pgxpool.Pool, media string) *EngagementHandler {
	return &EngagementHandler{db, &catalog.Repository{MediaBase: media}}
}
func (h *EngagementHandler) RegisterRoutes(r *gin.RouterGroup, auth *AuthHandler) {
	bounded := func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Second)
		defer cancel()
		c.Request = c.Request.WithContext(ctx)
		c.Next()
	}
	public := r.Group("")
	public.Use(bounded)
	public.GET("/products/:handle/reviews", h.PublicReviews)
	member := r.Group("")
	member.Use(auth.originGuard, auth.RequireUser(), bounded)
	member.GET("/products/:handle/review-eligibility", h.Eligibility)
	member.PUT("/products/:handle/review", h.SaveReview)
	member.GET("/wishlist", h.Wishlist)
	member.PUT("/wishlist/:id", h.SaveWishlist)
	member.DELETE("/wishlist/:id", h.RemoveWishlist)
	admin := r.Group("/admin")
	admin.Use(auth.originGuard, auth.RequireUser(), requireAdmin, bounded)
	admin.GET("/reviews", h.AdminReviews)
	admin.PATCH("/reviews/:id", h.Moderate)
}

type Review struct {
	ID          string    `json:"id"`
	ProductID   string    `json:"product_id"`
	ProductName string    `json:"product_name,omitempty"`
	Author      string    `json:"author"`
	Rating      int       `json:"rating"`
	Comment     string    `json:"comment"`
	Verified    bool      `json:"is_verified_purchase"`
	Hidden      bool      `json:"is_hidden"`
	CreatedAt   time.Time `json:"created_at"`
}

const reviewFields = `r.id::text,r.product_id::text,p.name,split_part(u.name,' ',1),r.rating,COALESCE(r.comment,''),r.is_verified_purchase,r.is_hidden,r.created_at`

func scanReview(row pgx.Row) (Review, error) {
	var v Review
	err := row.Scan(&v.ID, &v.ProductID, &v.ProductName, &v.Author, &v.Rating, &v.Comment, &v.Verified, &v.Hidden, &v.CreatedAt)
	return v, err
}
func (h *EngagementHandler) fail(c *gin.Context, err error) {
	log.Printf("engagement failed: %v", err)
	c.JSON(503, gin.H{"error": "Reviews and saved items are temporarily unavailable.", "code": "service_unavailable"})
}
func pageParams(c *gin.Context) (int, int, bool) {
	page, e := strconv.Atoi(c.DefaultQuery("page", "1"))
	limit, l := strconv.Atoi(c.DefaultQuery("limit", "12"))
	if e != nil || l != nil || page < 1 || page > 100000 || limit < 1 || limit > 100 {
		c.JSON(400, gin.H{"error": "Invalid pagination.", "code": "invalid_pagination"})
		return 0, 0, false
	}
	return page, limit, true
}
func (h *EngagementHandler) product(c *gin.Context) (string, bool) {
	var id string
	err := h.db.QueryRow(c.Request.Context(), "SELECT id::text FROM products WHERE handle=$1 AND is_active", c.Param("handle")).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		c.JSON(404, gin.H{"error": "Product not found."})
		return "", false
	}
	if err != nil {
		h.fail(c, err)
		return "", false
	}
	return id, true
}
func (h *EngagementHandler) reviews(c *gin.Context, pid string, admin bool) {
	page, limit, ok := pageParams(c)
	if !ok {
		return
	}
	ctx := c.Request.Context()
	var total int
	where := " WHERE ($1='' OR r.product_id::text=$1) AND ($2 OR (NOT r.is_hidden AND p.is_active))"
	joins := " FROM reviews r JOIN products p ON p.id=r.product_id JOIN users u ON u.id=r.user_id"
	if err := h.db.QueryRow(ctx, "SELECT count(*)"+joins+where, pid, admin).Scan(&total); err != nil {
		h.fail(c, err)
		return
	}
	rows, err := h.db.Query(ctx, "SELECT "+reviewFields+joins+where+" ORDER BY r.created_at DESC,r.id LIMIT $3 OFFSET $4", pid, admin, limit, (page-1)*limit)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer rows.Close()
	out := []Review{}
	for rows.Next() {
		v, err := scanReview(rows)
		if err != nil {
			h.fail(c, err)
			return
		}
		out = append(out, v)
	}
	if err = rows.Err(); err != nil {
		h.fail(c, err)
		return
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(200, gin.H{"data": out, "pagination": gin.H{"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) / limit}})
}
func (h *EngagementHandler) PublicReviews(c *gin.Context) {
	id, ok := h.product(c)
	if ok {
		h.reviews(c, id, false)
	}
}
func (h *EngagementHandler) AdminReviews(c *gin.Context) { h.reviews(c, "", true) }

const purchaseSQL = `SELECT o.id::text FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.user_id=$1 AND i.product_id=$2 AND o.order_status='confirmed' AND o.payment_status='paid' ORDER BY o.created_at,o.id LIMIT 1`

func (h *EngagementHandler) Eligibility(c *gin.Context) {
	pid, ok := h.product(c)
	if !ok {
		return
	}
	ctx := c.Request.Context()
	user := commerceUser(c)
	var order string
	err := h.db.QueryRow(ctx, purchaseSQL, user, pid).Scan(&order)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		h.fail(c, err)
		return
	}
	eligible := err == nil
	review, err := scanReview(h.db.QueryRow(ctx, "SELECT "+reviewFields+" FROM reviews r JOIN products p ON p.id=r.product_id JOIN users u ON u.id=r.user_id WHERE r.user_id=$1 AND r.product_id=$2", user, pid))
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		h.fail(c, err)
		return
	}
	var own any
	if err == nil {
		own = review
	}
	c.JSON(200, gin.H{"eligible": eligible, "review": own})
}
func (h *EngagementHandler) SaveReview(c *gin.Context) {
	var in struct {
		Rating  int    `json:"rating"`
		Comment string `json:"comment"`
	}
	if !readCommerce(c, &in) {
		return
	}
	in.Comment = strings.TrimSpace(in.Comment)
	if in.Rating < 1 || in.Rating > 5 || len(in.Comment) > 4000 {
		c.JSON(400, gin.H{"error": "Use a rating from 1 to 5 and a comment up to 4000 bytes.", "code": "invalid_review"})
		return
	}
	pid, ok := h.product(c)
	if !ok {
		return
	}
	ctx := c.Request.Context()
	tx, err := h.db.Begin(ctx)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer tx.Rollback(ctx)
	// Match commerce's user-first order and lock the purchased order through commit.
	var user string
	if err = tx.QueryRow(ctx, "SELECT id::text FROM users WHERE id=$1 FOR UPDATE", commerceUser(c)).Scan(&user); err != nil {
		h.fail(c, err)
		return
	}
	var order string
	err = tx.QueryRow(ctx, purchaseSQL+" FOR SHARE OF o", user, pid).Scan(&order)
	if errors.Is(err, pgx.ErrNoRows) {
		c.JSON(403, gin.H{"error": "A confirmed, paid purchase of this product is required.", "code": "purchase_required"})
		return
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	// Never clear is_hidden in an author update; moderation survives edits.
	_, err = tx.Exec(ctx, `INSERT INTO reviews(user_id,product_id,order_id,rating,comment,is_verified_purchase) VALUES($1,$2,$3,$4,$5,true) ON CONFLICT(user_id,product_id) DO UPDATE SET rating=EXCLUDED.rating,comment=EXCLUDED.comment`, user, pid, order, in.Rating, in.Comment)
	if err == nil {
		err = tx.Commit(ctx)
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	h.Eligibility(c)
}
func (h *EngagementHandler) Moderate(c *gin.Context) {
	if !commerce.ValidID(c.Param("id")) {
		c.JSON(404, gin.H{"error": "Review not found."})
		return
	}
	var in struct {
		Hidden *bool `json:"is_hidden"`
	}
	if !readCommerce(c, &in) {
		return
	}
	if in.Hidden == nil {
		c.JSON(400, gin.H{"error": "is_hidden is required."})
		return
	}
	tag, err := h.db.Exec(c.Request.Context(), "UPDATE reviews SET is_hidden=$2 WHERE id=$1", c.Param("id"), *in.Hidden)
	if err != nil {
		h.fail(c, err)
		return
	}
	if tag.RowsAffected() == 0 {
		c.JSON(404, gin.H{"error": "Review not found."})
		return
	}
	c.JSON(200, gin.H{"message": "Review visibility updated."})
}

type SavedProduct struct {
	ID       string `json:"id"`
	Handle   string `json:"handle"`
	Name     string `json:"name"`
	Price    int64  `json:"price_cents"`
	Currency string `json:"currency"`
	Image    string `json:"image_url"`
}

func (h *EngagementHandler) Wishlist(c *gin.Context) {
	page, limit, ok := pageParams(c)
	if !ok {
		return
	}
	ctx := c.Request.Context()
	user := commerceUser(c)
	var total int
	if err := h.db.QueryRow(ctx, "SELECT count(*) FROM wishlists w JOIN products p ON p.id=w.product_id WHERE w.user_id=$1 AND p.is_active", user).Scan(&total); err != nil {
		h.fail(c, err)
		return
	}
	rows, err := h.db.Query(ctx, `SELECT p.id::text,p.handle,p.name,(p.base_price*100)::bigint,p.currency,COALESCE((SELECT object_key FROM product_images WHERE product_id=p.id AND is_active ORDER BY is_primary DESC,position,id LIMIT 1),'') FROM wishlists w JOIN products p ON p.id=w.product_id WHERE w.user_id=$1 AND p.is_active ORDER BY w.created_at DESC,p.id LIMIT $2 OFFSET $3`, user, limit, (page-1)*limit)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer rows.Close()
	out := []SavedProduct{}
	for rows.Next() {
		var v SavedProduct
		var key string
		if err = rows.Scan(&v.ID, &v.Handle, &v.Name, &v.Price, &v.Currency, &key); err != nil {
			h.fail(c, err)
			return
		}
		v.Image = h.media.ImageURL(key)
		out = append(out, v)
	}
	if err = rows.Err(); err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"data": out, "pagination": gin.H{"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) / limit}})
}
func (h *EngagementHandler) SaveWishlist(c *gin.Context) {
	if !commerce.ValidID(c.Param("id")) {
		c.JSON(404, gin.H{"error": "Product not found."})
		return
	}
	tag, err := h.db.Exec(c.Request.Context(), "INSERT INTO wishlists(user_id,product_id) SELECT $1,id FROM products WHERE id=$2 AND is_active ON CONFLICT DO NOTHING", commerceUser(c), c.Param("id"))
	if err != nil {
		h.fail(c, err)
		return
	}
	if tag.RowsAffected() == 0 {
		var exists bool
		if err = h.db.QueryRow(c.Request.Context(), "SELECT EXISTS(SELECT 1 FROM products WHERE id=$1 AND is_active)", c.Param("id")).Scan(&exists); err != nil {
			h.fail(c, err)
			return
		}
		if !exists {
			c.JSON(404, gin.H{"error": "Product not found."})
			return
		}
	}
	c.JSON(200, gin.H{"message": "Product saved."})
}
func (h *EngagementHandler) RemoveWishlist(c *gin.Context) {
	if !commerce.ValidID(c.Param("id")) {
		c.JSON(404, gin.H{"error": "Product not found."})
		return
	}
	if _, err := h.db.Exec(c.Request.Context(), "DELETE FROM wishlists WHERE user_id=$1 AND product_id=$2", commerceUser(c), c.Param("id")); err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"message": "Product removed."})
}
