"""Build a FashionGen serving index from cached embeddings with provenance checks.

Verifies every CSV/product-id mapping and freshly encodes sampled image/text pairs
before publishing a complete, backed-up replacement of vector_db.
"""
import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

import faiss
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoTokenizer

from ai_worker.datasets.fashiongen import clip_transform
from ai_worker.models.mrl import MRL_CrossModal_Model
from ai_worker.paths import WORKER_ROOT


def sha256(path):
    with open(path, 'rb') as source:
        digest=hashlib.sha256()
        for chunk in iter(lambda: source.read(1024*1024), b''):
            digest.update(chunk)
        return digest.hexdigest()


def build(args):
    torch.set_num_threads(args.threads)
    csv_path, images = args.csv.resolve(), args.images.resolve()
    checkpoint, output = args.checkpoint.resolve(), args.output.resolve()
    rows = list(csv.DictReader(csv_path.open(encoding='utf-8-sig')))
    paths = [Path(row['image_path'].replace('\\', '/')).name for row in rows]
    product_ids = [row['product_id'].strip().strip('[]').strip() for row in rows]
    captions = [row['text'] for row in rows]
    cached_ids = [str(p).strip().strip('[]').strip() for p in json.loads(args.product_ids.read_text())]
    if not rows or cached_ids != product_ids:
        raise ValueError('CSV and embedding product IDs/order differ')
    if len(set(paths)) != len(paths) or any(not (images / p).is_file() for p in paths):
        raise ValueError('Duplicate image paths or missing dataset images')
    img = torch.load(args.image_features, map_location='cpu', weights_only=True).float()
    txt = torch.load(args.text_features, map_location='cpu', weights_only=True).float()
    if img.shape != (len(rows),512) or txt.shape != img.shape:
        raise ValueError('Embedding shape does not match CSV')
    if not torch.isfinite(img).all() or not torch.isfinite(txt).all() or (img.norm(dim=1)==0).any() or (txt.norm(dim=1)==0).any():
        raise ValueError('Invalid embedding vectors')

    model_name = 'openai/clip-vit-base-patch16'
    model = MRL_CrossModal_Model(model_name)
    raw = torch.load(checkpoint, map_location='cpu', weights_only=True)
    model.load_state_dict(raw.get('model_state_dict', raw)); model.eval()
    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
    sample_rows = sorted(set([0,len(rows)//4,len(rows)//2,3*len(rows)//4,len(rows)-1]))
    samples=[]
    with torch.inference_mode():
        for i in sample_rows:
            with Image.open(images/paths[i]) as image:
                x = clip_transform()(image.convert('RGB')).unsqueeze(0)
            tokens = tokenizer(captions[i],padding='max_length',truncation=True,max_length=77,return_tensors='pt')
            image_cos = F.cosine_similarity(model.extract_image_features(x),img[i:i+1]).item()
            text_cos = F.cosine_similarity(model.extract_text_features(tokens['input_ids'],tokens['attention_mask']),txt[i:i+1]).item()
            if min(image_cos,text_cos) < .99999:
                raise ValueError(f'Cache/checkpoint mismatch at row {i}: {image_cos}, {text_cos}')
            samples.append({'row':i,'image_cosine':image_cos,'text_cosine':text_cos})
    print('PASS: all row mappings and five freshly encoded image/text samples',flush=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    staging = output.with_name(output.name+'.building-'+uuid.uuid4().hex[:8])
    staging.mkdir(parents=True)
    backup=None
    try:
        for name, features in [('image_embeddings.index',img),('text_embeddings.index',txt)]:
            vectors=np.ascontiguousarray(F.normalize(features,dim=-1).numpy(),dtype=np.float32)
            index=faiss.IndexFlatIP(512); index.add(vectors)
            faiss.write_index(index,str(staging/name))
        def write(name, value):
            (staging/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        write('image_paths.json',paths);write('captions.json',captions);write('product_ids.json',product_ids)
        write('products.json',[{'vector_id':i,'product_id':product_ids[i],'image_path':paths[i],'caption':captions[i],'category':r.get('category',''),'subcategory':r.get('subcategory',''),'brand':r.get('brand','')} for i,r in enumerate(rows)])
        meta={
            'index_version': 'fashiongen-val-'+timestamp,
            'checkpoint_path': os.path.relpath(checkpoint,WORKER_ROOT).replace('\\','/'),
            'checkpoint_sha256':sha256(checkpoint),
            'clip_model_name':model_name,'tokenizer_name':model_name,
            'image_size':224,'normalize_mean':[.48145466,.4578275,.40821073],
            'normalize_std':[.26862954,.26130258,.27577711],
            'full_dim':512,'supported_dims':[16,32,64,128,256,512],
            'num_vectors':len(rows),'num_products':len(set(product_ids)),
            'dataset_name':'FashionGen','dataset_split':'val','image_root':str(images),
            'source_csv':str(csv_path),'source_csv_sha256':sha256(csv_path),
            'source_image_features_sha256':sha256(args.image_features),
            'source_text_features_sha256':sha256(args.text_features),
            'image_index_sha256':sha256(staging/'image_embeddings.index'),
            'text_index_sha256':sha256(staging/'text_embeddings.index'),
            'image_paths_sha256':sha256(staging/'image_paths.json'),
            'captions_sha256':sha256(staging/'captions.json'),
            'verification_samples':samples,'built_at':datetime.now(timezone.utc).isoformat(),
        }
        write('index_meta.json',meta)
        if output.exists():
            backup=output.with_name(output.name+'.backup-'+timestamp)
            shutil.copytree(output, backup)
        output.mkdir(parents=True, exist_ok=True)
        # Offline activation: replace artifacts first and metadata last. Workers
        # must be stopped; hash validation rejects incomplete publication.
        try:
            for item in sorted(staging.iterdir(), key=lambda p: p.name == 'index_meta.json'):
                os.replace(item, output/item.name)
            staging.rmdir()
        except BaseException:
            if backup:
                for item in backup.iterdir():
                    shutil.copy2(item, output/item.name)
            raise
    except BaseException:
        if staging.exists():
            if staging.resolve().parent != output.parent or not staging.name.startswith(output.name+".building-"):
                raise RuntimeError("Refusing cleanup outside the index staging directory")
            shutil.rmtree(staging)
        raise
    print(json.dumps({'active':str(output),'backup':str(backup),'vectors':len(rows),'products':len(set(product_ids)),'checkpoint':str(checkpoint)},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path,required=True)
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,default=WORKER_ROOT/'checkpoints/mrl_fashiongen_latest.pt')
    parser.add_argument('--image-features',type=Path,default=WORKER_ROOT/'embeddings/fgen_val_mrl_image_features.pt')
    parser.add_argument('--text-features',type=Path,default=WORKER_ROOT/'embeddings/fgen_val_mrl_text_features.pt')
    parser.add_argument('--product-ids',type=Path,default=WORKER_ROOT/'embeddings/fgen_val_product_ids.json')
    parser.add_argument('--output',type=Path,default=WORKER_ROOT/'vector_db')
    parser.add_argument('--threads',type=int,default=1)
    build(parser.parse_args())
