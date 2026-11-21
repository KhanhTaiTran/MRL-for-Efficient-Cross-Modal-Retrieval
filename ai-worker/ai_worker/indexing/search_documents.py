"""Build and validate versioned, product-level lexical search documents.

Rows passed to ``build_search_documents`` follow image-vector order.  An optional
product_ids sequence deliberately remaps source identities (for SQL imports).
The writer returns manifest fields; publishing index_meta.json remains the
caller's responsibility so the complete snapshot is activated together.
"""
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata


SCHEMA_VERSION = 1
NORMALIZER_VERSION = "english-snowball-v1"
ARTIFACT_NAME = "search_documents.json"
MANIFEST_FIELDS = ("search_documents_sha256", "hybrid_schema_version", "normalizer_version")
TEXT_FIELDS = ("name", "brand", "category", "subcategory", "description")


def _text(value):
    return unicodedata.normalize("NFKC", html.unescape(str(value or ""))).strip()


def _identity(value):
    return str(value).strip().strip("[]").strip() if value is not None else ""


def _tags(value):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        if value.lstrip().startswith("["):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("Search document tags must be strings") from exc
        else:
            value = value.split(",")
    if not isinstance(value, (list, tuple)) or any(not isinstance(tag, str) for tag in value):
        raise ValueError("Search document tags must be strings")
    return sorted({_text(tag) for tag in value if _text(tag)}, key=str.casefold)


def _name(row, description, brand):
    if row.get("name"):
        return _text(row["name"])
    # FashionGen has no standalone title. Match its catalog import's title rule.
    title = description.split(". ", 2)
    return (title[1] if len(title) > 1 and title[0] == brand else title[0])[:190]


def build_brand_aliases(documents):
    brands = sorted({doc["brand"] for doc in documents if doc["brand"]}, key=str.casefold)
    return {
        "adidas": [brand for brand in brands if re.match(r"^adidas\b", brand, re.IGNORECASE)],
        "diesel": [brand for brand in brands if brand.casefold() in ("diesel", "diesel black gold")],
    }


def build_search_documents(rows, product_ids=None):
    """Return one canonical document per product, with all its vector IDs."""
    rows = list(rows)
    if not rows:
        raise ValueError("Search documents require a nonempty vector mapping")
    if product_ids is not None:
        product_ids = list(product_ids)
        if len(product_ids) != len(rows):
            raise ValueError("Search document product ID count differs from rows")
    documents, remapping, reverse_remapping = {}, {}, {}
    for vector_id, row in enumerate(rows):
        source_id = _identity(row.get("product_id"))
        product_id = _identity(product_ids[vector_id]) if product_ids is not None else source_id
        if not product_id:
            raise ValueError("Search document product ID is empty")
        if source_id:
            if remapping.setdefault(source_id, product_id) != product_id or reverse_remapping.setdefault(product_id, source_id) != source_id:
                raise ValueError("Search document product ID remapping is inconsistent")
        description = _text(row.get("description", row.get("text", row.get("caption", ""))))
        brand = _text(row.get("brand"))
        doc = dict(product_id=product_id, name=_name(row, description, brand), brand=brand,
                   category=_text(row.get("category")), subcategory=_text(row.get("subcategory")),
                   tags=_tags(row.get("tags")), description=description, vector_ids=[])
        previous = documents.setdefault(product_id, doc)
        if any(previous[key] != doc[key] for key in (*TEXT_FIELDS, "tags")):
            raise ValueError(f"Search metadata differs between images of product {product_id}")
        previous["vector_ids"].append(vector_id)
    docs = list(documents.values())
    return dict(schema_version=SCHEMA_VERSION, normalizer_version=NORMALIZER_VERSION,
                brand_aliases=build_brand_aliases(docs), documents=docs)


def _validate_payload(payload, product_ids, num_vectors):
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported search document schema version")
    if payload.get("normalizer_version") != NORMALIZER_VERSION:
        raise ValueError("Unsupported search document normalizer version")
    if type(num_vectors) is not int or num_vectors <= 0 or len(product_ids) != num_vectors:
        raise ValueError("Search document vector count differs from index")
    docs = payload.get("documents")
    if not isinstance(docs, list) or not docs:
        raise ValueError("Search documents must be a nonempty list")
    seen_products, seen_vectors = set(), set()
    for doc in docs:
        if not isinstance(doc, dict):
            raise ValueError("Search document must be an object")
        pid = doc.get("product_id")
        if not isinstance(pid, str) or not pid.strip() or pid in seen_products:
            raise ValueError("Search document product IDs must be unique nonempty strings")
        seen_products.add(pid)
        if any(not isinstance(doc.get(key), str) for key in TEXT_FIELDS):
            raise ValueError("Search document metadata fields must be strings")
        if not isinstance(doc.get("tags"), list) or any(not isinstance(tag, str) for tag in doc["tags"]):
            raise ValueError("Search document tags must be strings")
        vector_ids = doc.get("vector_ids")
        if not isinstance(vector_ids, list) or not vector_ids:
            raise ValueError("Search document needs vector IDs")
        for vector_id in vector_ids:
            if type(vector_id) is not int or not 0 <= vector_id < num_vectors or vector_id in seen_vectors:
                raise ValueError("Search document vector IDs must have unique full coverage")
            if str(product_ids[vector_id]) != pid:
                raise ValueError("Search document product/vector ID mismatch")
            seen_vectors.add(vector_id)
    if seen_vectors != set(range(num_vectors)):
        raise ValueError("Search document vector IDs must have unique full coverage")
    if payload.get("brand_aliases") != build_brand_aliases(docs):
        raise ValueError("Search document brand aliases differ from catalog brands")
    return payload


def write_search_documents(folder, payload):
    """Write the artifact and return the three fields to merge into its manifest."""
    docs = payload.get("documents", []) if isinstance(payload, dict) else []
    vector_ids = [i for doc in docs for i in doc.get("vector_ids", [])]
    product_ids = [None] * len(vector_ids)
    for doc in docs:
        for vector_id in doc.get("vector_ids", []):
            if type(vector_id) is not int or not 0 <= vector_id < len(product_ids):
                raise ValueError("Search document vector IDs must have unique full coverage")
            product_ids[vector_id] = doc.get("product_id")
    _validate_payload(payload, product_ids, len(product_ids))
    path = Path(folder) / ARTIFACT_NAME
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return dict(search_documents_sha256=hashlib.sha256(data).hexdigest(),
                hybrid_schema_version=SCHEMA_VERSION, normalizer_version=NORMALIZER_VERSION)


def validate_search_documents(folder, meta, product_ids, num_vectors):
    """Return validated lexical state, or None only for a fully legacy manifest."""
    if not any(field in meta for field in MANIFEST_FIELDS):
        return None
    if type(meta.get("hybrid_schema_version")) is not int or meta["hybrid_schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported hybrid schema version")
    if meta.get("normalizer_version") != NORMALIZER_VERSION:
        raise ValueError("Unsupported search document normalizer version")
    checksum = meta.get("search_documents_sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Missing or invalid search document checksum")
    path = Path(folder) / ARTIFACT_NAME
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError("Search document artifact is missing or unreadable") from exc
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("Search document checksum mismatch")
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Search document artifact is invalid JSON") from exc
    return _validate_payload(payload, product_ids, num_vectors)
