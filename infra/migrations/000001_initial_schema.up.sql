CREATE TABLE users (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, avatar_key TEXT, password_hash TEXT,
 provider TEXT NOT NULL DEFAULT 'local' CHECK (provider IN ('local','google')), provider_id TEXT,
 role TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer','admin')),
 is_verified BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_ci ON users(lower(email));
CREATE UNIQUE INDEX users_provider_identity ON users(provider,provider_id) WHERE provider_id IS NOT NULL;
CREATE TABLE otp_tokens (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 code_hash TEXT NOT NULL, purpose TEXT NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
 expires_at TIMESTAMPTZ NOT NULL, used BOOLEAN NOT NULL DEFAULT false, attempts SMALLINT NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5), created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX otp_user_purpose ON otp_tokens(user_id,purpose);
CREATE TABLE refresh_tokens (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, family_id UUID NOT NULL, replaced_by UUID REFERENCES refresh_tokens(id),
 expires_at TIMESTAMPTZ NOT NULL, revoked BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX refresh_user ON refresh_tokens(user_id); CREATE INDEX refresh_family ON refresh_tokens(family_id);
CREATE TABLE products (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), handle TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT,
 brand TEXT, category TEXT, base_price NUMERIC(12,2) NOT NULL CHECK(base_price>=0), currency CHAR(3) NOT NULL DEFAULT 'USD',
 compare_at_price NUMERIC(12,2) CHECK(compare_at_price>=0), is_active BOOLEAN NOT NULL DEFAULT true,
 is_featured BOOLEAN NOT NULL DEFAULT false, tags TEXT[] NOT NULL DEFAULT '{}',
 search_status TEXT NOT NULL DEFAULT 'pending' CHECK(search_status IN ('pending','indexing','ready','failed')),
 metadata JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX products_active ON products(is_active,created_at DESC); CREATE INDEX products_category ON products(category);
CREATE TABLE product_variants (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 sku TEXT UNIQUE, size TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '', price NUMERIC(12,2) NOT NULL CHECK(price>=0),
 stock INT NOT NULL DEFAULT 0 CHECK(stock>=0), is_available BOOLEAN NOT NULL DEFAULT true,
 UNIQUE(product_id,size,color), UNIQUE(product_id,id)
);
ALTER TABLE products ADD COLUMN default_variant_id UUID;
ALTER TABLE products ADD CONSTRAINT products_default_variant FOREIGN KEY(id,default_variant_id) REFERENCES product_variants(product_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE product_images (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 object_key TEXT NOT NULL UNIQUE, alt_text TEXT, position SMALLINT NOT NULL DEFAULT 0 CHECK(position>=0), is_primary BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX images_product ON product_images(product_id,position);
CREATE UNIQUE INDEX images_primary ON product_images(product_id) WHERE is_primary;
CREATE TABLE ai_index_versions (
 id UUID PRIMARY KEY, version_tag TEXT NOT NULL UNIQUE, checkpoint_name TEXT NOT NULL, checkpoint_sha TEXT NOT NULL,
 num_vectors INT NOT NULL CHECK(num_vectors>0), supported_dims INT[] NOT NULL, index_path TEXT NOT NULL,
 is_active BOOLEAN NOT NULL DEFAULT false, metadata JSONB NOT NULL DEFAULT '{}', built_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_active_index ON ai_index_versions((true)) WHERE is_active;
CREATE TABLE ai_index_jobs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','done','failed')),
 triggered_by UUID REFERENCES users(id), index_version_id UUID REFERENCES ai_index_versions(id),
 started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, error_msg TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE index_vector_mappings (
 index_version_id UUID NOT NULL REFERENCES ai_index_versions(id) ON DELETE CASCADE,
 vector_id INT NOT NULL CHECK(vector_id>=0), product_image_id UUID NOT NULL REFERENCES product_images(id),
 PRIMARY KEY(index_version_id,vector_id), UNIQUE(index_version_id,product_image_id)
);
CREATE INDEX mappings_image ON index_vector_mappings(product_image_id);
CREATE TABLE orders (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
 order_status TEXT NOT NULL DEFAULT 'confirmed' CHECK(order_status IN ('confirmed','cancelled')),
 payment_status TEXT NOT NULL DEFAULT 'paid' CHECK(payment_status IN ('paid','refunded')),
 fulfillment_status TEXT NOT NULL DEFAULT 'unfulfilled' CHECK(fulfillment_status IN ('unfulfilled','shipped','delivered')),
 payment_method TEXT NOT NULL DEFAULT 'mock', idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 subtotal NUMERIC(12,2) NOT NULL CHECK(subtotal>=0), shipping_fee NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK(shipping_fee>=0),
 total NUMERIC(12,2) NOT NULL CHECK(total>=0 AND total=subtotal+shipping_fee), currency CHAR(3) NOT NULL DEFAULT 'USD',
 shipping_address JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id,idempotency_key)
);
CREATE INDEX orders_user ON orders(user_id,created_at DESC);
CREATE TABLE order_items (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 product_id UUID REFERENCES products(id) ON DELETE SET NULL, variant_id UUID REFERENCES product_variants(id) ON DELETE SET NULL,
 name TEXT NOT NULL, sku TEXT, size TEXT, color TEXT, price NUMERIC(12,2) NOT NULL CHECK(price>=0), quantity INT NOT NULL CHECK(quantity>0), image_key TEXT
);
CREATE INDEX order_items_order ON order_items(order_id);
CREATE TABLE cart_items (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 variant_id UUID NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE, quantity INT NOT NULL DEFAULT 1 CHECK(quantity>0), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id,variant_id)
);
CREATE TABLE reviews (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), product_id UUID NOT NULL REFERENCES products(id), user_id UUID NOT NULL REFERENCES users(id),
 order_id UUID NOT NULL REFERENCES orders(id), rating SMALLINT NOT NULL CHECK(rating BETWEEN 1 AND 5), comment TEXT,
 is_verified_purchase BOOLEAN NOT NULL DEFAULT true, is_hidden BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id,product_id)
);
CREATE INDEX reviews_product ON reviews(product_id,created_at DESC);
CREATE TABLE review_media (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
 object_key TEXT NOT NULL UNIQUE, media_type TEXT NOT NULL CHECK(media_type IN ('image','video')), position SMALLINT NOT NULL DEFAULT 0 CHECK(position>=0)
);
CREATE TABLE wishlists (
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id,product_id)
);
