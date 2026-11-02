ALTER TABLE cart_items ADD CONSTRAINT cart_quantity_max CHECK (quantity <= 99) NOT VALID;
ALTER TABLE cart_items VALIDATE CONSTRAINT cart_quantity_max;
