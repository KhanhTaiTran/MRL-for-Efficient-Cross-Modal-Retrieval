package commerce

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"

	"core-api/internal/catalog"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const MaxTotalCents int64 = 999999999999
const MaxItems = 100

type Error struct {
	Status        int
	Code, Message string
}

func (e *Error) Error() string                       { return e.Message }
func problem(status int, code, message string) error { return &Error{status, code, message} }

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

func ValidID(id string) bool { return uuidPattern.MatchString(id) }

type Repository struct {
	DB        *pgxpool.Pool
	MediaBase string
}
type Item struct {
	VariantID  string `json:"variant_id"`
	ProductID  string `json:"product_id"`
	Handle     string `json:"handle"`
	Name       string `json:"name"`
	SKU        string `json:"sku"`
	Size       string `json:"size"`
	Color      string `json:"color"`
	ImageURL   string `json:"image_url"`
	ImageKey   string `json:"-"`
	PriceCents int64  `json:"price_cents"`
	Quantity   int    `json:"quantity"`
	Stock      int    `json:"stock"`
	Available  bool   `json:"is_available"`
	Currency   string `json:"currency"`
}
type Cart struct {
	Items         []Item `json:"items"`
	SubtotalCents int64  `json:"subtotal_cents"`
	ShippingCents int64  `json:"shipping_cents"`
	TotalCents    int64  `json:"total_cents"`
	Currency      string `json:"currency"`
	CanCheckout   bool   `json:"can_checkout"`
	LimitExceeded bool   `json:"limit_exceeded"`
}
type QuoteItem struct {
	VariantID  string `json:"variant_id"`
	Quantity   int    `json:"quantity"`
	PriceCents int64  `json:"price_cents"`
}
type Address struct {
	Name       string `json:"name"`
	Line1      string `json:"line1"`
	Line2      string `json:"line2"`
	City       string `json:"city"`
	Region     string `json:"region"`
	PostalCode string `json:"postal_code"`
	Country    string `json:"country"`
}
type CheckoutInput struct {
	ShippingAddress Address     `json:"shipping_address"`
	Items           []QuoteItem `json:"items"`
	Currency        string      `json:"currency"`
}
type OrderItem struct {
	ProductID  string `json:"product_id"`
	VariantID  string `json:"variant_id"`
	Name       string `json:"name"`
	SKU        string `json:"sku"`
	Size       string `json:"size"`
	Color      string `json:"color"`
	PriceCents int64  `json:"price_cents"`
	Quantity   int    `json:"quantity"`
	ImageURL   string `json:"image_url"`
}
type Order struct {
	ID                string      `json:"id"`
	OrderStatus       string      `json:"order_status"`
	PaymentStatus     string      `json:"payment_status"`
	PaymentMethod     string      `json:"payment_method"`
	FulfillmentStatus string      `json:"fulfillment_status"`
	SubtotalCents     int64       `json:"subtotal_cents"`
	ShippingCents     int64       `json:"shipping_cents"`
	TotalCents        int64       `json:"total_cents"`
	Currency          string      `json:"currency"`
	ShippingAddress   Address     `json:"shipping_address"`
	CreatedAt         time.Time   `json:"created_at"`
	Items             []OrderItem `json:"items,omitempty"`
}

