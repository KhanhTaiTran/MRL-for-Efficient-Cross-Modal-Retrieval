"""Exercise Phase 1 through HTTP, PostgreSQL and the local MailHog inbox.

Uses a unique test account and removes only that account after the run. No real
email delivery is involved when using the development Compose stack.
"""
import os
import re
import time
from uuid import uuid4

import psycopg
import requests


def main():
    api = os.environ.get('API_URL', 'http://localhost:18080')
    web = os.environ.get('FRONTEND_URL', 'http://localhost:13000')
    inbox = os.environ.get('MAILHOG_URL', 'http://localhost:18025')
    origin = os.environ.get('WEB_ORIGIN', 'http://localhost:13000')
    database = os.environ.get('DATABASE_URL', 'postgresql://aurafind:aurafind_dev@localhost:15432/aurafind')
    email = f'phase1-{uuid4().hex[:12]}@aurafind.test'
    password = 'Phase-one-test-password-2026'
    new_password = 'Replacement-password-2026'
    browser = requests.Session()
    browser.headers['Origin'] = origin

    def post(path, body=None, status=200, client=browser):
        result = client.post(api + '/api/auth/' + path, json=body or {}, timeout=20)
        assert result.status_code == status, (path, result.status_code, result.text)
        return result

    def code_for(subject):
        for _ in range(10):
            result = requests.get(inbox + '/api/v2/search', params={'kind': 'to', 'query': email, 'limit': 50}, timeout=10)
            result.raise_for_status()
            for message in result.json().get('items', []):
                if subject in ''.join(message['Content']['Headers'].get('Subject', [])):
                    found = re.search(r'code is (\d{6})', message['Content']['Body'])
                    if found:
                        return found.group(1)
            time.sleep(.2)
        raise AssertionError('Verification email not found in local MailHog')

    with psycopg.connect(database, autocommit=True, connect_timeout=10) as db:
        try:
            listed = browser.get(api + '/api/products?limit=3&sort=price_asc', timeout=10)
            listed.raise_for_status()
            catalog = listed.json()
            assert len(catalog['data']) == 3 and catalog['pagination']['total'] >= 10
            assert [p['price'] for p in catalog['data']] == sorted(p['price'] for p in catalog['data'])
            product = catalog['data'][0]
            detail = browser.get(api + '/api/products/' + product['handle'], timeout=10).json()['data']
            assert detail['variants'] and detail['images'] and detail['review_count'] == 0 and detail['rating_average'] is None
            assert browser.get(api + '/api/products/does-not-exist-' + uuid4().hex, timeout=10).status_code == 404
            assert browser.get(api + '/api/products?min_price=NaN', timeout=10).status_code == 400
            assert browser.get(api + '/api/products?page=0', timeout=10).status_code == 400
            assert browser.get(api + '/api/products?sort=sql-injection', timeout=10).status_code == 400
            filtered = browser.get(api + '/api/products', params={'category': product['category'], 'min_price': product['price'], 'max_price': product['price']}, timeout=10).json()['data']
            assert filtered and all(p['category'] == product['category'] and p['price'] == product['price'] for p in filtered)
            print('PASS: catalog pagination, sorting, filters, details, variants and input validation', flush=True)

            post('register', {'name': 'Phase One Tester', 'email': email.upper(), 'password': password}, 201)
            verify_code = code_for('Verify your AuraFind email')
            record = db.execute('SELECT id,password_hash,is_verified FROM users WHERE email=%s', (email,)).fetchone()
            assert record and record[1] != password and record[1].startswith('$2') and record[2] is False
            otp_hash = db.execute('SELECT code_hash FROM otp_tokens WHERE user_id=%s ORDER BY created_at DESC LIMIT 1', (record[0],)).fetchone()[0]
            assert otp_hash != verify_code and len(otp_hash) == 64
            post('login', {'email': email, 'password': password}, 403)
            post('verify-email', {'email': email, 'code': 'wrong!'}, 400)
            assert db.execute('SELECT attempts FROM otp_tokens WHERE user_id=%s ORDER BY created_at DESC LIMIT 1', (record[0],)).fetchone()[0] == 1
            post('resend-verification', {'email': email}, 429)
            # Only this disposable account's OTP is altered to simulate time/lockout.
            db.execute("UPDATE otp_tokens SET expires_at=now()-interval '1 second' WHERE user_id=%s", (record[0],))
            post('verify-email', {'email': email, 'code': verify_code}, 400)
            db.execute("UPDATE otp_tokens SET expires_at=now()+interval '10 minutes' WHERE user_id=%s", (record[0],))
            for _ in range(4):
                post('verify-email', {'email': email, 'code': 'wrong!'}, 400)
            post('verify-email', {'email': email, 'code': verify_code}, 400)
            assert db.execute('SELECT attempts FROM otp_tokens WHERE user_id=%s ORDER BY created_at DESC LIMIT 1', (record[0],)).fetchone()[0] == 5
            db.execute('UPDATE otp_tokens SET attempts=0 WHERE user_id=%s', (record[0],))
            verified = post('verify-email', {'email': email, 'code': verify_code})
            session = verified.json()
            assert session['user']['is_verified'] and session['user']['role'] == 'customer'
            cookie = verified.headers.get('Set-Cookie', '')
            assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie and 'Path=/api/auth' in cookie
            post('verify-email', {'email': email, 'code': verify_code}, 400)
            access = session['access_token']
            auth = {'Authorization': 'Bearer ' + access}
            assert browser.get(api + '/api/auth/me', headers=auth, timeout=10).json()['user']['email'] == email
            updated = browser.patch(api + '/api/auth/me', json={'name': 'Updated Name', 'role': 'admin'}, headers=auth, timeout=10)
            assert updated.status_code == 200 and updated.json()['user']['name'] == 'Updated Name' and updated.json()['user']['role'] == 'customer'
            assert browser.get(api + '/api/auth/me', headers={'Authorization': 'Bearer ' + access + 'tampered'}, timeout=10).status_code == 401
            print('PASS: registration, hashed OTP/password, email gate, OTP expiry/lockout/replay, profile and JWT rejection', flush=True)

            # Concurrent access requests do not rotate the refresh token.
            old_cookie = browser.cookies.get('aurafind_refresh')
            rotated = post('refresh').json()
            assert browser.cookies.get('aurafind_refresh') != old_cookie
            assert browser.get(api + '/api/auth/me', headers={'Authorization': 'Bearer ' + rotated['access_token']}, timeout=10).status_code == 200
            attacker = requests.Session();attacker.headers['Origin'] = origin
            attacker.cookies.set('aurafind_refresh', old_cookie)
            post('refresh', status=401, client=attacker)
            assert browser.get(api + '/api/auth/me', headers={'Authorization': 'Bearer ' + rotated['access_token']}, timeout=10).status_code == 401
            post('refresh', status=401)
            login = post('login', {'email': email, 'password': password}).json()
            assert post('refresh', client=browser).status_code == 200
            rejected = browser.post(api + '/api/auth/refresh', headers={'Origin': 'http://untrusted.example'}, timeout=10)
            assert rejected.status_code == 403
            post('logout')
            assert not browser.cookies.get('aurafind_refresh')
            assert browser.get(api + '/api/auth/me', headers={'Authorization': 'Bearer ' + login['access_token']}, timeout=10).status_code == 401
            print('PASS: refresh rotation, reuse revocation, Origin protection and logout invalidation', flush=True)

            old_session = post('login', {'email': email, 'password': password}).json()
            post('forgot-password', {'email': email})
            post('forgot-password', {'email': 'unknown-' + uuid4().hex + '@aurafind.test'})
            reset_code = code_for('Reset your AuraFind password')
            post('forgot-password', {'email': email}, 429)
            post('reset-password', {'email': email, 'code': reset_code, 'password': new_password})
            post('reset-password', {'email': email, 'code': reset_code, 'password': new_password}, 400)
            post('login', {'email': email, 'password': password}, 401)
            assert browser.get(api + '/api/auth/me', headers={'Authorization': 'Bearer ' + old_session['access_token']}, timeout=10).status_code == 401
            post('login', {'email': email, 'password': new_password})
            post('logout')
            print('PASS: password reset, OTP cooldown/replay rejection and old-session revocation', flush=True)

            result = browser.post(api + '/api/search/text', data={'query': 'red cotton T-shirt', 'mrl_dimension': 512, 'search_mode': 'direct'}, timeout=30)
            result.raise_for_status();payload = result.json()
            assert payload['data']
            seen = set()
            scores = []
            for item in payload['data']:
                mapped = db.execute('SELECT p.id::text,p.handle,p.base_price::float8,p.currency,pi.object_key FROM index_vector_mappings m JOIN product_images pi ON pi.id=m.product_image_id JOIN products p ON p.id=pi.product_id WHERE m.index_version_id=%s AND m.vector_id=%s', (payload['index_version'], item['vector_id'])).fetchone()
                assert mapped and item['catalog_product_id'] == mapped[0] and item['handle'] == mapped[1] and item['price'] == mapped[2] and item['currency'] == mapped[3]
                assert item['catalog_product_id'] not in seen and item['image_url'].endswith(mapped[4])
                seen.add(item['catalog_product_id']);scores.append(item['similarity_score'])
            assert scores == sorted(scores, reverse=True)
            print('PASS: search enrichment uses version/vector mappings, SQL prices and preserved ranking', flush=True)

            for path in ['/', '/login', '/register', '/verify-email', '/forgot-password', '/reset-password', '/account', '/search', '/product/' + product['handle'], '/sitemap.xml']:
                response = browser.get(web + path, timeout=30)
                assert response.status_code == 200, (path, response.status_code)
            assert browser.get(web + '/product/does-not-exist-' + uuid4().hex, timeout=30).status_code == 404
            assert origin + '/product/' in browser.get(web + '/sitemap.xml', timeout=30).text
            print('PASS: storefront/auth/catalog routes, product 404 and Shopify-free sitemap', flush=True)
        finally:
            db.execute('DELETE FROM users WHERE email=%s', (email,))
            browser.close()
    print('PASS: Phase 1 HTTP integration completed; temporary test account removed')


if __name__ == '__main__':
    main()
