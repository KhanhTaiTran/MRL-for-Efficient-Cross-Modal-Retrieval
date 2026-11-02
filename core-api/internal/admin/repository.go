package admin

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"time"

	"core-api/internal/catalog"
	"core-api/internal/commerce"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Repository struct {
	DB        *pgxpool.Pool
	MediaBase string
}

func invalid(code, message string) error {
	return &commerce.Error{Status: 400, Code: code, Message: message}
}
func missing() error {
	return &commerce.Error{Status: 404, Code: "not_found", Message: "Product or resource not found."}
}
func conflict(message string) error {
	return &commerce.Error{Status: 409, Code: "conflict", Message: message}
}
func dbError(err error) error {
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		if pg.Code == "23505" {
			return conflict("Handle, SKU or variant options already exist.")
		}
		if pg.Code == "23503" || pg.Code == "23514" {
			return invalid("invalid_reference", "Check product, default variant and field values.")
		}
	}
	return err
}

type ProductInput struct {
	Handle           string `json:"handle"`
	Name             string `json:"name"`
	Description      string `json:"description"`
	Brand            string `json:"brand"`
	Category         string `json:"category"`
	PriceCents       int64  `json:"price_cents"`
	Active           bool   `json:"is_active"`
	Featured         bool   `json:"is_featured"`
	Revision         int64  `json:"revision"`
	DefaultVariantID string `json:"default_variant_id"`
}
type Product struct {
	ID string `json:"id"`
	ProductInput
	Currency     string    `json:"currency"`
	SearchStatus string    `json:"search_status"`
	UpdatedAt    time.Time `json:"updated_at"`
	Variants     []Variant `json:"variants,omitempty"`
	Images       []Image   `json:"images,omitempty"`
}
type VariantInput struct {
	SKU           string `json:"sku"`
	Size          string `json:"size"`
	Color         string `json:"color"`
	PriceCents    int64  `json:"price_cents"`
	Stock         int    `json:"stock"`
	ExpectedStock *int   `json:"expected_stock,omitempty"`
	Available     bool   `json:"is_available"`
}
type Variant struct {
	ID string `json:"id"`
	VariantInput
}
type Image struct {
	ID       string `json:"id"`
	URL      string `json:"url"`
	Key      string `json:"object_key"`
	Alt      string `json:"alt"`
	Position int    `json:"position"`
	Primary  bool   `json:"is_primary"`
}
type ImageInput struct {
	Alt      string `json:"alt"`
	Position int    `json:"position"`
	Primary  bool   `json:"is_primary"`
}
type Job struct {
	ID         string     `json:"id"`
	Status     string     `json:"status"`
	Version    *string    `json:"index_version_id"`
	Error      *string    `json:"error"`
	CreatedAt  time.Time  `json:"created_at"`
	StartedAt  *time.Time `json:"started_at"`
	FinishedAt *time.Time `json:"finished_at"`
}
type Version struct {
	ID      string    `json:"id"`
	Tag     string    `json:"version_tag"`
	Vectors int       `json:"num_vectors"`
	Active  bool      `json:"is_active"`
	BuiltAt time.Time `json:"built_at"`
}

var slug = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

func normalize(in ProductInput) (ProductInput, error) {
	in.Handle = strings.TrimSpace(in.Handle)
	in.Name = strings.TrimSpace(in.Name)
	in.Brand = strings.TrimSpace(in.Brand)
	in.Category = strings.TrimSpace(in.Category)
	if !slug.MatchString(in.Handle) || len(in.Handle) > 120 || in.Name == "" || len(in.Name) > 200 || len(in.Description) > 5000 || len(in.Brand) > 120 || len(in.Category) > 100 || in.PriceCents < 0 || in.PriceCents > commerce.MaxTotalCents || in.Revision < 0 || (in.DefaultVariantID != "" && !commerce.ValidID(in.DefaultVariantID)) {
		return in, invalid("invalid_product", "Check the handle, name, price and field lengths.")
	}
	return in, nil
}

const productFields = `id::text,handle,name,COALESCE(description,''),COALESCE(brand,''),COALESCE(category,''),(base_price*100)::bigint,is_active,is_featured,search_revision,COALESCE(default_variant_id::text,''),currency,search_status,updated_at`

