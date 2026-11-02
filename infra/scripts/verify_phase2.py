"""Verify local Phase 2 HTTP flows with isolated users/products, cleaned in finally.

Uses the development database only. Never changes seeded demo inventory.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import bcrypt
import psycopg
import requests


def main():
    api = os.environ.get('API_URL', 'http://localhost:18080')
    web = os.environ.get('FRONTEND_URL', 'http://localhost:13000')
    origin = os.environ.get('WEB_ORIGIN', 'http://localhost:13000')
    database = os.environ.get('DATABASE_URL', 'postgresql://aurafind:aurafind_dev@localhost:15432/aurafind')
    suffix = uuid4().hex[:12]
    password = 'Phase-two-integration-password-2026'
    user_ids, product_ids = [], []

    def call(method, path, token='', status=200, **kwargs):
        headers = {'Origin': origin}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        headers.update(kwargs.pop('headers', {}))
        result = requests.request(method, api + '/api' + path, headers=headers, timeout=30, **kwargs)
        assert result.status_code == status, (method, path, result.status_code, result.text)
        return result.json() if result.content else {}

    with psycopg.connect(database, autocommit=True, connect_timeout=10) as db:
        try:
            assert db.execute('SELECT version,dirty FROM schema_migrations').fetchone() == (2, False)
            tokens = []
            for n in range(2):
                email = f'phase2-{suffix}-{n}@aurafind.test'
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                user_ids.append(db.execute('INSERT INTO users(email,name,password_hash,is_verified) VALUES(%s,%s,%s,true) RETURNING id', (email, 'Phase 2 verifier', hashed)).fetchone()[0])
                tokens.append(call('POST', '/auth/login', json={'email': email, 'password': password})['access_token'])
            a, b = tokens
            product = db.execute("INSERT INTO products(handle,name,base_price) VALUES(%s,'Phase 2 fixture',0.10) RETURNING id", ('phase2-' + suffix,)).fetchone()[0]
            product_ids.append(product)
            variant = str(db.execute("INSERT INTO product_variants(product_id,price,stock) VALUES(%s,0.10,100) RETURNING id", (product,)).fetchone()[0])
            path = '/cart/items/' + variant
            call('GET', '/cart', status=401)
            call('PUT', path, a, status=403, json={'quantity': 1}, headers={'Origin': 'https://untrusted.example'})
            preflight = requests.options(api + '/api/checkout', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type,idempotency-key'}, timeout=10)
            assert preflight.status_code in (200, 204) and 'idempotency-key' in preflight.headers.get('Access-Control-Allow-Headers', '').lower()
            for quantity in (0, -1, 100, 1.5):
                call('PUT', path, a, status=400, json={'quantity': quantity})
            for _ in range(2):
                cart = call('PUT', path, a, json={'quantity': 3})['data']
                assert len(cart['items']) == 1 and cart['total_cents'] == 30 and cart['items'][0]['quantity'] == 3
            assert call('GET', '/cart', b)['data']['items'] == []
            call('DELETE', path, b)
            assert call('GET', '/cart', a)['data']['total_cents'] == 30
            address = {'name': 'Verifier', 'line1': '1 Test Street', 'line2': '', 'city': 'Test City', 'region': '', 'postal_code': '12345', 'country': 'US'}
            payload = {'shipping_address': address, 'currency': 'USD', 'items': [{'variant_id': variant, 'quantity': 3, 'price_cents': 10}]}
            key = 'phase2-' + suffix
            call('POST', '/checkout', a, status=400, json=payload)
            bad = {**payload, 'items': [{'variant_id': variant, 'quantity': 3, 'price_cents': 1}]}
            call('POST', '/checkout', a, status=409, json=bad, headers={'Idempotency-Key': key})
            first = call('POST', '/checkout', a, status=201, json=payload, headers={'Idempotency-Key': key})
            order = first['data']
            assert not first['replayed'] and order['total_cents'] == 30 and order['payment_method'] == 'mock'
            with ThreadPoolExecutor(max_workers=4) as pool:
                retries = list(pool.map(lambda _: call('POST', '/checkout', a, json=payload, headers={'Idempotency-Key': key}), range(4)))
            assert all(value['replayed'] and value['data']['id'] == order['id'] for value in retries)
            assert db.execute('SELECT stock FROM product_variants WHERE id=%s', (variant,)).fetchone()[0] == 97
            assert call('GET', '/cart', a)['data']['items'] == []
            call('POST', '/checkout', a, status=409, json={**payload, 'shipping_address': {**address, 'city': 'Changed'}}, headers={'Idempotency-Key': key})
            call('GET', '/orders/' + order['id'], b, status=404)
            assert call('GET', '/orders', b)['data'] == []
            assert call('GET', '/orders?limit=1', a)['pagination']['total'] == 1
            call('GET', '/orders?page=0', a, status=400)
            db.execute("UPDATE products SET name='Changed catalog' WHERE id=%s", (product,))
            saved = call('GET', '/orders/' + order['id'], a)['data']
            assert saved['items'][0]['name'] == 'Phase 2 fixture' and saved['items'][0]['price_cents'] == 10
            print('PASS: auth/Origin/CORS, cart ownership/validation/persistence, exact totals, quote conflicts, idempotent checkout/retry, snapshots and order ownership/pagination', flush=True)

            # Both customers quote the last unit before either purchases it.
            db.execute('UPDATE product_variants SET stock=1,price=0 WHERE id=%s', (variant,))
            for token in tokens:
                call('PUT', path, token, json={'quantity': 1})
            last = {**payload, 'items': [{'variant_id': variant, 'quantity': 1, 'price_cents': 0}]}
            def compete(token):
                return requests.post(api + '/api/checkout', json=last, headers={'Origin': origin, 'Authorization': 'Bearer ' + token, 'Idempotency-Key': 'last-' + suffix}, timeout=30)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(compete, tokens))
            assert sorted(result.status_code for result in results) == [201, 409], [r.text for r in results]
            assert db.execute('SELECT stock FROM product_variants WHERE id=%s', (variant,)).fetchone()[0] == 0
            print('PASS: simultaneous last-unit checkout permits one buyer; free item total is exact', flush=True)
            for route in ('/cart', '/checkout', '/account/orders', '/account/orders/' + order['id'], '/product/phase2-' + suffix):
                response = requests.get(web + route, timeout=30)
                assert response.status_code == 200, (route, response.status_code)
            print('PASS: cart/checkout/order/detail storefront routes', flush=True)
        finally:
            # Only records created by this run are removed; seeded stock is untouched.
            if user_ids:
                db.execute('DELETE FROM orders WHERE user_id=ANY(%s)', (user_ids,))
                db.execute('DELETE FROM users WHERE id=ANY(%s)', (user_ids,))
            if product_ids:
                db.execute('DELETE FROM products WHERE id=ANY(%s)', (product_ids,))
    print('PASS: Phase 2 HTTP verification; temporary fixtures removed', flush=True)


if __name__ == '__main__':
    main()
