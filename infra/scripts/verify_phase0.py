"""Verify Phase 0 schema/seed/storage/HTTP. Set endpoint env vars for non-default ports."""
import json
import os
import smtplib
from email.message import EmailMessage
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError
import psycopg
from minio import Minio


def fetch(url):
    with urlopen(url,timeout=30) as response:return response.status,response.read()


def main():
    database=os.environ.get('DATABASE_URL','postgresql://aurafind:aurafind_dev@localhost:5432/aurafind')
    api=os.environ.get('API_URL','http://localhost:8080')
    storage_url=os.environ.get('STORAGE_URL','http://localhost:9000')
    with psycopg.connect(database,autocommit=True) as db:
        tables={r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        expected={'users','otp_tokens','refresh_tokens','products','product_variants','product_images','ai_index_versions','ai_index_jobs','index_vector_mappings','orders','order_items','cart_items','reviews','review_media','wishlists'}
        assert expected<=tables,expected-tables
        migration, dirty = db.execute('SELECT version,dirty FROM schema_migrations').fetchone()
        assert migration >= 1 and not dirty, (migration, dirty)
        assert db.execute("SELECT count(*) FROM products WHERE metadata->>'demo'='true'").fetchone()[0]==10
        assert db.execute('SELECT count(*) FROM product_variants').fetchone()[0]==10
        version,count=db.execute('SELECT id,num_vectors FROM ai_index_versions WHERE is_active').fetchone()
        assert count==10
        assert db.execute('SELECT count(*) FROM index_vector_mappings WHERE index_version_id=%s',(version,)).fetchone()[0]==10
        try:
            with db.transaction():db.execute('UPDATE product_variants SET stock=-1')
        except psycopg.errors.CheckViolation:pass
        else:raise AssertionError('Negative stock accepted')
        pairs=db.execute('SELECT id,default_variant_id FROM products ORDER BY id LIMIT 2').fetchall()
        try:
            with db.transaction():db.execute('UPDATE products SET default_variant_id=%s WHERE id=%s',(pairs[1][1],pairs[0][0]))
        except psycopg.errors.ForeignKeyViolation:pass
        else:raise AssertionError('Cross-product default variant accepted')
        key=db.execute('SELECT object_key FROM product_images ORDER BY id LIMIT 1').fetchone()[0]
    assert fetch(storage_url+'/products/'+key)[0]==200
    store=Minio(storage_url.removeprefix('http://'),access_key=os.environ.get('MINIO_ACCESS_KEY','aurafind_dev'),secret_key=os.environ.get('MINIO_SECRET_KEY','aurafind_dev_secret'),secure=False)
    assert store.bucket_exists('products') and store.bucket_exists('reviews')
    assert len(list(store.list_objects('products',prefix='demo/',recursive=True)))==10
    try:fetch(storage_url+'/reviews?list-type=2')
    except HTTPError as e:assert e.code==403
    else:raise AssertionError('Reviews bucket is public')
    assert fetch(api+'/health/ready')[0]==200
    cfg=json.loads(fetch(api+'/api/search/config')[1]);assert cfg['num_vectors']==10 and cfg['supported_dims']==[512]
    assert str(version)==cfg['active_index_version']
    form=urlencode({'query':'red cotton T-shirt','mrl_dimension':512,'search_mode':'direct'}).encode()
    with urlopen(Request(api+'/api/search/text',data=form,headers={'Content-Type':'application/x-www-form-urlencoded'}),timeout=30) as response:
        result=json.load(response)
    assert result['status']=='success' and result['data'] and result['index_version']==str(version)
    image_name=result['data'][0]['product_id']
    image_data=fetch(api+'/images/'+image_name)[1]
    boundary='aurafind-phase0-verification'
    fields=b''
    for field,value in [('mrl_dimension','512'),('search_mode','direct')]:
        fields+=(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n').encode()
    fields+=(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{image_name}"\r\nContent-Type: image/png\r\n\r\n').encode()+image_data+f'\r\n--{boundary}--\r\n'.encode()
    with urlopen(Request(api+'/api/search/image',data=fields,headers={'Content-Type':f'multipart/form-data; boundary={boundary}'}),timeout=30) as response:
        similar=json.load(response)
    assert any(p['product_id']==image_name and p['similarity_score']>.999 for p in similar['data'])
    assert fetch(os.environ.get('FRONTEND_URL','http://localhost:3000'))[0]==200
    assert fetch(os.environ.get('STORAGE_CONSOLE_URL','http://localhost:9001'))[0]==200
    assert fetch(os.environ.get('MAILHOG_URL','http://localhost:8025'))[0]==200
    message=EmailMessage();message['From']='demo@aurafind.local';message['To']='test@aurafind.local';message['Subject']='Phase 0 SMTP verification';message.set_content('Local development mail check.')
    with smtplib.SMTP(os.environ.get('SMTP_HOST','localhost'),int(os.environ.get('SMTP_PORT','1025')),timeout=10) as smtp:smtp.send_message(message)
    print('PASS: 15 tables, migration, catalog/mapping consistency, stock/FK constraints, S3 objects/privacy, real text/image search, HTTP readiness/config/frontend and local SMTP')


if __name__=='__main__':main()
