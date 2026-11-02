DROP TABLE IF EXISTS wishlists,review_media,reviews,cart_items,order_items,orders,index_vector_mappings,ai_index_jobs,ai_index_versions,product_images;
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_default_variant;
DROP TABLE product_variants,products,refresh_tokens,otp_tokens,users;
