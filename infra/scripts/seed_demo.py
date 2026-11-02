"""Idempotently provision the local demo catalog, storage and real CLIP index.

Demo illustrations and prices are fictional fixtures, not FashionGen records.
Uses public pretrained CLIP (512D only); never claims fine-tuned MRL quality.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

source_root = Path(__file__).resolve().parents[2]
worker_root = source_root / 'ai-worker' if (source_root / 'ai-worker' / 'ai_worker').is_dir() else source_root
sys.path.insert(0, str(worker_root))
import bcrypt
import faiss
from minio import Minio
import numpy as np
from PIL import Image, ImageDraw
import psycopg
from psycopg.types.json import Jsonb
import torch
from transformers import AutoTokenizer
from torchvision import transforms
from ai_worker.models.mrl import MRL_CrossModal_Model

FIXTURES=[
 ('red-cotton-tshirt','Red cotton T-shirt','tops','red',29,'shirt'),
 ('blue-denim-jeans','Blue denim jeans','bottoms','blue',59,'pants'),
 ('green-summer-dress','Green summer dress','dresses','green',79,'dress'),
 ('black-tailored-trousers','Black tailored trousers','bottoms','black',69,'pants'),
 ('yellow-cotton-tshirt','Yellow cotton T-shirt','tops','yellow',25,'shirt'),
 ('purple-midi-dress','Purple midi dress','dresses','purple',89,'dress'),
 ('navy-casual-jacket','Navy casual jacket','outerwear','navy',99,'jacket'),
 ('white-linen-shirt','White linen shirt','tops','white',49,'jacket'),
 ('orange-summer-dress','Orange summer dress','dresses','orange',75,'dress'),
 ('gray-jogger-pants','Gray jogger pants','bottoms','gray',45,'pants'),
]

def uid(name):return uuid5(NAMESPACE_URL,'aurafind-demo:'+name)
def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def illustration(kind,color):
    image=Image.new('RGB',(320,400),'#f6f5f2');d=ImageDraw.Draw(image)
    outline='#555555'
    if kind=='pants':
        d.polygon([(100,50),(220,50),(238,350),(183,350),(160,150),(137,350),(82,350)],fill=color,outline=outline,width=3)
        d.line([(102,75),(218,75)],fill=outline,width=3)
    elif kind=='dress':
        d.polygon([(135,45),(185,45),(205,125),(245,345),(75,345),(115,125)],fill=color,outline=outline,width=3)
        d.line([(116,135),(204,135)],fill=outline,width=3)
    else:
        d.polygon([(110,70),(140,55),(180,55),(210,70),(260,130),(225,165),(210,140),(210,310),(110,310),(110,140),(95,165),(60,130)],fill=color,outline=outline,width=3)
        d.arc((138,45,182,95),0,180,fill=outline,width=3)
        if kind=='jacket':
            d.line([(160,80),(160,310)],fill=outline,width=3)
            for y in range(120,290,35):d.ellipse((166,y,171,y+5),fill=outline)
    d.text((14,376),'AuraFind demo illustration',fill='#666666')
    return image


def main():
    print("Preparing demo storage and catalog fixtures...",flush=True)
    torch.set_num_threads(1)
    out=Path(os.environ.get('VECTOR_DB_DIR','/data/vector_db'));out.mkdir(parents=True,exist_ok=True)
    existing=out/'index_meta.json'
    if existing.exists() and json.loads(existing.read_text()).get('dataset_split') != 'demo':
        raise RuntimeError('Refusing to overwrite a non-demo index; select a dedicated demo volume')
    images=Path(os.environ.get('IMG_BASE_DIR','/data/images'));images.mkdir(parents=True,exist_ok=True)
    storage=Minio(os.environ['MINIO_ENDPOINT'],access_key=os.environ['MINIO_ACCESS_KEY'],secret_key=os.environ['MINIO_SECRET_KEY'],secure=False)
    for bucket in ('products','reviews'):
        if not storage.bucket_exists(bucket):storage.make_bucket(bucket)
    storage.set_bucket_policy('products',json.dumps({'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'AWS':['*']},'Action':['s3:GetObject'],'Resource':['arn:aws:s3:::products/*']}]}))
    model_name=os.environ.get('DEMO_MODEL_NAME','openai/clip-vit-base-patch32')
    checkpoint=out/'demo_clip.pt'
    print(f"Loading public CLIP model: {model_name}",flush=True)
    model=MRL_CrossModal_Model(model_name);model.eval()
    if checkpoint.exists():model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True))
    else:torch.save(model.state_dict(),checkpoint)
    tokenizer=AutoTokenizer.from_pretrained(model_name)
    transform=transforms.Compose([transforms.Resize(224,interpolation=transforms.InterpolationMode.BICUBIC),transforms.CenterCrop(224),transforms.ToTensor(),transforms.Normalize((.48145466,.4578275,.40821073),(.26862954,.26130258,.27577711))])
    print("Encoding ten demo illustrations and captions...",flush=True)
    img_vectors=[];txt_vectors=[];paths=[];captions=[];ids=[];products=[]
    for slug,name,category,color,price,kind in FIXTURES:
        filename=slug+'.png';image=illustration(kind,color);image.save(images/filename)
        key=f'demo/{uid(slug)}/{filename}'
        storage.fput_object('products',key,str(images/filename),content_type='image/png')
        caption=f'AuraFind Demo. {name}. A demo illustration of clothing on a plain background.'
        tokens=tokenizer(caption,padding='max_length',truncation=True,max_length=77,return_tensors='pt')
        with torch.inference_mode():
            img_vectors.append(model.extract_image_features(transform(image).unsqueeze(0)).numpy())
            txt_vectors.append(model.extract_text_features(tokens['input_ids'],tokens['attention_mask']).numpy())
        paths.append(filename);captions.append(caption);ids.append(str(uid(slug)))
        products.append({'product_id':str(uid(slug)),'image_path':filename,'name':name,'brand':'AuraFind Demo','caption':caption,'price':price,'currency':'USD','object_key':key,'category':category,'color':color,'demo':True})
    for filename,vectors in [('image_embeddings.index',img_vectors),('text_embeddings.index',txt_vectors)]:
        vectors=np.ascontiguousarray(np.vstack(vectors),dtype='float32');faiss.normalize_L2(vectors)
        idx=faiss.IndexFlatIP(512);idx.add(vectors);faiss.write_index(idx,str(out/filename))
    for filename,data in [('image_paths.json',paths),('captions.json',captions),('product_ids.json',ids),('products.json',products)]:
        (out/filename).write_text(json.dumps(data,indent=2),encoding='utf-8')
    fixture_hash=hashlib.sha256(json.dumps(FIXTURES).encode()).hexdigest()
    version=str(uid('index:'+digest(checkpoint)+fixture_hash+digest(out/'image_embeddings.index')+digest(out/'text_embeddings.index')))
    meta={'index_version':version,'checkpoint_path':str(checkpoint),'checkpoint_sha256':digest(checkpoint),
          'clip_model_name':model_name,'tokenizer_name':model_name,'image_size':224,
          'normalize_mean':[.48145466,.4578275,.40821073],'normalize_std':[.26862954,.26130258,.27577711],
          'full_dim':512,'supported_dims':[512],'num_vectors':len(paths),'num_products':len(ids),
          'dataset_name':'AuraFind demo illustrations','dataset_split':'demo','image_root':str(images),
          'model_kind':'pretrained-clip-not-mrl','fixture_hash':fixture_hash,'built_at':datetime.now(timezone.utc).isoformat()}
    for filename,key in [('image_embeddings.index','image_index_sha256'),('text_embeddings.index','text_index_sha256'),('image_paths.json','image_paths_sha256'),('captions.json','captions_sha256')]:meta[key]=digest(out/filename)
    print('Publishing SQL catalog and versioned mappings...',flush=True)
    with psycopg.connect(os.environ['DATABASE_URL']) as db:
        # Serialize repeated seed processes and keep catalog/mapping publication transactional.
        db.execute('SELECT pg_advisory_xact_lock(19860512)')
        email=os.environ.get('DEMO_ADMIN_EMAIL','admin@aurafind.local')
        password=os.environ.get('DEMO_ADMIN_PASSWORD','aurafind-demo-password')
        db.execute("INSERT INTO users(id,email,name,password_hash,role,is_verified) VALUES(%s,%s,'Demo Admin',%s,'admin',true) ON CONFLICT(id) DO NOTHING",(uid('admin'),email,bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode()))
        db.execute('UPDATE ai_index_versions SET is_active=false WHERE is_active')
        db.execute('INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,num_vectors,supported_dims,index_path,is_active,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,true,%s) ON CONFLICT(id) DO UPDATE SET is_active=true,metadata=excluded.metadata',(version,'demo-'+version,checkpoint.name,meta['checkpoint_sha256'],len(paths),[512],str(out),Jsonb(meta)))
        for i,(fixture,p) in enumerate(zip(FIXTURES,products)):
            slug,name,category,color,price,kind=fixture;pid=uid(slug);vid=uid(slug+':M');iid=uid(slug+':image')
            db.execute("INSERT INTO products(id,handle,name,description,brand,category,base_price,is_featured,search_status,metadata) VALUES(%s,%s,%s,%s,'AuraFind Demo',%s,%s,true,'ready',%s) ON CONFLICT(id) DO UPDATE SET search_status='ready'",(pid,slug,name,p['caption'],category,price,Jsonb({'demo':True,'price_kind':'fictional fixture'})))
            db.execute("INSERT INTO product_variants(id,product_id,sku,size,color,price,stock) VALUES(%s,%s,%s,'M',%s,%s,25) ON CONFLICT(id) DO NOTHING",(vid,pid,'DEMO-'+slug,color,price))
            db.execute('UPDATE products SET default_variant_id=%s WHERE id=%s',(vid,pid))
            db.execute('INSERT INTO product_images(id,product_id,object_key,alt_text,is_primary) VALUES(%s,%s,%s,%s,true) ON CONFLICT(id) DO NOTHING',(iid,pid,p['object_key'],name))
            db.execute('INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(version,i,iid))
    # Metadata is published last; inference is ordered after this one-shot service.
    temporary=out/'index_meta.json.tmp';temporary.write_text(json.dumps(meta,indent=2),encoding='utf-8');temporary.replace(out/'index_meta.json')
    print(f'Seed complete: {len(paths)} demo products and vectors; index version {version}',flush=True)


if __name__=='__main__':main()
