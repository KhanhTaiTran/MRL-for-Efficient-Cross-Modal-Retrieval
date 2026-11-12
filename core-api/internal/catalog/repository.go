package catalog

import (
	"context"
	"errors"
	"net/url"
	"path"
	"sort"
	"strings"

	"core-api/internal/models"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Repository struct {
	DB        *pgxpool.Pool
	MediaBase string
}
type Product struct {
	ID               string    `json:"id"`
	Handle           string    `json:"handle"`
	Name             string    `json:"name"`
	Description      string    `json:"description"`
	Brand            string    `json:"brand"`
	Category         string    `json:"category"`
	Price            float64   `json:"price"`
	Currency         string    `json:"currency"`
	ImageURL         string    `json:"image_url"`
	ReviewCount      int       `json:"review_count"`
	RatingAverage    *float64  `json:"rating_average"`
	Featured         bool      `json:"is_featured"`
	SearchStatus     string    `json:"search_status"`
	CommerceDataNote string    `json:"commerce_data_note,omitempty"`
	DefaultVariantID string    `json:"default_variant_id"`
	Images           []Image   `json:"images,omitempty"`
	Variants         []Variant `json:"variants,omitempty"`
	SimilarityScore  *float64  `json:"similarity_score,omitempty"`
	RankScore        *float64  `json:"rank_score,omitempty"`
}
type Image struct {
	ID      string `json:"id"`
	URL     string `json:"url"`
	Alt     string `json:"alt"`
	Primary bool   `json:"is_primary"`
}
type Variant struct {
	ID        string  `json:"id"`
	SKU       string  `json:"sku"`
	Size      string  `json:"size"`
	Color     string  `json:"color"`
	Price     float64 `json:"price"`
	Stock     int     `json:"stock"`
	Available bool    `json:"is_available"`
}
type Filter struct {
	Category, Q, Sort string
	Featured          bool
	Min, Max          *float64
	Page, Limit       int
}

func (r *Repository) ImageURL(key string) string {
	if key == "" {
		return ""
	}
	parts := strings.Split(key, "/")
	for i, p := range parts {
		parts[i] = url.PathEscape(p)
	}
	return strings.TrimRight(r.MediaBase, "/") + "/" + strings.Join(parts, "/")
}

const fields = `p.id::text,p.handle,p.name,COALESCE(p.description,''),COALESCE(p.brand,''),COALESCE(p.category,''),p.base_price::float8,p.currency,COALESCE(img.object_key,''),COALESCE(rv.count,0)::int,rv.average,p.is_featured,p.search_status,COALESCE(p.default_variant_id::text,''),COALESCE(p.metadata->>'commerce_data_note','')`
const joins = ` LEFT JOIN LATERAL (SELECT object_key FROM product_images WHERE product_id=p.id AND is_active ORDER BY is_primary DESC,position,id LIMIT 1) img ON true LEFT JOIN LATERAL (SELECT count(*) count,avg(rating)::float8 average FROM reviews WHERE product_id=p.id AND NOT is_hidden) rv ON true `

func (r *Repository) scan(row pgx.Row) (Product, error) {
	var p Product
	var key string
	err := row.Scan(&p.ID, &p.Handle, &p.Name, &p.Description, &p.Brand, &p.Category, &p.Price, &p.Currency, &key, &p.ReviewCount, &p.RatingAverage, &p.Featured, &p.SearchStatus, &p.DefaultVariantID, &p.CommerceDataNote)
	p.ImageURL = r.ImageURL(key)
	return p, err
}

func (r *Repository) List(ctx context.Context, f Filter) ([]Product, int, error) {
	where := ` WHERE p.is_active AND ($1='' OR p.category=$1) AND ($2='' OR p.name ILIKE '%'||$2||'%' OR p.brand ILIKE '%'||$2||'%') AND (NOT $3::boolean OR p.is_featured) AND ($4::numeric IS NULL OR p.base_price>=$4) AND ($5::numeric IS NULL OR p.base_price<=$5)`
	args := []any{f.Category, f.Q, f.Featured, f.Min, f.Max}
	var total int
	if err := r.DB.QueryRow(ctx, "SELECT count(*) FROM products p"+where, args...).Scan(&total); err != nil {
		return nil, 0, err
	}
	order := map[string]string{"newest": "p.created_at DESC,p.id", "price_asc": "p.base_price,p.id", "price_desc": "p.base_price DESC,p.id", "name": "p.name,p.id"}[f.Sort]
	if order == "" {
		order = "p.created_at DESC,p.id"
	}
	args = append(args, f.Limit, (f.Page-1)*f.Limit)
	rows, err := r.DB.Query(ctx, "SELECT "+fields+" FROM products p"+joins+where+" ORDER BY "+order+" LIMIT $6 OFFSET $7", args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	products := []Product{}
	for rows.Next() {
		p, err := r.scan(rows)
		if err != nil {
			return nil, 0, err
		}
		products = append(products, p)
	}
	return products, total, rows.Err()
}

func (r *Repository) Get(ctx context.Context, handle string) (Product, error) {
	p, err := r.scan(r.DB.QueryRow(ctx, "SELECT "+fields+" FROM products p"+joins+" WHERE p.handle=$1 AND p.is_active", handle))
	if err != nil {
		return p, err
	}
	rows, err := r.DB.Query(ctx, "SELECT id::text,object_key,COALESCE(alt_text,''),is_primary FROM product_images WHERE product_id=$1 AND is_active ORDER BY is_primary DESC,position,id", p.ID)
	if err != nil {
		return p, err
	}
	p.Images = []Image{}
	for rows.Next() {
		var image Image
		var key string
		if err = rows.Scan(&image.ID, &key, &image.Alt, &image.Primary); err != nil {
			rows.Close()
			return p, err
		}
		image.URL = r.ImageURL(key)
		p.Images = append(p.Images, image)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return p, err
	}
	rows, err = r.DB.Query(ctx, "SELECT id::text,COALESCE(sku,''),size,color,price::float8,stock,is_available FROM product_variants WHERE product_id=$1 ORDER BY size,color,id", p.ID)
	if err != nil {
		return p, err
	}
	defer rows.Close()
	p.Variants = []Variant{}
	for rows.Next() {
		var v Variant
		if err = rows.Scan(&v.ID, &v.SKU, &v.Size, &v.Color, &v.Price, &v.Stock, &v.Available); err != nil {
			return p, err
		}
		p.Variants = append(p.Variants, v)
	}
	return p, rows.Err()
}

func (r *Repository) Categories(ctx context.Context) ([]string, error) {
	rows, err := r.DB.Query(ctx, "SELECT DISTINCT category FROM products WHERE is_active AND COALESCE(category,'')<>'' ORDER BY category")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []string{}
	for rows.Next() {
		var category string
		if err = rows.Scan(&category); err != nil {
			return nil, err
		}
		result = append(result, category)
	}
	return result, rows.Err()
}

var ErrIndexNotMapped = errors.New("inference index has no catalog mapping")

func (r *Repository) Enrich(ctx context.Context, version string, results []models.EnrichedResult) ([]models.EnrichedResult, error) {
	var id string
	err := r.DB.QueryRow(ctx, "SELECT id::text FROM ai_index_versions WHERE id::text=$1 OR version_tag=$1", version).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrIndexNotMapped
	}
	if err != nil {
		return nil, err
	}
	ids := make([]int, 0, len(results))
	for _, p := range results {
		ids = append(ids, p.VectorID)
		for _, alternate := range p.ImageCandidates {
			ids = append(ids, alternate.VectorID)
		}
	}
	rows, err := r.DB.Query(ctx, `SELECT m.vector_id,p.id::text,p.handle,p.name,COALESCE(p.brand,''),p.base_price::float8,p.currency,pi.object_key,COALESCE(rv.count,0)::int,rv.average,p.is_active,pi.is_active
 FROM index_vector_mappings m JOIN product_images pi ON pi.id=m.product_image_id JOIN products p ON p.id=pi.product_id
 LEFT JOIN LATERAL (SELECT count(*) count,avg(rating)::float8 average FROM reviews WHERE product_id=p.id AND NOT is_hidden) rv ON true
 WHERE m.index_version_id=$1 AND m.vector_id=ANY($2::int[])`, id, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	matched := map[int]models.EnrichedResult{}
	identities := map[int]string{}
	for rows.Next() {
		var p models.EnrichedResult
		var key string
		var productActive, imageActive bool
		if err = rows.Scan(&p.VectorID, &p.CatalogProductID, &p.Handle, &p.Name, &p.Brand, &p.Price, &p.Currency, &key, &p.ReviewCount, &p.RatingAverage, &productActive, &imageActive); err != nil {
			return nil, err
		}
		identities[p.VectorID] = p.CatalogProductID
		if !productActive || !imageActive {
			continue
		}
		p.ImageURL = r.ImageURL(key)
		p.ProductID = path.Base(key)
		matched[p.VectorID] = p
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	// Preserve the worker's ranking; collapse multiple images of a product.
	enriched := []models.EnrichedResult{}
	seen := map[string]bool{}
	for _, original := range results {
		authoritativeID := identities[original.VectorID]
		if len(original.ImageCandidates) > 0 && (authoritativeID == "" || original.CatalogProductID != authoritativeID) {
			continue
		}
		candidates := append([]models.ImageCandidate(nil), original.ImageCandidates...)
		if len(candidates) == 0 {
			candidates = []models.ImageCandidate{{VectorID: original.VectorID, SimilarityScore: original.SimilarityScore}}
		}
		sort.SliceStable(candidates, func(i, j int) bool { return candidates[i].SimilarityScore > candidates[j].SimilarityScore })
		var p models.EnrichedResult
		found := false
		for _, candidate := range candidates {
			mapped, ok := matched[candidate.VectorID]
			if !ok {
				continue
			}
			// Alternate views must belong to the product identified by the main vector.
			if len(original.ImageCandidates) > 0 && mapped.CatalogProductID != authoritativeID {
				continue
			}
			p = mapped
			p.SimilarityScore = candidate.SimilarityScore
			found = true
			break
		}
		if !found || seen[p.CatalogProductID] {
			continue
		}
		seen[p.CatalogProductID] = true
		if p.VectorID == original.VectorID {
			p.ProductID = original.ProductID
		}
		p.Caption = original.Caption
		p.RankScore = original.RankScore
		enriched = append(enriched, p)
	}
	return enriched, nil
}

// Eligibility is applied before either retriever takes a bounded candidate set.
// Query text deliberately does not participate in this catalog filter.
const searchEligibility = `p.is_active AND ($1='' OR p.category=$1) AND (NOT $2::boolean OR p.is_featured) AND ($3::numeric IS NULL OR p.base_price >= $3) AND ($4::numeric IS NULL OR p.base_price <= $4) AND EXISTS (SELECT 1 FROM product_images e WHERE e.product_id=p.id AND e.is_active)`

func searchFilterArgs(f Filter) []any { return []any{f.Category, f.Featured, f.Min, f.Max} }

func (r *Repository) EligibleProductIDs(ctx context.Context, f Filter) ([]string, error) {
	rows, err := r.DB.Query(ctx, "SELECT p.id::text FROM products p WHERE "+searchEligibility+" ORDER BY p.id", searchFilterArgs(f)...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	ids := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

// SearchProducts hydrates and orders the complete retrieved pool before paging.
func (r *Repository) SearchProducts(ctx context.Context, results []models.EnrichedResult, f Filter) ([]Product, error) {
	products := []Product{}
	if len(results) == 0 {
		return products, nil
	}
	ids := make([]string, 0, len(results))
	byID := make(map[string]models.EnrichedResult, len(results))
	for _, result := range results {
		ids = append(ids, result.CatalogProductID)
		byID[result.CatalogProductID] = result
	}
	order := map[string]string{"newest": "p.created_at DESC,p.id", "price_asc": "p.base_price,p.id", "price_desc": "p.base_price DESC,p.id", "name": "p.name,p.id"}[f.Sort]
	if order == "" {
		order = "array_position($5::uuid[],p.id)"
	}
	args := append(searchFilterArgs(f), ids)
	rows, err := r.DB.Query(ctx, "SELECT "+fields+" FROM products p"+joins+" WHERE "+searchEligibility+" AND p.id=ANY($5::uuid[]) ORDER BY "+order, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		p, err := r.scan(rows)
		if err != nil {
			return nil, err
		}
		candidate := byID[p.ID]
		p.ImageURL = candidate.ImageURL
		p.SimilarityScore = &candidate.SimilarityScore
		p.RankScore = candidate.RankScore
		products = append(products, p)
	}
	return products, rows.Err()
}
