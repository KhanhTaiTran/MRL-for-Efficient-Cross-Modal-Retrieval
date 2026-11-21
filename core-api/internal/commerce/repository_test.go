package commerce

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"core-api/internal/auth"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func assertCode(t *testing.T, err error, code string) {
	t.Helper()
	var e *Error
	if !errors.As(err, &e) || e.Code != code {
		t.Fatalf("expected %s, got %v", code, err)
	}
}
func TestCanonicalQuote(t *testing.T) {
	in := CheckoutInput{Currency: "USD", ShippingAddress: Address{Name: " Buyer ", Line1: "Street", City: "City", PostalCode: "123", Country: "us"}, Items: []QuoteItem{{VariantID: "00000000-0000-0000-0000-000000000002", Quantity: 2, PriceCents: 10}, {VariantID: "00000000-0000-0000-0000-000000000001", Quantity: 1}}}
	normalized, h1, err := Canonicalize(in, "test-key-123")
	if err != nil {
		t.Fatal(err)
	}
	in.Items[0], in.Items[1] = in.Items[1], in.Items[0]
	in.ShippingAddress = normalized.ShippingAddress
	_, h2, err := Canonicalize(in, "test-key-123")
	if err != nil || h1 != h2 {
		t.Fatal("equivalent quotes hash differently", err)
	}
	in.Items[0].Quantity = 0
	_, _, err = Canonicalize(in, "test-key-123")
	assertCode(t, err, "invalid_quote")
}

