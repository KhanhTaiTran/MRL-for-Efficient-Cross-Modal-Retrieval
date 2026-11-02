package catalog

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"core-api/internal/auth"
	"core-api/internal/models"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestEnrichmentVersionIsolation(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set TEST_DATABASE_URL for the isolated PostgreSQL integration test")
	}
	ctx := context.Background()
	admin, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close()
	random, err := auth.RandomToken()
	if err != nil {
		t.Fatal(err)
	}
	schema := "catalog_test_" + random[:12]
	identifier := pgx.Identifier{schema}.Sanitize()
	if _, err = admin.Exec(ctx, "CREATE SCHEMA "+identifier); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := admin.Exec(ctx, "DROP SCHEMA "+identifier+" CASCADE"); err != nil {
			t.Error(err)
		}
	}()
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal(err)
	}
	config.ConnConfig.RuntimeParams["search_path"] = schema
	db, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for _, name := range []string{"000001_initial_schema.up.sql", "000002_commerce.up.sql", "000003_catalog_admin.up.sql"} {
		migration, err := os.ReadFile(filepath.Join("..", "..", "..", "infra", "migrations", name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err = db.Exec(ctx, string(migration)); err != nil {
			t.Fatal(err)
		}
	}

	var a, b, aa, ab, ba, versionA, versionB string
	for _, v := range []struct {
		sql string
		dst *string
	}{
		{"INSERT INTO products(handle,name,base_price) VALUES('a','Product A',0) RETURNING id::text", &a},
		{"INSERT INTO products(handle,name,base_price) VALUES('b','Product B',20) RETURNING id::text", &b},
		{"INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,num_vectors,supported_dims,index_path) VALUES(gen_random_uuid(),'version-a','test','test',3,'{512}','test') RETURNING id::text", &versionA},
		{"INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,num_vectors,supported_dims,index_path) VALUES(gen_random_uuid(),'version-b','test','test',1,'{512}','test') RETURNING id::text", &versionB},
	} {
		if err = db.QueryRow(ctx, v.sql).Scan(v.dst); err != nil {
			t.Fatal(err)
		}
	}
	for _, v := range []struct {
		product, key string
		dst          *string
	}{{a, "a/first.png", &aa}, {a, "a/second.png", &ab}, {b, "b/first.png", &ba}} {
		if err = db.QueryRow(ctx, "INSERT INTO product_images(product_id,object_key) VALUES($1,$2) RETURNING id::text", v.product, v.key).Scan(v.dst); err != nil {
			t.Fatal(err)
		}
	}
	for _, v := range []struct {
		version string
		vector  int
		image   string
	}{{versionA, 0, aa}, {versionA, 1, ab}, {versionA, 2, ba}, {versionB, 0, ba}} {
		if _, err = db.Exec(ctx, "INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id) VALUES($1,$2,$3)", v.version, v.vector, v.image); err != nil {
			t.Fatal(err)
		}
	}
	repo := Repository{DB: db, MediaBase: "http://storage/products"}
	input := []models.EnrichedResult{{VectorID: 0, CatalogProductID: b, SimilarityScore: .9}, {VectorID: 1, SimilarityScore: .8}, {VectorID: 2, SimilarityScore: .7}}
	results, err := repo.Enrich(ctx, versionA, input)
	if err != nil {
		t.Fatal(err)
	}
	if len(results) != 2 || results[0].CatalogProductID != a || results[1].CatalogProductID != b || results[0].SimilarityScore != .9 || results[0].Price == nil || *results[0].Price != 0 || results[0].ImageURL != "http://storage/products/a/first.png" {
		t.Fatalf("ranking, dedup, authoritative mapping or zero price lost: %+v", results)
	}
	other, err := repo.Enrich(ctx, versionB, input[:1])
	if err != nil || len(other) != 1 || other[0].CatalogProductID != b {
		t.Fatalf("mixed index versions: %+v %v", other, err)
	}
	if _, err = repo.Enrich(ctx, "unknown-version", input); !errors.Is(err, ErrIndexNotMapped) {
		t.Fatalf("unmapped version accepted: %v", err)
	}
	if _, err = db.Exec(ctx, "UPDATE products SET is_active=false WHERE id=$1", b); err != nil {
		t.Fatal(err)
	}
	results, err = repo.Enrich(ctx, versionA, input)
	if err != nil || len(results) != 1 || results[0].CatalogProductID != a {
		t.Fatalf("hidden product not filtered: %+v %v", results, err)
	}
}