func Canonicalize(in CheckoutInput, key string) (CheckoutInput, string, error) {
	if len(key) < 8 || len(key) > 128 || strings.IndexFunc(key, func(r rune) bool { return r > 126 || r < 33 }) >= 0 {
		return in, "", problem(400, "invalid_idempotency_key", "Use an Idempotency-Key of 8–128 printable characters.")
	}
	a := &in.ShippingAddress
	fields := []*string{&a.Name, &a.Line1, &a.Line2, &a.City, &a.Region, &a.PostalCode, &a.Country}
	for _, field := range fields {
		*field = strings.TrimSpace(*field)
		if len(*field) > 200 || strings.IndexFunc(*field, unicode.IsControl) >= 0 {
			return in, "", problem(400, "invalid_address", "Enter a valid shipping address.")
		}
	}
	a.Country = strings.ToUpper(a.Country)
	if a.Name == "" || a.Line1 == "" || a.City == "" || a.PostalCode == "" || !regexp.MustCompile(`^[A-Z]{2}$`).MatchString(a.Country) {
		return in, "", problem(400, "invalid_address", "Name, street, city, postal code and a two-letter country are required.")
	}
	if in.Currency != "USD" || len(in.Items) == 0 || len(in.Items) > MaxItems {
		return in, "", problem(400, "invalid_quote", "Provide a nonempty USD cart quote with at most 100 items.")
	}
	// Copy before sorting so callers retain their original request.
	in.Items = append([]QuoteItem(nil), in.Items...)
	for i := range in.Items {
		item := &in.Items[i]
		item.VariantID = strings.ToLower(item.VariantID)
		if !ValidID(item.VariantID) || item.Quantity < 1 || item.Quantity > 99 || item.PriceCents < 0 || item.PriceCents > MaxTotalCents {
			return in, "", problem(400, "invalid_quote", "Invalid variant, quantity or price in cart quote.")
		}
	}
	sort.Slice(in.Items, func(i, j int) bool { return in.Items[i].VariantID < in.Items[j].VariantID })
	for i := 1; i < len(in.Items); i++ {
		if in.Items[i-1].VariantID == in.Items[i].VariantID {
			return in, "", problem(400, "invalid_quote", "Quote contains duplicate variants.")
		}
	}
	data, err := json.Marshal(in)
	if err != nil {
		return in, "", err
	}
	sum := sha256.Sum256(data)
	return in, hex.EncodeToString(sum[:]), nil
}

type querier interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
	QueryRow(context.Context, string, ...any) pgx.Row
}

