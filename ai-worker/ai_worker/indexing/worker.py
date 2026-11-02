"""Consume PostgreSQL index jobs; publish complete versioned catalog snapshots.

The session advisory lock permits one consumer. Search never traverses this queue.
"""
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import shutil
import time
from datetime import datetime, timezone
from uuid import uuid4

import faiss
import numpy as np
from PIL import Image
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from minio import Minio
from minio.error import S3Error
import torch
from torchvision import transforms
from transformers import AutoTokenizer

from ai_worker.models.mrl import MRL_CrossModal_Model

LOCK_ID = 19860513
ROOT = Path(os.environ.get('VECTOR_DB_DIR', '/data/vector_db')).resolve()
IMAGES = Path(os.environ.get('IMG_BASE_DIR', '/data/images')).resolve()
ARTIFACTS = [('image_embeddings.index', 'image_index_sha256'), ('text_embeddings.index', 'text_index_sha256'), ('image_paths.json', 'image_paths_sha256'), ('captions.json', 'captions_sha256'), ('product_ids.json', 'product_ids_sha256')]


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def managed(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise RuntimeError('Index path is outside the managed root')
    return path


def preserve_source(db, source):
    """Archive legacy seed artifacts before publishing the first managed rebuild."""
    folder = managed(source['index_path'])
    meta = json.loads((folder / 'index_meta.json').read_text())
    if folder != ROOT:
        return folder, meta
    destination = ROOT / 'versions' / str(source['id'])
    if not destination.exists():
        building = ROOT / 'versions' / (str(source['id']) + '.archiving')
        building.mkdir(parents=True, exist_ok=True)
        for filename, field in ARTIFACTS:
            if meta.get(field) and digest(folder / filename) != meta[field]:
                raise RuntimeError(f'Source artifact hash mismatch: {filename}')
            shutil.copy2(folder / filename, building / filename)
        checkpoint = managed(meta['checkpoint_path'])
        shutil.copy2(checkpoint, building / 'checkpoint.pt')
        meta['checkpoint_path'] = str(destination / 'checkpoint.pt')
        for filename, field in ARTIFACTS:
            meta[field] = digest(building / filename)
        (building / 'index_meta.json').write_text(json.dumps(meta, indent=2))
        building.rename(destination)
    else:
        meta = json.loads((destination / 'index_meta.json').read_text())
    db.execute('UPDATE ai_index_versions SET index_path=%s,metadata=%s WHERE id=%s', (str(destination), Jsonb(meta), source['id']))
    return destination, meta


def rebuild(db, job):
    source = db.execute('SELECT id,index_path FROM ai_index_versions WHERE is_active').fetchone()
    if not source:
        raise RuntimeError('No validated source model/index is configured')
    _, source_meta = preserve_source(db, source)
    checkpoint = managed(source_meta['checkpoint_path'])
    if digest(checkpoint) != source_meta['checkpoint_sha256']:
        raise RuntimeError('Source checkpoint hash mismatch')
    # One SQL statement captures products, image identity and revisions consistently.
    rows = db.execute("""SELECT p.id product_id,p.name,COALESCE(p.description,'') description,
        COALESCE(p.brand,'') brand,p.search_revision,i.id image_id,i.object_key
        FROM products p JOIN product_images i ON i.product_id=p.id AND i.is_active
        WHERE p.is_active ORDER BY p.id,i.position,i.id LIMIT 20001"""
    ).fetchall()
    if not rows or len(rows) > 20000:
        raise RuntimeError('Rebuild requires 1–20,000 active catalog images')
    for pid, revision in {row['product_id']: row['search_revision'] for row in rows}.items():
        db.execute("UPDATE products SET search_status='indexing' WHERE id=%s AND search_revision=%s", (pid, revision))
    version = str(uuid4())
    destination = ROOT / 'versions' / version
    building = ROOT / 'versions' / (version + '.building')
    building.mkdir(parents=True)
    shutil.copy2(checkpoint, building / 'checkpoint.pt')
    model_name = source_meta['clip_model_name']
    model = MRL_CrossModal_Model(model_name)
    raw = torch.load(checkpoint, map_location='cpu', weights_only=True)
    model.load_state_dict(raw.get('model_state_dict', raw))
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    transform = transforms.Compose([transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC), transforms.CenterCrop(224), transforms.ToTensor(), transforms.Normalize(source_meta['normalize_mean'], source_meta['normalize_std'])])
    store = Minio(os.environ['MINIO_ENDPOINT'], access_key=os.environ['MINIO_ACCESS_KEY'], secret_key=os.environ['MINIO_SECRET_KEY'], secure=os.environ.get('MINIO_SECURE') == 'true')
    image_vectors, text_vectors, paths, captions, ids = [], [], [], [], []
    IMAGES.mkdir(parents=True, exist_ok=True)
    for row in rows:
        try:
            response = store.get_object('products', row['object_key'])
        except S3Error as exc:
            raise RuntimeError(f"Image for '{row['name']}' is unavailable in storage. Re-upload or remove the image, then rebuild.") from exc
        try:
            data = response.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                raise RuntimeError('Catalog image exceeds 10 MB')
        finally:
            response.close()
            response.release_conn()
        with Image.open(io.BytesIO(data)) as original:
            if original.width * original.height > 20000000:
                raise RuntimeError('Catalog image exceeds pixel limit')
            image = original.convert('RGB')
        filename = str(row['image_id']) + '.png'
        # Image IDs/object keys are immutable; retain old images for historical indexes.
        if not (IMAGES / filename).exists():
            temporary = IMAGES / (filename + '.tmp')
            image.save(temporary, format='PNG')
            temporary.replace(IMAGES / filename)
        caption = f"{row['brand']}. {row['name']}. {row['description']}"
        tokens = tokenizer(caption, padding='max_length', truncation=True, max_length=77, return_tensors='pt')
        with torch.inference_mode():
            image_vectors.append(model.extract_image_features(transform(image).unsqueeze(0)).numpy())
            text_vectors.append(model.extract_text_features(tokens['input_ids'], tokens['attention_mask']).numpy())
        paths.append(filename); captions.append(caption); ids.append(str(row['product_id']))
    for filename, vectors in [('image_embeddings.index', image_vectors), ('text_embeddings.index', text_vectors)]:
        vectors = np.ascontiguousarray(np.vstack(vectors), dtype='float32')
        if vectors.shape != (len(rows), 512) or not np.isfinite(vectors).all():
            raise RuntimeError('Invalid extracted vectors')
        faiss.normalize_L2(vectors)
        index = faiss.IndexFlatIP(512); index.add(vectors)
        faiss.write_index(index, str(building / filename))
    for filename, values in [('image_paths.json', paths), ('captions.json', captions), ('product_ids.json', ids)]:
        (building / filename).write_text(json.dumps(values))
    meta = dict(source_meta)
    meta.update(index_version=version, checkpoint_path=str(destination / 'checkpoint.pt'), num_vectors=len(rows), num_products=len(set(ids)), dataset_name='AuraFind SQL catalog', dataset_split='catalog', image_root=str(IMAGES), built_at=datetime.now(timezone.utc).isoformat())
    for filename, field in ARTIFACTS:
        meta[field] = digest(building / filename)
    (building / 'index_meta.json').write_text(json.dumps(meta, indent=2))
    building.rename(destination)
    # Files exist before SQL publication. Existing versions/mappings are never removed.
    with db.transaction():
        current = db.execute('SELECT status FROM ai_index_jobs WHERE id=%s FOR UPDATE', (job['id'],)).fetchone()
        if not current or current['status'] != 'running':
            raise RuntimeError('Job no longer owns publication')
        db.execute('UPDATE ai_index_versions SET is_active=false WHERE is_active')
        db.execute('INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,num_vectors,supported_dims,index_path,is_active,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,true,%s)', (version, 'catalog-' + version, 'checkpoint.pt', meta['checkpoint_sha256'], len(rows), meta['supported_dims'], str(destination), Jsonb(meta)))
        for n, row in enumerate(rows):
            db.execute('INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id) VALUES(%s,%s,%s)', (version, n, row['image_id']))
        revisions = {row['product_id']: row['search_revision'] for row in rows}
        for pid, revision in revisions.items():
            db.execute("UPDATE products SET search_status='ready' WHERE id=%s AND search_revision=%s", (pid, revision))
        db.execute("UPDATE ai_index_jobs SET status='done',index_version_id=%s,finished_at=now() WHERE id=%s", (version, job['id']))
    return version


