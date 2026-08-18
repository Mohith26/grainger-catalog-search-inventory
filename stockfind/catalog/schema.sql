-- StockFind relational schema (Postgres 16).
-- Full-text ranking lives in a STORED generated tsvector column with a GIN index,
-- so the lexical index can never drift from the row it describes.

DROP TABLE IF EXISTS reservations CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS warehouses CASCADE;

CREATE TABLE warehouses (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    region      text NOT NULL,          -- US state/region code the DC primarily serves
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL
);

CREATE TABLE products (
    id            integer PRIMARY KEY,
    part_no       text NOT NULL UNIQUE,
    name          text NOT NULL,
    brand         text NOT NULL,
    category      text NOT NULL,
    subtype       text NOT NULL,
    material      text NOT NULL,
    price_cents   integer NOT NULL CHECK (price_cents >= 0),
    lead_time_days integer NOT NULL CHECK (lead_time_days >= 0),
    description   text NOT NULL,
    attributes    jsonb NOT NULL DEFAULT '{}'::jsonb,
    attr_text     text NOT NULL DEFAULT '',   -- normalized attribute tokens for FTS
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(brand, '') || ' ' || coalesce(part_no, '')), 'B') ||
        setweight(to_tsvector('english',
            coalesce(category, '') || ' ' || coalesce(subtype, '') || ' ' ||
            coalesce(material, '') || ' ' || coalesce(attr_text, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'D')
    ) STORED
);

CREATE INDEX products_search_idx ON products USING GIN (search_vector);
CREATE INDEX products_category_idx ON products (category);
CREATE INDEX products_brand_idx ON products (brand);
CREATE INDEX products_attributes_idx ON products USING GIN (attributes);

CREATE TABLE inventory (
    product_id     integer NOT NULL REFERENCES products (id),
    warehouse_code text NOT NULL REFERENCES warehouses (code),
    on_hand        integer NOT NULL CHECK (on_hand >= 0),
    reserved       integer NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    PRIMARY KEY (product_id, warehouse_code),
    -- ATP can never go negative: reserved may never exceed on_hand. This DB-level
    -- invariant is the last line of defense behind the SELECT ... FOR UPDATE path.
    CONSTRAINT no_oversell CHECK (reserved <= on_hand)
);

CREATE TABLE reservations (
    id             bigserial PRIMARY KEY,
    product_id     integer NOT NULL REFERENCES products (id),
    warehouse_code text NOT NULL REFERENCES warehouses (code),
    quantity       integer NOT NULL CHECK (quantity > 0),
    buyer          text NOT NULL,
    status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released')),
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX reservations_product_idx ON reservations (product_id, warehouse_code);
