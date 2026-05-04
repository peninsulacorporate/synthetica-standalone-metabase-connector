-- Seed data for the demo Postgres database that the LLM will query through
-- the metabase-mcp server. Two simple tables — orders and customers — with
-- enough rows to make the chart tools (`bar`, `line`, `pie`) interesting.

CREATE TABLE customers (
    id           SERIAL PRIMARY KEY,
    email        TEXT NOT NULL,
    country      TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INTEGER REFERENCES customers(id),
    total        NUMERIC(10, 2) NOT NULL,
    status       TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO customers (email, country) VALUES
    ('alice@example.com',   'BR'),
    ('bob@example.com',     'US'),
    ('carla@example.com',   'BR'),
    ('diego@example.com',   'AR'),
    ('eve@example.com',     'US'),
    ('frank@example.com',   'PT'),
    ('gabi@example.com',    'BR'),
    ('hugo@example.com',    'PT');

INSERT INTO orders (customer_id, total, status, created_at) VALUES
    (1, 120.50, 'paid',     NOW() - INTERVAL '60 days'),
    (1,  85.00, 'paid',     NOW() - INTERVAL '45 days'),
    (1, 200.00, 'paid',     NOW() - INTERVAL '12 days'),
    (2,  40.00, 'paid',     NOW() - INTERVAL '50 days'),
    (2, 150.00, 'refunded', NOW() - INTERVAL '20 days'),
    (3,  90.00, 'paid',     NOW() - INTERVAL '40 days'),
    (3,  60.00, 'pending',  NOW() - INTERVAL '5 days'),
    (4, 320.00, 'paid',     NOW() - INTERVAL '35 days'),
    (5, 110.00, 'paid',     NOW() - INTERVAL '30 days'),
    (5,  75.00, 'paid',     NOW() - INTERVAL '7 days'),
    (6, 250.00, 'paid',     NOW() - INTERVAL '25 days'),
    (7,  45.00, 'paid',     NOW() - INTERVAL '15 days'),
    (7,  88.50, 'pending',  NOW() - INTERVAL '2 days'),
    (8, 175.00, 'paid',     NOW() - INTERVAL '10 days'),
    (8,  55.00, 'refunded', NOW() - INTERVAL '3 days');
