-- Vehicles: exact names from PiecesAuto24
CREATE TABLE IF NOT EXISTS vehicles (
    id SERIAL PRIMARY KEY,
    brand VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    chassis_code VARCHAR,
    displacement VARCHAR,
    power_hp INTEGER,
    fuel VARCHAR,
    year_start INTEGER,
    year_end INTEGER,
    engine_code VARCHAR,
    pa24_full_name VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(pa24_full_name)
);

-- VIN patterns: first 13 chars -> vehicle
CREATE TABLE IF NOT EXISTS vin_patterns (
    id SERIAL PRIMARY KEY,
    vin_pattern VARCHAR(13) NOT NULL,
    vehicle_id INTEGER REFERENCES vehicles(id),
    confidence VARCHAR DEFAULT 'high',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(vin_pattern)
);

-- Part references extracted from PiecesAuto24
CREATE TABLE IF NOT EXISTS part_references (
    id SERIAL PRIMARY KEY,
    vehicle_id INTEGER REFERENCES vehicles(id),
    part_name VARCHAR NOT NULL,
    brand VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    is_oe BOOLEAN DEFAULT FALSE,
    price_eur FLOAT,
    source VARCHAR DEFAULT 'piecesauto24',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(vehicle_id, part_name, brand, reference)
);

-- Compatible vehicles for a given part reference
CREATE TABLE IF NOT EXISTS part_vehicle_compatibility (
    id SERIAL PRIMARY KEY,
    reference_id INTEGER REFERENCES part_references(id),
    compatible_vehicle_name VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Screenshots stored locally
CREATE TABLE IF NOT EXISTS screenshots (
    id SERIAL PRIMARY KEY,
    vehicle_id INTEGER REFERENCES vehicles(id),
    part_name VARCHAR,
    filename VARCHAR NOT NULL,
    screenshot_type VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Client request logs
CREATE TABLE IF NOT EXISTS requests_log (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    vehicle_id INTEGER,
    part_name VARCHAR,
    vin VARCHAR,
    vin_confidence VARCHAR,
    cdg_results_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
