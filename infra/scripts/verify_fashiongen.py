"""Check real FashionGen retrieval plus checkout/review on a real product.

Only a disposable customer is created. Its order/review/session are removed;
the unit purchased by this check is returned to inventory in finally.
"""
import os
from uuid import uuid4

import bcrypt
import psycopg
import requests


def main():
    api = os.environ.get("API_URL", "http://localhost:18080")
    web = os.environ.get("FRONTEND_URL", "http://localhost:13000")
    origin = os.environ.get("WEB_ORIGIN", "http://localhost:13000")
    suffix = uuid4().hex[:12]
    user = None

    def call(method, path, token="", expected=200, **kwargs):
        headers = {"Origin": origin}
        if token:
            headers["Authorization"] = "Bearer " + token
        headers.update(kwargs.pop("headers", {}))
        response = requests.request(method, api + "/api" + path, headers=headers, timeout=45, **kwargs)
        assert response.status_code == expected, (path, response.status_code, response.text[:300])
        return response.json()

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        try:
            version, count, meta = db.execute("SELECT id,num_vectors,metadata FROM ai_index_versions WHERE is_active").fetchone()
            assert meta["catalog_source"] == "FashionGen" and meta["model_kind"] == "trained-mrl"
            assert count == 32528 and meta["num_products"] == 7519
            assert db.execute("SELECT count(*) FROM index_vector_mappings WHERE index_version_id=%s", (version,)).fetchone()[0] == count
            assert db.execute("SELECT count(*) FROM products WHERE is_active AND metadata->>'source_dataset'='FashionGen'").fetchone()[0] == 7519
            assert db.execute("SELECT count(*) FROM products WHERE is_active AND metadata->>'demo'='true'").fetchone()[0] == 0
            config = call("GET", "/search/config")
            assert config["active_index_version"] == str(version)
            assert config["supported_dims"] == [16, 32, 64, 128, 256, 512]
            assert config["num_vectors"] == count and config["catalog_source"] == "FashionGen"
            assert config["model_kind"] == "trained-mrl" and "simulated" in config["commerce_data_note"]
            print("PASS: SQL corpus, all mappings, loaded version and trained MRL provenance", flush=True)
            for dimension in config["supported_dims"]:
                result = call("POST", "/search/text", data={"query": "blue denim jacket", "mrl_dimension": dimension, "search_mode": "direct"})
                assert result["data"] and result["index_version"] == str(version)
                assert all(item["handle"].startswith("fashiongen-") and item["image_url"] and item["price"] >= 0 for item in result["data"])
            print("PASS: text retrieval at 16/32/64/128/256/512D with real SQL product links/prices", flush=True)
            filename, pid, handle, variant, cents = db.execute("""SELECT split_part(i.object_key,'/',3),p.id,p.handle,v.id,(v.price*100)::bigint
                FROM index_vector_mappings m JOIN product_images i ON i.id=m.product_image_id
                JOIN products p ON p.id=i.product_id JOIN product_variants v ON v.id=p.default_variant_id
                WHERE m.index_version_id=%s AND m.vector_id=0""", (version,)).fetchone()
            image = requests.get(api + "/images/" + filename, timeout=30)
            assert image.status_code == 200
            result = call("POST", "/search/image", files={"image": (filename, image.content, "image/jpeg")}, data={"mrl_dimension": 512, "search_mode": "direct"})
            assert any(item["catalog_product_id"] == str(pid) and item["similarity_score"] > .999 for item in result["data"])
            product = call("GET", "/products/" + handle)["data"]
            assert len(product["images"]) > 1 and "simulated" in product["commerce_data_note"]
            assert requests.get(web + "/product/" + handle, timeout=45).status_code == 200
            print("PASS: uploaded real image matches its indexed product (>0.999); gallery and detail page", flush=True)

            email = "fashiongen-check-" + suffix + "@aurafind.test"
            password = "FashionGen-integration-check-2026"
            user = db.execute("INSERT INTO users(email,name,password_hash,is_verified) VALUES(%s,'FashionGen verifier',%s,true) RETURNING id", (email, bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())).fetchone()[0]
            token = call("POST", "/auth/login", json={"email": email, "password": password})["access_token"]
            call("PUT", "/wishlist/" + str(pid), token)
            assert call("GET", "/wishlist", token)["data"][0]["id"] == str(pid)
            stock = db.execute("SELECT stock FROM product_variants WHERE id=%s", (variant,)).fetchone()[0]
            assert stock > 0
            call("PUT", "/cart/items/" + str(variant), token, json={"quantity": 1})
            payload = {"currency": "USD", "items": [{"variant_id": str(variant), "quantity": 1, "price_cents": cents}], "shipping_address": {"name": "Verifier", "line1": "1 Demo Street", "line2": "", "city": "Demo", "region": "", "postal_code": "12345", "country": "US"}}
            order = call("POST", "/checkout", token, expected=201, headers={"Idempotency-Key": "fashiongen-" + suffix}, json=payload)["data"]
            assert order["total_cents"] == cents
            assert db.execute("SELECT stock FROM product_variants WHERE id=%s", (variant,)).fetchone()[0] == stock - 1
            call("PUT", "/products/" + handle + "/review", token, json={"rating": 5, "comment": "Disposable real-catalog integration check"})
            assert call("GET", "/products/" + handle + "/reviews")["data"]
            print("PASS: real-product wishlist, exact-price checkout, stock deduction and verified-purchase review", flush=True)
        finally:
            if user:
                with db.transaction():
                    items = db.execute("SELECT oi.variant_id,sum(oi.quantity)::int FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.user_id=%s GROUP BY oi.variant_id ORDER BY oi.variant_id", (user,)).fetchall()
                    for variant, quantity in items:
                        db.execute("UPDATE product_variants SET stock=stock+%s WHERE id=%s", (quantity, variant))
                    db.execute("DELETE FROM reviews WHERE user_id=%s", (user,))
                    db.execute("DELETE FROM orders WHERE user_id=%s", (user,))
                    db.execute("DELETE FROM users WHERE id=%s", (user,))
    print("PASS: FashionGen end-to-end; customer/session/order/review removed, purchased stock restored", flush=True)


if __name__ == "__main__":
    main()
