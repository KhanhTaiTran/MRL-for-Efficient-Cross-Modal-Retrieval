package admin

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"core-api/internal/auth"
	"core-api/internal/catalog"
	"core-api/internal/commerce"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestAdminRepository(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set TEST_DATABASE_URL for isolated PostgreSQL tests")
	}
	ctx := context.Background()
	adminDB, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer adminDB.Close()
	token, _ := auth.RandomToken()
	schema := "admin_test_" + token[:12]
	ident := pgx.Identifier{schema}.Sanitize()
	if _, err = adminDB.Exec(ctx, "CREATE SCHEMA "+ident); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := adminDB.Exec(ctx, "DROP SCHEMA "+ident+" CASCADE"); err != nil {
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
		data, err := os.ReadFile(filepath.Join("..", "..", "..", "infra", "migrations", name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err = db.Exec(ctx, string(data)); err != nil {
			t.Fatal(err)
		}
	}
	repo := &Repository{DB: db, MediaBase: "http://media.test/products"}
	code := func(err error, status int) {
		t.Helper()
		var e *commerce.Error
		if !errors.As(err, &e) || e.Status != status {
			t.Fatalf("expected %d: %v", status, err)
		}
	}
	input := ProductInput{Handle: "test-product", Name: "Original", PriceCents: 1234, Active: true}
	pid, err := repo.Create(ctx, input)
	if err != nil {
		t.Fatal(err)
	}
	_, err = repo.Create(ctx, input)
	code(err, 409)
	p, err := repo.Get(ctx, pid)
	if err != nil {
		t.Fatal(err)
	}
	stale := p.ProductInput
	v := VariantInput{Size: "M", PriceCents: 1234, Stock: 3, Available: true}
	vid, err := repo.SaveVariant(ctx, pid, "", v)
	if err != nil {
		t.Fatal(err)
	}
	code(repo.Update(ctx, pid, stale), 409)
	p, _ = repo.Get(ctx, pid)
	p.Name = "Updated"
	if err = repo.Update(ctx, pid, p.ProductInput); err != nil {
		t.Fatal(err)
	}
	var user string
	if err = db.QueryRow(ctx, "INSERT INTO users(email,name,is_verified,role) VALUES('buyer@test.local','Buyer',true,'admin') RETURNING id::text").Scan(&user); err != nil {
		t.Fatal(err)
	}
	cart := commerce.Repository{DB: db}
	if err = cart.SetItem(ctx, user, vid, 1); err != nil {
		t.Fatal(err)
	}
	_, _, err = cart.Checkout(ctx, user, "admin-stock-test", commerce.CheckoutInput{Currency: "USD", ShippingAddress: commerce.Address{Name: "Buyer", Line1: "Street", City: "City", PostalCode: "123", Country: "US"}, Items: []commerce.QuoteItem{{VariantID: vid, Quantity: 1, PriceCents: 1234}}})
	if err != nil {
		t.Fatal(err)
	}
	expected := 3
	v.ExpectedStock = &expected
	v.Stock = 5
	_, err = repo.SaveVariant(ctx, pid, vid, v)
	code(err, 409)
	expected = 2
	if _, err = repo.SaveVariant(ctx, pid, vid, v); err != nil {
		t.Fatal(err)
	}
	image1 := "00000000-0000-0000-0000-000000000001"
	image2 := "00000000-0000-0000-0000-000000000002"
	if err = repo.AddImage(ctx, pid, image1, "first.png", ImageInput{}); err != nil {
		t.Fatal(err)
	}
	if err = repo.AddImage(ctx, pid, image2, "second.png", ImageInput{Primary: true}); err != nil {
		t.Fatal(err)
	}
	if err = repo.EditImage(ctx, pid, image2, ImageInput{}, true); err != nil {
		t.Fatal(err)
	}
	p, _ = repo.Get(ctx, pid)
	if len(p.Images) != 1 || p.Images[0].ID != image1 || !p.Images[0].Primary {
		t.Fatalf("primary promotion failed %+v", p.Images)
	}
	var version string
	if err = db.QueryRow(ctx, "INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,num_vectors,supported_dims,index_path,is_active) VALUES(gen_random_uuid(),'test','test','test',1,'{512}','/test',true) RETURNING id::text").Scan(&version); err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec(ctx, "INSERT INTO index_vector_mappings VALUES($1,0,$2)", version, image1); err != nil {
		t.Fatal(err)
	}
	if err = repo.EditImage(ctx, pid, image1, ImageInput{}, true); err != nil {
		t.Fatal(err)
	}
	public := catalog.Repository{DB: db}
	product, err := public.Get(ctx, "test-product")
	if err != nil || len(product.Images) != 0 {
		t.Fatalf("retired image is public %+v %v", product, err)
	}
	var retained int
	if err = db.QueryRow(ctx, "SELECT count(*) FROM index_vector_mappings WHERE index_version_id=$1", version).Scan(&retained); err != nil || retained != 1 {
		t.Fatal("historical mapping lost", err)
	}
	ids := make([]string, 6)
	errs := make([]error, 6)
	var wg sync.WaitGroup
	for i := range ids {
		wg.Add(1)
		go func(i int) { defer wg.Done(); j, err := repo.Enqueue(ctx, user); ids[i] = j.ID; errs[i] = err }(i)
	}
	wg.Wait()
	for i, err := range errs {
		if err != nil || ids[i] != ids[0] {
			t.Fatalf("queue deduplication failed %v %v", ids, errs)
		}
	}
	if err = repo.Archive(ctx, pid); err != nil {
		t.Fatal(err)
	}
	_, err = public.Get(ctx, "test-product")
	if !errors.Is(err, pgx.ErrNoRows) {
		t.Fatal("archived product remains public", err)
	}
}