func (r *Repository) cart(ctx context.Context, q querier, user string, locked bool) (Cart, error) {
	suffix := " ORDER BY p.id,v.id"
	if locked {
		suffix += " FOR UPDATE OF p,v,c"
	}
	rows, err := q.Query(ctx, `SELECT v.id::text,p.id::text,p.handle,p.name,COALESCE(v.sku,''),v.size,v.color,
 COALESCE((SELECT object_key FROM product_images WHERE product_id=p.id ORDER BY is_primary DESC,position,id LIMIT 1),''),
 (v.price*100)::bigint,c.quantity,v.stock,(p.is_active AND v.is_available),p.currency
 FROM cart_items c JOIN product_variants v ON v.id=c.variant_id JOIN products p ON p.id=v.product_id WHERE c.user_id=$1`+suffix, user)
	if err != nil {
		return Cart{}, err
	}
	defer rows.Close()
	cart := Cart{Items: []Item{}, Currency: "USD", CanCheckout: true}
	media := catalog.Repository{MediaBase: r.MediaBase}
	for rows.Next() {
		var item Item
		if err := rows.Scan(&item.VariantID, &item.ProductID, &item.Handle, &item.Name, &item.SKU, &item.Size, &item.Color, &item.ImageKey, &item.PriceCents, &item.Quantity, &item.Stock, &item.Available, &item.Currency); err != nil {
			return Cart{}, err
		}
		item.ImageURL = media.ImageURL(item.ImageKey)
		if !item.Available || item.Stock < item.Quantity || item.Currency != "USD" {
			cart.CanCheckout = false
		}
		if item.PriceCents > math.MaxInt64/int64(item.Quantity) || cart.SubtotalCents > math.MaxInt64-item.PriceCents*int64(item.Quantity) {
			return Cart{}, problem(409, "total_limit", "Cart exceeds the supported order total.")
		}
		cart.SubtotalCents += item.PriceCents * int64(item.Quantity)
		cart.Items = append(cart.Items, item)
	}
	if err := rows.Err(); err != nil {
		return Cart{}, err
	}
	cart.TotalCents = cart.SubtotalCents
	cart.LimitExceeded = cart.TotalCents > MaxTotalCents
	if cart.LimitExceeded {
		cart.CanCheckout = false
	}
	if len(cart.Items) == 0 || len(cart.Items) > MaxItems {
		cart.CanCheckout = false
	}
	return cart, nil
}
func (r *Repository) Cart(ctx context.Context, user string) (Cart, error) {
	return r.cart(ctx, r.DB, user, false)
}
func lockUser(ctx context.Context, tx pgx.Tx, user string) error {
	var id string
	return tx.QueryRow(ctx, "SELECT id::text FROM users WHERE id=$1 FOR UPDATE", user).Scan(&id)
}
func (r *Repository) SetItem(ctx context.Context, user, variant string, quantity int) error {
	if !ValidID(variant) || quantity < 1 || quantity > 99 {
		return problem(400, "invalid_quantity", "Choose a valid variant and a quantity from 1 to 99.")
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = lockUser(ctx, tx, user); err != nil {
		return err
	}
	var available bool
	var stock int
	var currency string
	err = tx.QueryRow(ctx, `SELECT p.is_active AND v.is_available,v.stock,p.currency FROM product_variants v JOIN products p ON p.id=v.product_id WHERE v.id=$1`, variant).Scan(&available, &stock, &currency)
	if errors.Is(err, pgx.ErrNoRows) {
		return problem(404, "variant_not_found", "Variant not found.")
	}
	if err != nil {
		return err
	}
	if !available || stock < quantity || currency != "USD" {
		return problem(409, "unavailable", "This variant or quantity is unavailable.")
	}
	var count int
	var exists bool
	if err = tx.QueryRow(ctx, "SELECT count(*),COALESCE(bool_or(variant_id=$2::uuid),false) FROM cart_items WHERE user_id=$1", user, variant).Scan(&count, &exists); err != nil {
		return err
	}
	if count >= MaxItems && !exists {
		return problem(409, "cart_limit", "A cart can contain at most 100 variants.")
	}
	_, err = tx.Exec(ctx, `INSERT INTO cart_items(user_id,variant_id,quantity) VALUES($1,$2,$3) ON CONFLICT(user_id,variant_id) DO UPDATE SET quantity=EXCLUDED.quantity`, user, variant, quantity)
	if err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (r *Repository) RemoveItem(ctx context.Context, user, variant string) error {
	if !ValidID(variant) {
		return problem(400, "invalid_variant", "Invalid variant ID.")
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = lockUser(ctx, tx, user); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "DELETE FROM cart_items WHERE user_id=$1 AND variant_id=$2", user, variant); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (r *Repository) Checkout(ctx context.Context, user, key string, input CheckoutInput) (Order, bool, error) {
	in, hash, err := Canonicalize(input, key)
	if err != nil {
		return Order{}, false, err
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return Order{}, false, err
	}
	defer tx.Rollback(ctx)
	if err = lockUser(ctx, tx, user); err != nil {
		return Order{}, false, err
	}
	var existingID, existingHash string
	err = tx.QueryRow(ctx, "SELECT id::text,request_hash FROM orders WHERE user_id=$1 AND idempotency_key=$2", user, key).Scan(&existingID, &existingHash)
	if err == nil {
		if hash != existingHash {
			return Order{}, false, problem(409, "idempotency_conflict", "This checkout key was already used for a different request.")
		}
		order, err := r.order(ctx, tx, user, existingID)
		return order, true, err
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Order{}, false, err
	}
	cart, err := r.cart(ctx, tx, user, true)
	if err != nil {
		return Order{}, false, err
	}
	if len(cart.Items) != len(in.Items) {
		return Order{}, false, problem(409, "cart_changed", "Your cart changed. Review it before checking out.")
	}
	expected := map[string]QuoteItem{}
	for _, item := range in.Items {
		expected[item.VariantID] = item
	}
	for _, item := range cart.Items {
		quote, ok := expected[item.VariantID]
		if !ok || quote.Quantity != item.Quantity || quote.PriceCents != item.PriceCents {
			return Order{}, false, problem(409, "cart_changed", "Your cart or its prices changed. Review it before checking out.")
		}
	}
	if cart.LimitExceeded {
		return Order{}, false, problem(409, "total_limit", "Cart exceeds the supported order total. Remove items before checkout.")
	}
	if !cart.CanCheckout {
		return Order{}, false, problem(409, "unavailable", "Some items are unavailable. Review your cart.")
	}
	address, err := json.Marshal(in.ShippingAddress)
	if err != nil {
		return Order{}, false, err
	}
	var id string
	err = tx.QueryRow(ctx, `INSERT INTO orders(user_id,idempotency_key,request_hash,subtotal,shipping_fee,total,currency,shipping_address)
 VALUES($1,$2,$3,$4::bigint/100.0,0,$4::bigint/100.0,'USD',$5) RETURNING id::text`, user, key, hash, cart.TotalCents, address).Scan(&id)
	if err != nil {
		return Order{}, false, err
	}
	for _, item := range cart.Items {
		tag, err := tx.Exec(ctx, "UPDATE product_variants SET stock=stock-$2 WHERE id=$1 AND stock>=$2 AND is_available", item.VariantID, item.Quantity)
		if err != nil {
			return Order{}, false, err
		}
		if tag.RowsAffected() != 1 {
			return Order{}, false, problem(409, "unavailable", "Stock changed. Review your cart.")
		}
		_, err = tx.Exec(ctx, `INSERT INTO order_items(order_id,product_id,variant_id,name,sku,size,color,price,quantity,image_key)
  VALUES($1,$2,$3,$4,$5,$6,$7,$8::bigint/100.0,$9,$10)`, id, item.ProductID, item.VariantID, item.Name, item.SKU, item.Size, item.Color, item.PriceCents, item.Quantity, item.ImageKey)
		if err != nil {
			return Order{}, false, err
		}
	}
	if _, err = tx.Exec(ctx, "DELETE FROM cart_items WHERE user_id=$1", user); err != nil {
		return Order{}, false, err
	}
	order, err := r.order(ctx, tx, user, id)
	if err != nil {
		return Order{}, false, err
	}
	if err = tx.Commit(ctx); err != nil {
		return Order{}, false, err
	}
	return order, false, nil
}

const orderFields = `id::text,order_status,payment_status,payment_method,fulfillment_status,(subtotal*100)::bigint,(shipping_fee*100)::bigint,(total*100)::bigint,currency,shipping_address,created_at`

func scanOrder(row pgx.Row) (Order, error) {
	var o Order
	var address []byte
	err := row.Scan(&o.ID, &o.OrderStatus, &o.PaymentStatus, &o.PaymentMethod, &o.FulfillmentStatus, &o.SubtotalCents, &o.ShippingCents, &o.TotalCents, &o.Currency, &address, &o.CreatedAt)
	if err == nil {
		err = json.Unmarshal(address, &o.ShippingAddress)
	}
	return o, err
}
func (r *Repository) order(ctx context.Context, q querier, user, id string) (Order, error) {
	o, err := scanOrder(q.QueryRow(ctx, "SELECT "+orderFields+" FROM orders WHERE id=$1 AND user_id=$2", id, user))
	if errors.Is(err, pgx.ErrNoRows) {
		return o, problem(404, "order_not_found", "Order not found.")
	}
	if err != nil {
		return o, err
	}
	rows, err := q.Query(ctx, `SELECT COALESCE(product_id::text,''),COALESCE(variant_id::text,''),name,COALESCE(sku,''),COALESCE(size,''),COALESCE(color,''),(price*100)::bigint,quantity,COALESCE(image_key,'') FROM order_items WHERE order_id=$1 ORDER BY id`, id)
	if err != nil {
		return o, err
	}
	defer rows.Close()
	o.Items = []OrderItem{}
	media := catalog.Repository{MediaBase: r.MediaBase}
	for rows.Next() {
		var item OrderItem
		var key string
		if err = rows.Scan(&item.ProductID, &item.VariantID, &item.Name, &item.SKU, &item.Size, &item.Color, &item.PriceCents, &item.Quantity, &key); err != nil {
			return o, err
		}
		item.ImageURL = media.ImageURL(key)
		o.Items = append(o.Items, item)
	}
	return o, rows.Err()
}
func (r *Repository) Order(ctx context.Context, user, id string) (Order, error) {
	if !ValidID(id) {
		return Order{}, problem(404, "order_not_found", "Order not found.")
	}
	return r.order(ctx, r.DB, user, id)
}
func (r *Repository) Orders(ctx context.Context, user string, page, limit int) ([]Order, int, error) {
	var total int
	if err := r.DB.QueryRow(ctx, "SELECT count(*) FROM orders WHERE user_id=$1", user).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := r.DB.Query(ctx, "SELECT "+orderFields+" FROM orders WHERE user_id=$1 ORDER BY created_at DESC,id LIMIT $2 OFFSET $3", user, limit, (page-1)*limit)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	orders := []Order{}
	for rows.Next() {
		o, err := scanOrder(rows)
		if err != nil {
			return nil, 0, err
		}
		orders = append(orders, o)
	}
	return orders, total, rows.Err()
}
