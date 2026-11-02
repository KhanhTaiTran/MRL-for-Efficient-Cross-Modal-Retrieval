DROP INDEX one_open_index_job;
DROP INDEX images_primary;
UPDATE product_images SET is_primary=false WHERE NOT is_active;
CREATE UNIQUE INDEX images_primary ON product_images(product_id) WHERE is_primary;
ALTER TABLE product_images DROP COLUMN is_active;
ALTER TABLE products DROP COLUMN search_revision;
