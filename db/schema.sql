-- lets one rule combine "same stylist" with "overlapping time"
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- one row per stylist, with the price tier they work at
CREATE TABLE IF NOT EXISTS stylists (
    id SERIAL PRIMARY KEY,                -- auto numbered id
    name TEXT UNIQUE NOT NULL,            -- no two stylists share a name
    tier TEXT NOT NULL                    -- stylist, senior, master or creative
);

-- one row per service on the menu
CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY,                  -- short code such as haircut_women
    name TEXT NOT NULL,                   -- name the agent speaks
    minutes INT NOT NULL CHECK (minutes > 0),  -- duration, must be positive
    flat_price INT,                       -- price when it does not depend on tier
    price_source TEXT NOT NULL            -- sourced or placeholder, so we stay honest
);

-- prices that depend on the stylist tier
CREATE TABLE IF NOT EXISTS service_prices (
    service_id TEXT NOT NULL REFERENCES services(id),  -- must be a real service
    tier TEXT NOT NULL,                   -- which tier this price is for
    price INT NOT NULL,                   -- price in rupees
    PRIMARY KEY (service_id, tier)        -- one price per service per tier
);

-- one row per appointment
CREATE TABLE IF NOT EXISTS bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- unique id made by the database
    idempotency_key TEXT UNIQUE NOT NULL,           -- duplicate attempts are rejected
    customer_name TEXT NOT NULL,                    -- name the caller gave
    customer_phone TEXT NOT NULL,                   -- phone the caller gave
    stylist_id INT NOT NULL REFERENCES stylists(id),  -- must be a real stylist
    starts_at TIMESTAMPTZ NOT NULL,                 -- appointment start with timezone
    ends_at TIMESTAMPTZ NOT NULL,                   -- appointment end with timezone
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when the row was written
    CHECK (ends_at > starts_at),                    -- end must come after start
    -- the diary rule: one stylist cannot have two confirmed bookings that overlap
    EXCLUDE USING gist (stylist_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
        WHERE (status = 'confirmed')
);

-- which services belong to which booking, with the price at booking time
CREATE TABLE IF NOT EXISTS booking_services (
    booking_id UUID NOT NULL REFERENCES bookings(id),  -- the booking
    service_id TEXT NOT NULL REFERENCES services(id),  -- the service
    price INT NOT NULL,                                -- price frozen at booking time
    PRIMARY KEY (booking_id, service_id)               -- a service appears once per booking
);