func scanProduct(row pgx.Row) (Product, error) {
	var p Product
	err := row.Scan(&p.ID, &p.Handle, &p.Name, &p.Description, &p.Brand, &p.Category, &p.PriceCents, &p.Active, &p.Featured, &p.Revision, &p.DefaultVariantID, &p.Currency, &p.SearchStatus, &p.UpdatedAt)
	return p, err
}
func (r *Repository) List(ctx context.Context, page, limit int, q string) ([]Product, int, error) {
	var total int
	if err := r.DB.QueryRow(ctx, "SELECT count(*) FROM products WHERE name ILIKE '%'||$1||'%' OR handle ILIKE '%'||$1||'%'", q).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := r.DB.Query(ctx, "SELECT "+productFields+" FROM products WHERE name ILIKE '%'||$1||'%' OR handle ILIKE '%'||$1||'%' ORDER BY updated_at DESC,id LIMIT $2 OFFSET $3", q, limit, (page-1)*limit)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	items := []Product{}
	for rows.Next() {
		p, err := scanProduct(rows)
		if err != nil {
			return nil, 0, err
		}
		items = append(items, p)
	}
	return items, total, rows.Err()
}
func (r *Repository) Get(ctx context.Context, id string) (Product, error) {
	if !commerce.ValidID(id) {
		return Product{}, missing()
	}
	p, err := scanProduct(r.DB.QueryRow(ctx, "SELECT "+productFields+" FROM products WHERE id=$1", id))
	if errors.Is(err, pgx.ErrNoRows) {
		return p, missing()
	}
	if err != nil {
		return p, err
	}
	rows, err := r.DB.Query(ctx, "SELECT id::text,COALESCE(sku,''),size,color,(price*100)::bigint,stock,is_available FROM product_variants WHERE product_id=$1 ORDER BY size,color,id", id)
	if err != nil {
		return p, err
	}
	p.Variants = []Variant{}
	for rows.Next() {
		var v Variant
		if err = rows.Scan(&v.ID, &v.SKU, &v.Size, &v.Color, &v.PriceCents, &v.Stock, &v.Available); err != nil {
			rows.Close()
			return p, err
		}
		p.Variants = append(p.Variants, v)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return p, err
	}
	rows, err = r.DB.Query(ctx, "SELECT id::text,object_key,COALESCE(alt_text,''),position,is_primary FROM product_images WHERE product_id=$1 AND is_active ORDER BY is_primary DESC,position,id", id)
	if err != nil {
		return p, err
	}
	defer rows.Close()
	p.Images = []Image{}
	media := catalog.Repository{MediaBase: r.MediaBase}
	for rows.Next() {
		var i Image
		if err = rows.Scan(&i.ID, &i.Key, &i.Alt, &i.Position, &i.Primary); err != nil {
			return p, err
		}
		i.URL = media.ImageURL(i.Key)
		p.Images = append(p.Images, i)
	}
	return p, rows.Err()
}
func (r *Repository) Create(ctx context.Context, in ProductInput) (string, error) {
	in, err := normalize(in)
	if err != nil {
		return "", err
	}
	if in.DefaultVariantID != "" {
		return "", invalid("invalid_variant", "Create variants after creating the product.")
	}
	var id string
	err = r.DB.QueryRow(ctx, `INSERT INTO products(handle,name,description,brand,category,base_price,is_active,is_featured) VALUES($1,$2,$3,$4,$5,$6::bigint/100.0,$7,$8) RETURNING id::text`, in.Handle, in.Name, in.Description, in.Brand, in.Category, in.PriceCents, in.Active, in.Featured).Scan(&id)
	return id, dbError(err)
}
func (r *Repository) Update(ctx context.Context, id string, in ProductInput) error {
	if !commerce.ValidID(id) {
		return missing()
	}
	in, err := normalize(in)
	if err != nil {
		return err
	}
	tag, err := r.DB.Exec(ctx, `UPDATE products SET handle=$2,name=$3,description=$4,brand=$5,category=$6,base_price=$7::bigint/100.0,is_active=$8,is_featured=$9,default_variant_id=NULLIF($10,'')::uuid,search_revision=search_revision+1,search_status='pending',updated_at=now() WHERE id=$1 AND search_revision=$11`, id, in.Handle, in.Name, in.Description, in.Brand, in.Category, in.PriceCents, in.Active, in.Featured, in.DefaultVariantID, in.Revision)
	if err != nil {
		return dbError(err)
	}
	if tag.RowsAffected() == 0 {
		if _, err := r.Get(ctx, id); err != nil {
			return err
		}
		return conflict("This product changed. Reload before saving.")
	}
	return nil
}
func (r *Repository) Archive(ctx context.Context, id string) error {
	if !commerce.ValidID(id) {
		return missing()
	}
	tag, err := r.DB.Exec(ctx, "UPDATE products SET is_active=false,search_status='pending',search_revision=search_revision+1,updated_at=now() WHERE id=$1", id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return missing()
	}
	return nil
}
func lockProduct(ctx context.Context, tx pgx.Tx, id string) error {
	if !commerce.ValidID(id) {
		return missing()
	}
	var value string
	err := tx.QueryRow(ctx, "SELECT id::text FROM products WHERE id=$1 FOR UPDATE", id).Scan(&value)
	if errors.Is(err, pgx.ErrNoRows) {
		return missing()
	}
	return err
}
func dirty(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "UPDATE products SET search_revision=search_revision+1,search_status='pending',updated_at=now() WHERE id=$1", id)
	return err
}
func (r *Repository) SaveVariant(ctx context.Context, pid, id string, in VariantInput) (string, error) {
	in.SKU = strings.TrimSpace(in.SKU)
	in.Size = strings.TrimSpace(in.Size)
	in.Color = strings.TrimSpace(in.Color)
	if len(in.SKU) > 120 || len(in.Size) > 100 || len(in.Color) > 100 || in.Stock < 0 || int64(in.Stock) > 2147483647 || in.PriceCents < 0 || in.PriceCents > commerce.MaxTotalCents || (id != "" && !commerce.ValidID(id)) {
		return "", invalid("invalid_variant", "Check variant price, stock and field lengths.")
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)
	if err = lockProduct(ctx, tx, pid); err != nil {
		return "", err
	}
	if id == "" {
		err = tx.QueryRow(ctx, "INSERT INTO product_variants(product_id,sku,size,color,price,stock,is_available) VALUES($1,NULLIF($2,''),$3,$4,$5::bigint/100.0,$6,$7) RETURNING id::text", pid, in.SKU, in.Size, in.Color, in.PriceCents, in.Stock, in.Available).Scan(&id)
	} else {
		var stock int
		if err = tx.QueryRow(ctx, "SELECT stock FROM product_variants WHERE id=$1 AND product_id=$2 FOR UPDATE", id, pid).Scan(&stock); errors.Is(err, pgx.ErrNoRows) {
			return "", missing()
		}
		if err != nil {
			return "", err
		}
		if in.ExpectedStock == nil || *in.ExpectedStock != stock {
			return "", conflict("Stock changed. Reload the variant before saving.")
		}
		tag, e := tx.Exec(ctx, "UPDATE product_variants SET sku=NULLIF($3,''),size=$4,color=$5,price=$6::bigint/100.0,stock=$7,is_available=$8 WHERE id=$1 AND product_id=$2", id, pid, in.SKU, in.Size, in.Color, in.PriceCents, in.Stock, in.Available)
		err = e
		if err == nil && tag.RowsAffected() == 0 {
			return "", missing()
		}
	}
	if err != nil {
		return "", dbError(err)
	}
	if _, err = tx.Exec(ctx, "UPDATE products SET default_variant_id=COALESCE(default_variant_id,$2::uuid) WHERE id=$1", pid, id); err != nil {
		return "", dbError(err)
	}
	if err = dirty(ctx, tx, pid); err != nil {
		return "", err
	}
	return id, dbError(tx.Commit(ctx))
}
func (r *Repository) DisableVariant(ctx context.Context, pid, id string) error {
	if !commerce.ValidID(id) {
		return missing()
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = lockProduct(ctx, tx, pid); err != nil {
		return err
	}
	tag, err := tx.Exec(ctx, "UPDATE product_variants SET is_available=false WHERE product_id=$1 AND id=$2", pid, id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return missing()
	}
	if err = dirty(ctx, tx, pid); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (r *Repository) AddImage(ctx context.Context, pid, id, key string, in ImageInput) error {
	if len(in.Alt) > 200 || in.Position < 0 || in.Position > 32767 {
		return invalid("invalid_image", "Check image description and position.")
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = lockProduct(ctx, tx, pid); err != nil {
		return err
	}
	var count int
	if err = tx.QueryRow(ctx, "SELECT count(*) FROM product_images WHERE product_id=$1 AND is_active", pid).Scan(&count); err != nil {
		return err
	}
	if count >= 20 {
		return conflict("A product can have at most 20 active images.")
	}
	if count == 0 {
		in.Primary = true
	}
	if in.Primary {
		if _, err = tx.Exec(ctx, "UPDATE product_images SET is_primary=false WHERE product_id=$1 AND is_active", pid); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(ctx, "INSERT INTO product_images(id,product_id,object_key,alt_text,position,is_primary) VALUES($1,$2,$3,$4,$5,$6)", id, pid, key, in.Alt, in.Position, in.Primary); err != nil {
		return dbError(err)
	}
	if err = dirty(ctx, tx, pid); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (r *Repository) EditImage(ctx context.Context, pid, id string, in ImageInput, retire bool) error {
	if !commerce.ValidID(id) {
		return missing()
	}
	if len(in.Alt) > 200 || in.Position < 0 || in.Position > 32767 {
		return invalid("invalid_image", "Check image description and position.")
	}
	tx, err := r.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = lockProduct(ctx, tx, pid); err != nil {
		return err
	}
	var primary bool
	if err = tx.QueryRow(ctx, "SELECT is_primary FROM product_images WHERE id=$1 AND product_id=$2 AND is_active", id, pid).Scan(&primary); errors.Is(err, pgx.ErrNoRows) {
		return missing()
	}
	if err != nil {
		return err
	}
	if !retire && !in.Primary && primary {
		return invalid("primary_required", "Choose another primary image before clearing this primary image.")
	}
	if in.Primary && !retire {
		if _, err = tx.Exec(ctx, "UPDATE product_images SET is_primary=false WHERE product_id=$1 AND is_active", pid); err != nil {
			return err
		}
	}
	if retire {
		_, err = tx.Exec(ctx, "UPDATE product_images SET is_active=false,is_primary=false WHERE id=$1", id)
	} else {
		_, err = tx.Exec(ctx, "UPDATE product_images SET alt_text=$2,position=$3,is_primary=$4 WHERE id=$1", id, in.Alt, in.Position, in.Primary)
	}
	if err != nil {
		return err
	}
	if retire && primary {
		if _, err = tx.Exec(ctx, "UPDATE product_images SET is_primary=true WHERE id=(SELECT id FROM product_images WHERE product_id=$1 AND is_active ORDER BY position,id LIMIT 1)", pid); err != nil {
			return err
		}
	}
	if err = dirty(ctx, tx, pid); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (r *Repository) Enqueue(ctx context.Context, user string) (Job, error) {
	var id string
	// A partial unique index makes concurrent clicks return the one open job.
	err := r.DB.QueryRow(ctx, `INSERT INTO ai_index_jobs(triggered_by) VALUES($1) ON CONFLICT ((true)) WHERE status IN ('pending','running') DO UPDATE SET status=ai_index_jobs.status RETURNING id::text`, user).Scan(&id)
	if err != nil {
		return Job{}, err
	}
	return r.Job(ctx, id)
}
func (r *Repository) Job(ctx context.Context, id string) (Job, error) {
	var j Job
	err := r.DB.QueryRow(ctx, "SELECT id::text,status,index_version_id::text,error_msg,created_at,started_at,finished_at FROM ai_index_jobs WHERE id=$1", id).Scan(&j.ID, &j.Status, &j.Version, &j.Error, &j.CreatedAt, &j.StartedAt, &j.FinishedAt)
	return j, err
}
func (r *Repository) Jobs(ctx context.Context) ([]Job, error) {
	rows, err := r.DB.Query(ctx, "SELECT id::text,status,index_version_id::text,error_msg,created_at,started_at,finished_at FROM ai_index_jobs ORDER BY created_at DESC,id LIMIT 50")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Job{}
	for rows.Next() {
		var j Job
		if err = rows.Scan(&j.ID, &j.Status, &j.Version, &j.Error, &j.CreatedAt, &j.StartedAt, &j.FinishedAt); err != nil {
			return nil, err
		}
		out = append(out, j)
	}
	return out, rows.Err()
}
func (r *Repository) Versions(ctx context.Context) ([]Version, error) {
	rows, err := r.DB.Query(ctx, "SELECT id::text,version_tag,num_vectors,is_active,built_at FROM ai_index_versions ORDER BY built_at DESC,id LIMIT 50")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Version{}
	for rows.Next() {
		var v Version
		if err = rows.Scan(&v.ID, &v.Tag, &v.Vectors, &v.Active, &v.BuiltAt); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}
