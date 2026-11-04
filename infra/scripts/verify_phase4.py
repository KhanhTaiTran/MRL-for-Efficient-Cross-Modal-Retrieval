"""Exercise Phase 4 using disposable local users/product/orders; cleanup in finally."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import bcrypt
import psycopg
import requests


def main():
    api=os.environ.get('API_URL','http://localhost:18080')
    web=os.environ.get('FRONTEND_URL','http://localhost:13000')
    origin=os.environ.get('WEB_ORIGIN','http://localhost:13000')
    database=os.environ.get('DATABASE_URL','postgresql://aurafind:aurafind_dev@localhost:15432/aurafind')
    suffix=uuid4().hex[:12];users=[];pid=None
    def call(method,path,token='',status=200,**kwargs):
        headers={'Origin':origin}
        if token:headers['Authorization']='Bearer '+token
        headers.update(kwargs.pop('headers',{}))
        response=requests.request(method,api+'/api'+path,headers=headers,timeout=30,**kwargs)
        assert response.status_code==status,(method,path,response.status_code,response.text)
        return response.json() if response.content else {}
    with psycopg.connect(database,autocommit=True,connect_timeout=10) as db:
        try:
            password='Phase-four-test-password-2026';hashed=bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode();tokens=[]
            for n,role in enumerate(('customer','customer','admin')):
                email=f'phase4-{suffix}-{n}@aurafind.test'
                users.append(db.execute("INSERT INTO users(email,name,password_hash,role,is_verified) VALUES(%s,'Test Customer',%s,%s,true) RETURNING id",(email,hashed,role)).fetchone()[0])
                tokens.append(call('POST','/auth/login',json={'email':email,'password':password})['access_token'])
            a,b,admin=tokens;handle='phase4-'+suffix
            pid=db.execute("INSERT INTO products(handle,name,base_price) VALUES(%s,'Review test product',1.25) RETURNING id",(handle,)).fetchone()[0]
            vid=str(db.execute("INSERT INTO product_variants(product_id,price,stock) VALUES(%s,1.25,20) RETURNING id",(pid,)).fetchone()[0])
            base='/products/'+handle
            call('GET','/wishlist',status=401)
            for _ in range(2):call('PUT','/wishlist/'+str(pid),a)
            assert call('GET','/wishlist',a)['pagination']['total']==1
            assert call('GET','/wishlist',b)['data']==[]
            call('DELETE','/wishlist/'+str(pid),b)
            assert call('GET','/wishlist',a)['pagination']['total']==1
            call('PUT','/wishlist/'+str(pid),a,status=403,headers={'Origin':'https://untrusted.example'})
            call('GET','/wishlist?page=0',a,status=400)
            assert not call('GET',base+'/review-eligibility',a)['eligible']
            call('PUT',base+'/review',a,status=403,json={'rating':5,'comment':'No purchase'})
            call('PUT',base+'/review',a,status=400,json={'rating':6,'comment':''})
            call('PUT',base+'/review',a,status=400,json={'rating':5,'comment':'x'*4001})
            call('PUT',base+'/review',a,status=400,json={'rating':5,'comment':'','is_verified_purchase':True})
            call('GET','/admin/reviews',a,status=403)
            call('PUT','/cart/items/'+vid,a,json={'quantity':1})
            payload={'currency':'USD','items':[{'variant_id':vid,'quantity':1,'price_cents':125}],'shipping_address':{'name':'Test','line1':'Street','line2':'','city':'City','region':'','postal_code':'123','country':'US'}}
            order=call('POST','/checkout',a,status=201,json=payload,headers={'Idempotency-Key':'phase4-'+suffix})['data']
            assert call('GET',base+'/review-eligibility',a)['eligible']
            assert not call('GET',base+'/review-eligibility',b)['eligible']
            db.execute("UPDATE orders SET payment_status='refunded' WHERE id=%s",(order['id'],))
            call('PUT',base+'/review',a,status=403,json={'rating':5,'comment':'Refunded'})
            db.execute("UPDATE orders SET payment_status='paid',order_status='cancelled' WHERE id=%s",(order['id'],))
            call('PUT',base+'/review',a,status=403,json={'rating':5,'comment':'Cancelled'})
            db.execute("UPDATE orders SET order_status='confirmed' WHERE id=%s",(order['id'],))
            with ThreadPoolExecutor(max_workers=4) as pool:
                values=list(pool.map(lambda _:call('PUT',base+'/review',a,json={'rating':4,'comment':'Verified review'}),range(4)))
            review=values[0]['review'];rid=review['id']
            assert review['is_verified_purchase'] and all(value['review']['id']==rid for value in values)
            assert call('GET',base+'/reviews')['pagination']['total']==1
            detail=call('GET',base)['data'];assert detail['review_count']==1 and detail['rating_average']==4
            call('PATCH','/admin/reviews/'+rid,b,status=403,json={'is_hidden':True})
            call('PATCH','/admin/reviews/'+rid,admin,status=400,json={})
            call('PATCH','/admin/reviews/'+rid,admin,json={'is_hidden':True})
            call('PUT',base+'/review',a,json={'rating':5,'comment':'Edited while hidden'})
            assert call('GET',base+'/review-eligibility',a)['review']['is_hidden']
            assert call('GET',base+'/reviews')['data']==[]
            detail=call('GET',base)['data'];assert detail['review_count']==0 and detail['rating_average'] is None
            assert any(v['id']==rid and v['is_hidden'] for v in call('GET','/admin/reviews',admin)['data'])
            call('PATCH','/admin/reviews/'+rid,admin,json={'is_hidden':False})
            detail=call('GET',base)['data'];assert detail['rating_average']==5 and detail['review_count']==1
            db.execute('UPDATE products SET is_active=false WHERE id=%s',(pid,))
            assert call('GET','/wishlist',a)['data']==[]
            call('GET',base+'/reviews',status=404)
            call('PUT','/wishlist/'+str(pid),a,status=404)
            call('DELETE','/wishlist/'+str(pid),a);call('DELETE','/wishlist/'+str(pid),a)
            for route in ('/wishlist','/admin/reviews'):
                assert requests.get(web+route,timeout=30).status_code==200
            print('PASS: purchase eligibility, refunded/cancelled/foreign orders, concurrent review upsert, input/Origin/role validation, hidden-review edits, visible aggregates, wishlist privacy/idempotency/pagination/archive and frontend routes',flush=True)
        finally:
            if pid:db.execute('DELETE FROM reviews WHERE product_id=%s',(pid,))
            if users:
                db.execute('DELETE FROM orders WHERE user_id=ANY(%s)',(users,))
                db.execute('DELETE FROM users WHERE id=ANY(%s)',(users,))
            if pid:db.execute('DELETE FROM products WHERE id=%s',(pid,))
    print('PASS: Phase 4 fixtures removed',flush=True)


if __name__=='__main__':main()
