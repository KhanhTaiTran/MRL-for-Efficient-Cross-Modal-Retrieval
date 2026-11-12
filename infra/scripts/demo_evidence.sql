-- Presentation evidence only. No user email, password/token hashes or addresses.
BEGIN TRANSACTION READ ONLY;

SELECT version AS migration_version, dirty FROM schema_migrations;

SELECT 'active_products' AS metric, count(*) AS total FROM products WHERE is_active
UNION ALL
SELECT 'active_product_images', count(*) FROM product_images i JOIN products p ON p.id=i.product_id WHERE p.is_active AND i.is_active
UNION ALL
SELECT 'current_vector_mappings', count(*) FROM index_vector_mappings m JOIN ai_index_versions v ON v.id=m.index_version_id WHERE v.is_active;

SELECT version_tag, num_vectors, supported_dims,
       metadata->>'catalog_source' AS catalog_source,
       metadata->>'clip_model_name' AS backbone,
       metadata->>'model_kind' AS model_kind,
       metadata->>'commerce_data_kind' AS commerce_data
FROM ai_index_versions WHERE is_active;

-- The bridge between a FAISS row and the SQL catalog / MinIO object.
SELECT m.vector_id, p.handle, p.name, i.object_key
FROM index_vector_mappings m
JOIN ai_index_versions v ON v.id=m.index_version_id AND v.is_active
JOIN product_images i ON i.id=m.product_image_id
JOIN products p ON p.id=i.product_id
ORDER BY m.vector_id LIMIT 3;

SELECT status, count(*) AS jobs FROM ai_index_jobs GROUP BY status ORDER BY status;
SELECT search_status, count(*) AS products FROM products WHERE is_active GROUP BY search_status;

-- Counts are useful before/after the manual purchase/review demonstration.
SELECT 'orders' AS metric, count(*) AS total FROM orders
UNION ALL SELECT 'order_items', count(*) FROM order_items
UNION ALL SELECT 'visible_reviews', count(*) FROM reviews WHERE NOT is_hidden
UNION ALL SELECT 'wishlist_entries', count(*) FROM wishlists;

COMMIT;
