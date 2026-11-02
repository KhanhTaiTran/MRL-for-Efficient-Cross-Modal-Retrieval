"""Local admin CRUD/storage, durable indexing and uninterrupted search verification.

Temporary catalog fixtures are archived before the successful rebuild, allowing
their complete cleanup without deleting historical mappings. Real demo versions
created by successful rebuilds are intentionally retained.
"""
import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import bcrypt
from minio import Minio
from PIL import Image
import psycopg
import requests


def main():
    api = os.environ.get('API_URL', 'http://localhost:18080')
    web = os.environ.get('FRONTEND_URL', 'http://localhost:13000')
    origin = os.environ.get('WEB_ORIGIN', 'http://localhost:13000')
    database = os.environ.get('DATABASE_URL', 'postgresql://aurafind:aurafind_dev@localhost:15432/aurafind')
    suffix = uuid4().hex[:12]
    password = 'Phase-three-test-password-2026'
    users, products, keys, jobs = [], [], [], []
    store = Minio(os.environ.get('MINIO_ENDPOINT', 'minio:9000'), access_key=os.environ.get('MINIO_ACCESS_KEY', 'aurafind_dev'), secret_key=os.environ.get('MINIO_SECRET_KEY', 'aurafind_dev_secret'), secure=False)

    def call(method, path, token='', status=200, **kwargs):
        headers = {'Origin': origin}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        headers.update(kwargs.pop('headers', {}))
        response = requests.request(method, api + '/api' + path, headers=headers, timeout=30, **kwargs)
        assert response.status_code == status, (method, path, response.status_code, response.text)
        return response.json() if response.content else {}

    def search():
        result = call('POST', '/search/text', data={'query': 'red cotton T-shirt', 'mrl_dimension': 512, 'search_mode': 'direct'})
        assert result['data'] and result['index_version']
        return result

    def wait_job(job, expected):
        for _ in range(240):
            row = db.execute('SELECT status,index_version_id,error_msg FROM ai_index_jobs WHERE id=%s', (job,)).fetchone()
            if row[0] in ('done', 'failed'):
                assert row[0] == expected, row
                return row
            time.sleep(1)
        raise TimeoutError('Index job did not finish')

    with psycopg.connect(database, autocommit=True, connect_timeout=10) as db:
        try:
            migration, dirty = db.execute('SELECT version,dirty FROM schema_migrations').fetchone()
            assert migration >= 3 and not dirty
            original = str(db.execute('SELECT id FROM ai_index_versions WHERE is_active').fetchone()[0])
            hashes = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            tokens = []
            for role in ('admin', 'customer'):
                email = f'phase3-{suffix}-{role}@aurafind.test'
                users.append(db.execute('INSERT INTO users(email,name,password_hash,role,is_verified) VALUES(%s,%s,%s,%s,true) RETURNING id', (email, 'Phase 3 verifier', hashes, role)).fetchone()[0])
                tokens.append(call('POST', '/auth/login', json={'email': email, 'password': password})['access_token'])
            admin, customer = tokens
            call('GET', '/admin/products', status=401)
            call('GET', '/admin/products', customer, status=403)
            call('POST', '/admin/index/jobs', customer, status=403)
            # Roles are read from SQL on every request, not trusted from old JWT claims.
            db.execute("UPDATE users SET role='customer' WHERE id=%s", (users[0],))
            call('GET', '/admin/products', admin, status=403)
            db.execute("UPDATE users SET role='admin' WHERE id=%s", (users[0],))
            body = dict(handle='phase3-' + suffix, name='Phase 3 fixture', description='Temporary verification product', brand='Test', category='test', price_cents=1234, is_active=True, is_featured=False, revision=0, default_variant_id='')
            product = call('POST', '/admin/products', admin, status=201, json=body)['data']
            pid = product['id']; products.append(pid)
            call('POST', '/admin/products', admin, status=409, json=body)
            variant = dict(sku='PHASE3-' + suffix, size='M', color='Red', price_cents=1234, stock=5, is_available=True)
            product = call('POST', f'/admin/products/{pid}/variants', admin, json=variant)['data']
            vid = product['variants'][0]['id']
            call('PUT', f'/admin/products/{pid}', admin, status=409, json={**body, 'revision': 1})
            call('PUT', f'/admin/products/{pid}/variants/{vid}', admin, status=409, json={**variant, 'stock': 9, 'expected_stock': 4})
            product = call('PUT', f'/admin/products/{pid}/variants/{vid}', admin, json={**variant, 'stock': 9, 'expected_stock': 5})['data']
            call('POST', f'/admin/products/{pid}/images', admin, status=400, files={'image': ('bad.svg', b'<svg/>', 'image/svg+xml')})
            image = io.BytesIO(); Image.new('RGB', (64, 64), 'red').save(image, format='PNG')
            product = call('POST', f'/admin/products/{pid}/images', admin, files={'image': ('test.png', image.getvalue(), 'image/png')}, data={'alt': 'Test image'})['data']
            uploaded = product['images'][0]; keys.append(uploaded['object_key'])
            stream = store.get_object('products', uploaded['object_key'])
            try:
                assert Image.open(io.BytesIO(stream.read())).size == (64, 64)
            finally:
                stream.close(); stream.release_conn()
            call('GET', '/products/' + body['handle'])
            print('PASS: live SQL admin-role enforcement, CRUD, revision/stock conflicts, PNG storage and invalid-image rejection', flush=True)

            # Inject one missing object into our own fixture to force a real failed job.
            missing = db.execute('INSERT INTO product_images(product_id,object_key) VALUES(%s,%s) RETURNING id', (pid, 'phase3-missing/' + suffix)).fetchone()[0]
            stop = threading.Event(); failures = []; seen = set()
            def continuous_search():
                while not stop.is_set():
                    try:
                        result = search(); seen.add(result['index_version'])
                        mapping_count = db_search.execute('SELECT count(*) FROM ai_index_versions WHERE id::text=%s', (result['index_version'],)).fetchone()[0]
                        assert mapping_count == 1
                    except Exception as error:
                        failures.append(str(error))
                    stop.wait(.25)
            with psycopg.connect(database, autocommit=True) as db_search:
                thread = threading.Thread(target=continuous_search, daemon=True); thread.start()
                try:
                    failed = call('POST', '/admin/index/jobs', admin, status=202)['data']['id']; jobs.append(failed)
                    wait_job(failed, 'failed')
                    assert str(db.execute('SELECT id FROM ai_index_versions WHERE is_active').fetchone()[0]) == original
                    assert search()['index_version'] == original
                    db.execute('DELETE FROM product_images WHERE id=%s', (missing,))
                    # No verification-only image is included in retained catalog snapshots.
                    call('DELETE', f'/admin/products/{pid}', admin)
                    call('GET', '/products/' + body['handle'], status=404)
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        queued = list(pool.map(lambda _: call('POST', '/admin/index/jobs', admin, status=202)['data']['id'], range(4)))
                    assert len(set(queued)) == 1, queued
                    job = queued[0]; jobs.append(job)
                    completed = wait_job(job, 'done'); version = str(completed[1])
                    for _ in range(60):
                        if search()['index_version'] == version:
                            break
                        time.sleep(1)
                    else:
                        raise AssertionError('Inference did not activate the published version')
                    assert db.execute('SELECT count(*) FROM index_vector_mappings WHERE index_version_id=%s', (original,)).fetchone()[0] > 0
                    assert len(call('GET', '/admin/index/versions', admin)['data']) >= 2
                finally:
                    stop.set(); thread.join(timeout=35)
            assert not failures, failures
            assert original in seen
            assert requests.get(web + '/admin', timeout=30).status_code == 200
            print('PASS: failed rebuild retains active index; concurrent queue requests deduplicate; successful rebuild hot-swaps while real searches continue; old mappings retained', flush=True)
        finally:
            # Jobs retain their audit identity but need not retain disposable test accounts.
            if jobs:
                db.execute('UPDATE ai_index_jobs SET triggered_by=NULL WHERE id=ANY(%s::uuid[])', (jobs,))
            if products:
                db.execute('DELETE FROM products WHERE id=ANY(%s::uuid[])', (products,))
            if users:
                db.execute('DELETE FROM users WHERE id=ANY(%s)', (users,))
            for key in keys:
                store.remove_object('products', key)
    print('PASS: Phase 3 verification completed; temporary users/products/objects removed, real index versions retained', flush=True)


if __name__ == '__main__':
    main()
