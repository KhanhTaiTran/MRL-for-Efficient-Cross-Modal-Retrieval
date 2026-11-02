ALTER TABLE products ADD COLUMN search_revision BIGINT NOT NULL DEFAULT 1 CHECK(search_revision > 0);
ALTER TABLE product_images ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;
DROP INDEX images_primary;
CREATE UNIQUE INDEX images_primary ON product_images(product_id) WHERE is_primary AND is_active;
CREATE UNIQUE INDEX one_open_index_job ON ai_index_jobs((true)) WHERE status IN ('pending','running');