func TestCommerceTransactions(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set TEST_DATABASE_URL for isolated PostgreSQL integration tests")
	}
	ctx := context.Background()
	admin, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close()
	token, _ := auth.RandomToken()
	schema := "commerce_test_" + token[:12]
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
		data, err := os.ReadFile(filepath.Join("..", "..", "..", "infra", "migrations", name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err = db.Exec(ctx, string(data)); err != nil {
			t.Fatal(err)
		}
	}
	repo := &Repository{DB: db, MediaBase: "https://media.example/products"}
	mustExec := func(sql string, args ...any) {
		t.Helper()
		if _, err := db.Exec(ctx, sql, args...); err != nil {
			t.Fatal(err)
		}
	}
	var a, b, product, variant string
	if err = db.QueryRow(ctx, "INSERT INTO users(email,name,is_verified) VALUES('a@example.test','A',true) RETURNING id::text").Scan(&a); err != nil {
		t.Fatal(err)
	}
	if err = db.QueryRow(ctx, "INSERT INTO users(email,name,is_verified) VALUES('b@example.test','B',true) RETURNING id::text").Scan(&b); err != nil {
		t.Fatal(err)
	}
	if err = db.QueryRow(ctx, "INSERT INTO products(handle,name,base_price) VALUES('test','Original',0.10) RETURNING id::text").Scan(&product); err != nil {
		t.Fatal(err)
	}
	if err = db.QueryRow(ctx, "INSERT INTO product_variants(product_id,price,stock) VALUES($1,0.10,200) RETURNING id::text", product).Scan(&variant); err != nil {
		t.Fatal(err)
	}
	address := Address{Name: "Buyer", Line1: "1 Street", City: "City", PostalCode: "12345", Country: "US"}
	quote := func(user string) CheckoutInput {
		t.Helper()
		c, err := repo.Cart(ctx, user)
		if err != nil {
			t.Fatal(err)
		}
		items := []QuoteItem{}
		for _, i := range c.Items {
			items = append(items, QuoteItem{i.VariantID, i.Quantity, i.PriceCents})
		}
		return CheckoutInput{address, items, "USD"}
	}
	t.Run("cart validation and absolute quantity", func(t *testing.T) {
		assertCode(t, repo.SetItem(ctx, a, variant, 0), "invalid_quantity")
		assertCode(t, repo.SetItem(ctx, a, variant, 100), "invalid_quantity")
		for i := 0; i < 2; i++ {
			if err := repo.SetItem(ctx, a, variant, 3); err != nil {
				t.Fatal(err)
			}
		}
		c, err := repo.Cart(ctx, a)
		if err != nil || len(c.Items) != 1 || c.Items[0].Quantity != 3 || c.TotalCents != 30 {
			t.Fatalf("bad cart %+v %v", c, err)
		}
		mustExec("UPDATE product_variants SET is_available=false WHERE id=$1", variant)
		assertCode(t, repo.SetItem(ctx, a, variant, 1), "unavailable")
		_, _, err = repo.Checkout(ctx, a, "disabled-variant", quote(a))
		assertCode(t, err, "unavailable")
		mustExec("UPDATE product_variants SET is_available=true WHERE id=$1", variant)
	})
	t.Run("stale quote and rollback", func(t *testing.T) {
		in := quote(a)
		in.Items[0].PriceCents++
		_, _, err := repo.Checkout(ctx, a, "tampered-price", in)
		assertCode(t, err, "cart_changed")
		mustExec(`CREATE FUNCTION reject_item() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected order item failure'; END $$`)
		mustExec(`CREATE TRIGGER fail_item BEFORE INSERT ON order_items FOR EACH ROW EXECUTE FUNCTION reject_item()`)
		_, _, err = repo.Checkout(ctx, a, "rollback-test", quote(a))
		if err == nil {
			t.Fatal("expected injected failure")
		}
		var stock, orders int
		db.QueryRow(ctx, "SELECT stock FROM product_variants WHERE id=$1", variant).Scan(&stock)
		db.QueryRow(ctx, "SELECT count(*) FROM orders").Scan(&orders)
		c, _ := repo.Cart(ctx, a)
		if stock != 200 || orders != 0 || len(c.Items) != 1 {
			t.Fatalf("transaction leaked: %d %d %+v", stock, orders, c)
		}
		mustExec("DROP TRIGGER fail_item ON order_items")
		mustExec("DROP FUNCTION reject_item()")
	})
	t.Run("concurrent retry ownership and immutable snapshot", func(t *testing.T) {
		in := quote(a)
		var wg sync.WaitGroup
		orders := make([]Order, 6)
		errs := make([]error, 6)
		for i := range orders {
			wg.Add(1)
			go func(i int) { defer wg.Done(); orders[i], _, errs[i] = repo.Checkout(ctx, a, "same-checkout", in) }(i)
		}
		wg.Wait()
		for i, err := range errs {
			if err != nil || orders[i].ID != orders[0].ID {
				t.Fatalf("retry %d: %+v %v", i, orders[i], err)
			}
		}
		if orders[0].TotalCents != 30 {
			t.Fatal("inexact money")
		}
		var stock int
		db.QueryRow(ctx, "SELECT stock FROM product_variants WHERE id=$1", variant).Scan(&stock)
		if stock != 197 {
			t.Fatal("stock decremented more than once", stock)
		}
		in.ShippingAddress.Line1 = "Changed"
		_, _, err := repo.Checkout(ctx, a, "same-checkout", in)
		assertCode(t, err, "idempotency_conflict")
		_, err = repo.Order(ctx, b, orders[0].ID)
		assertCode(t, err, "order_not_found")
		if err := repo.SetItem(ctx, b, variant, 2); err != nil {
			t.Fatal(err)
		}
		if err := repo.RemoveItem(ctx, a, variant); err != nil {
			t.Fatal(err)
		}
		bc, _ := repo.Cart(ctx, b)
		if len(bc.Items) != 1 {
			t.Fatal("foreign cart changed")
		}
		repo.RemoveItem(ctx, b, variant)
		mustExec("UPDATE products SET name='Edited' WHERE id=$1", product)
		mustExec("UPDATE product_variants SET price=9.99 WHERE id=$1", variant)
		saved, err := repo.Order(ctx, a, orders[0].ID)
		if err != nil || saved.Items[0].Name != "Original" || saved.Items[0].PriceCents != 10 || saved.ShippingAddress.Line1 != "1 Street" {
			t.Fatalf("snapshot changed %+v %v", saved, err)
		}
	})
	t.Run("last unit competition", func(t *testing.T) {
		mustExec("UPDATE product_variants SET price=0,stock=1 WHERE id=$1", variant)
		for _, u := range []string{a, b} {
			if err := repo.SetItem(ctx, u, variant, 1); err != nil {
				t.Fatal(err)
			}
		}
		qa, qb := quote(a), quote(b)
		var wg sync.WaitGroup
		errs := make([]error, 2)
		for i, u := range []string{a, b} {
			in := qa
			if i == 1 {
				in = qb
			}
			wg.Add(1)
			go func(i int, u string, in CheckoutInput) {
				defer wg.Done()
				_, _, errs[i] = repo.Checkout(ctx, u, "last-unit-key", in)
			}(i, u, in)
		}
		wg.Wait()
		successes := 0
		for _, err := range errs {
			if err == nil {
				successes++
			} else {
				assertCode(t, err, "unavailable")
			}
		}
		if successes != 1 {
			t.Fatal("expected one buyer", errs)
		}
		var stock int
		db.QueryRow(ctx, "SELECT stock FROM product_variants WHERE id=$1", variant).Scan(&stock)
		if stock != 0 {
			t.Fatal("bad stock", stock)
		}
	})
	t.Run("total bounds and inactive products", func(t *testing.T) {
		mustExec("DELETE FROM cart_items")
		mustExec("UPDATE product_variants SET price=0.01,stock=200 WHERE id=$1", variant)
		if err := repo.SetItem(ctx, a, variant, 99); err != nil {
			t.Fatal(err)
		}
		cart, err := repo.Cart(ctx, a)
		if err != nil || cart.TotalCents != 99 {
			t.Fatalf("99 cents must be exact: %+v %v", cart, err)
		}
		in := quote(a)
		mustExec("UPDATE products SET is_active=false WHERE id=$1", product)
		_, _, err = repo.Checkout(ctx, a, "inactive-product", in)
		assertCode(t, err, "unavailable")
		mustExec("UPDATE products SET is_active=true WHERE id=$1", product)
		mustExec("UPDATE product_variants SET price=9999999999.99 WHERE id=$1", variant)
		cart, err = repo.Cart(ctx, a)
		if err != nil || cart.CanCheckout || !cart.LimitExceeded {
			t.Fatalf("oversized cart must remain editable: %+v %v", cart, err)
		}
		_, _, err = repo.Checkout(ctx, a, "oversized-order-total", quote(a))
		assertCode(t, err, "total_limit")
		if err = repo.SetItem(ctx, a, variant, 1); err != nil {
			t.Fatal(err)
		}
		order, _, err := repo.Checkout(ctx, a, "maximum-order-total", quote(a))
		if err != nil || order.TotalCents != MaxTotalCents {
			t.Fatalf("maximum exact total: %+v %v", order, err)
		}
	})
	t.Run("cart mutation serializes with checkout", func(t *testing.T) {
		mustExec("DELETE FROM cart_items")
		mustExec("UPDATE product_variants SET price=1,stock=200 WHERE id=$1", variant)
		if err := repo.SetItem(ctx, a, variant, 1); err != nil {
			t.Fatal(err)
		}
		in := quote(a)
		var checkoutErr, updateErr error
		var wg sync.WaitGroup
		start := make(chan struct{})
		wg.Add(2)
		go func() { defer wg.Done(); <-start; _, _, checkoutErr = repo.Checkout(ctx, a, "cart-race-key", in) }()
		go func() { defer wg.Done(); <-start; updateErr = repo.SetItem(ctx, a, variant, 2) }()
		close(start)
		wg.Wait()
		if updateErr != nil {
			t.Fatal(updateErr)
		}
		if checkoutErr != nil {
			assertCode(t, checkoutErr, "cart_changed")
		}
		cart, err := repo.Cart(ctx, a)
		if err != nil || len(cart.Items) != 1 || cart.Items[0].Quantity != 2 {
			t.Fatalf("concurrent cart update was lost: %+v %v", cart, err)
		}
	})
	t.Run("multi-product competing checkouts", func(t *testing.T) {
		mustExec("DELETE FROM cart_items")
		mustExec("UPDATE product_variants SET price=1,stock=1 WHERE id=$1", variant)
		var secondProduct, secondVariant string
		if err := db.QueryRow(ctx, "INSERT INTO products(handle,name,base_price) VALUES('second','Second',2) RETURNING id::text").Scan(&secondProduct); err != nil {
			t.Fatal(err)
		}
		if err := db.QueryRow(ctx, "INSERT INTO product_variants(product_id,price,stock) VALUES($1,2,1) RETURNING id::text", secondProduct).Scan(&secondVariant); err != nil {
			t.Fatal(err)
		}
		for _, user := range []string{a, b} {
			for _, id := range []string{variant, secondVariant} {
				if err := repo.SetItem(ctx, user, id, 1); err != nil {
					t.Fatal(err)
				}
			}
		}
		qa, qb := quote(a), quote(b)
		qb.Items[0], qb.Items[1] = qb.Items[1], qb.Items[0]
		bounded, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		var wg sync.WaitGroup
		errs := make([]error, 2)
		for i, user := range []string{a, b} {
			in := qa
			if i == 1 {
				in = qb
			}
			wg.Add(1)
			go func(i int, user string, in CheckoutInput) {
				defer wg.Done()
				_, _, errs[i] = repo.Checkout(bounded, user, "multi-product-key", in)
			}(i, user, in)
		}
		wg.Wait()
		successes := 0
		for _, err := range errs {
			if err == nil {
				successes++
			} else {
				assertCode(t, err, "unavailable")
			}
		}
		if successes != 1 {
			t.Fatal("expected one atomic multi-item purchase", errs)
		}
		var sum int
		if err := db.QueryRow(ctx, "SELECT sum(stock) FROM product_variants WHERE id=ANY($1::uuid[])", []string{variant, secondVariant}).Scan(&sum); err != nil || sum != 0 {
			t.Fatalf("bad multi-item stock %d %v", sum, err)
		}
	})
}