def main():
    logging.basicConfig(level=logging.INFO)
    torch.set_num_threads(1)
    while True:
        try:
            with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True, row_factory=dict_row, connect_timeout=5) as db:
                if not db.execute('SELECT pg_try_advisory_lock(%s) acquired', (LOCK_ID,)).fetchone()['acquired']:
                    time.sleep(3)
                    continue
                # Owning the singleton lock proves the previous consumer is gone.
                db.execute("UPDATE ai_index_jobs SET status='failed',error_msg='Index worker interrupted; submit a new rebuild.',finished_at=now() WHERE status='running'")
                db.execute("UPDATE products SET search_status='failed' WHERE search_status='indexing'")
                while True:
                    job = db.execute("UPDATE ai_index_jobs SET status='running',started_at=now(),error_msg=NULL WHERE id=(SELECT id FROM ai_index_jobs WHERE status='pending' ORDER BY created_at LIMIT 1) RETURNING id").fetchone()
                    if not job:
                        time.sleep(2)
                        continue
                    try:
                        version = rebuild(db, job)
                        logging.info('Completed job %s: %s', job['id'], version)
                    except Exception as exc:
                        logging.exception('Index job %s failed; prior version retained', job['id'])
                        db.execute("UPDATE ai_index_jobs SET status='failed',error_msg=%s,finished_at=now() WHERE id=%s AND status='running'", (str(exc)[:1000], job['id']))
                        db.execute("UPDATE products SET search_status='failed' WHERE search_status='indexing'")
        except Exception:
            logging.exception('Index consumer connection failed; reconnecting')
            time.sleep(3)


if __name__ == '__main__':
    main()
