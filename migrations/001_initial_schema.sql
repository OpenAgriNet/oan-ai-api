-- Migration 001: Initial Schema
-- Creates all market data tables: marketplaces, crops, livestock, varieties, breeds, prices, context, logs

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table: marketplaces
CREATE TABLE IF NOT EXISTS marketplaces (
    marketplace_id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    name_amharic VARCHAR(255),
    region VARCHAR(100),
    region_amharic VARCHAR(100),
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_data JSONB DEFAULT '{}'::jsonb
);

-- Table: crops (agricultural crops only, NOT livestock)
CREATE TABLE IF NOT EXISTS crops (
    crop_id SERIAL PRIMARY KEY,
    nmis_crop_id INTEGER,
    name VARCHAR(255) NOT NULL UNIQUE,
    name_amharic VARCHAR(255),
    category VARCHAR(100) DEFAULT 'agricultural',
    unit VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_data JSONB DEFAULT '{}'::jsonb
);

-- Table: crop_varieties
CREATE TABLE IF NOT EXISTS crop_varieties (
    variety_id SERIAL PRIMARY KEY,
    crop_id INTEGER NOT NULL,
    nmis_variety_id INTEGER,
    name VARCHAR(255) NOT NULL,
    name_amharic VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_data JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_variety_crop FOREIGN KEY (crop_id) REFERENCES crops(crop_id) ON DELETE CASCADE,
    CONSTRAINT uq_crop_variety UNIQUE (crop_id, name)
);

-- Table: livestock (separate from crops per user requirement)
CREATE TABLE IF NOT EXISTS livestock (
    livestock_id SERIAL PRIMARY KEY,
    nmis_livestock_id INTEGER,
    name VARCHAR(255) NOT NULL UNIQUE,
    name_amharic VARCHAR(255),
    category VARCHAR(100),
    unit VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_data JSONB DEFAULT '{}'::jsonb
);

-- Table: livestock_breeds
CREATE TABLE IF NOT EXISTS livestock_breeds (
    breed_id SERIAL PRIMARY KEY,
    livestock_id INTEGER NOT NULL,
    nmis_breed_id INTEGER,
    name VARCHAR(255) NOT NULL,
    name_amharic VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_data JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_breed_livestock FOREIGN KEY (livestock_id) REFERENCES livestock(livestock_id) ON DELETE CASCADE,
    CONSTRAINT uq_livestock_breed UNIQUE (livestock_id, name)
);

-- Table: market_prices (supports both crops and livestock)
CREATE TABLE IF NOT EXISTS market_prices (
    price_id SERIAL PRIMARY KEY,
    marketplace_id INTEGER NOT NULL,
    crop_id INTEGER,
    variety_id INTEGER,
    livestock_id INTEGER,
    breed_id INTEGER,
    min_price DECIMAL(10, 2),
    max_price DECIMAL(10, 2),
    avg_price DECIMAL(10, 2),
    modal_price DECIMAL(10, 2),
    currency VARCHAR(10) DEFAULT 'ETB',
    unit VARCHAR(50),
    price_date DATE NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR(100) DEFAULT 'nmis.et',
    is_verified BOOLEAN DEFAULT FALSE,
    confidence_score DECIMAL(3, 2),
    meta_data JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_price_marketplace FOREIGN KEY (marketplace_id) REFERENCES marketplaces(marketplace_id) ON DELETE CASCADE,
    CONSTRAINT fk_price_crop FOREIGN KEY (crop_id) REFERENCES crops(crop_id) ON DELETE CASCADE,
    CONSTRAINT fk_price_variety FOREIGN KEY (variety_id) REFERENCES crop_varieties(variety_id) ON DELETE SET NULL,
    CONSTRAINT fk_price_livestock FOREIGN KEY (livestock_id) REFERENCES livestock(livestock_id) ON DELETE CASCADE,
    CONSTRAINT fk_price_breed FOREIGN KEY (breed_id) REFERENCES livestock_breeds(breed_id) ON DELETE SET NULL,
    CONSTRAINT ck_price_crop_or_livestock CHECK (
        (crop_id IS NOT NULL AND livestock_id IS NULL) OR
        (crop_id IS NULL AND livestock_id IS NOT NULL)
    ),
    CONSTRAINT uq_crop_market_price UNIQUE (marketplace_id, crop_id, variety_id, price_date),
    CONSTRAINT uq_livestock_market_price UNIQUE (marketplace_id, livestock_id, breed_id, price_date)
);

-- Table: conversation_context (for multi-turn dialogue state)
CREATE TABLE IF NOT EXISTS conversation_context (
    context_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL,
    user_id UUID NOT NULL,
    context_type VARCHAR(50) NOT NULL,
    state VARCHAR(50) NOT NULL,
    crop_name VARCHAR(255),
    crop_id INTEGER,
    variety_name VARCHAR(255),
    variety_id INTEGER,
    livestock_name VARCHAR(255),
    livestock_id INTEGER,
    breed_name VARCHAR(255),
    breed_id INTEGER,
    marketplace_name VARCHAR(255),
    marketplace_id INTEGER,
    context_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    CONSTRAINT fk_context_crop FOREIGN KEY (crop_id) REFERENCES crops(crop_id),
    CONSTRAINT fk_context_variety FOREIGN KEY (variety_id) REFERENCES crop_varieties(variety_id),
    CONSTRAINT fk_context_livestock FOREIGN KEY (livestock_id) REFERENCES livestock(livestock_id),
    CONSTRAINT fk_context_breed FOREIGN KEY (breed_id) REFERENCES livestock_breeds(breed_id),
    CONSTRAINT fk_context_marketplace FOREIGN KEY (marketplace_id) REFERENCES marketplaces(marketplace_id),
    CONSTRAINT uq_context_active UNIQUE (conversation_id, context_type, is_active)
);

-- Table: scraper_logs (track scraper health)
CREATE TABLE IF NOT EXISTS scraper_logs (
    log_id SERIAL PRIMARY KEY,
    scraper_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    records_fetched INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    error_details JSONB,
    meta_data JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT ck_scraper_status CHECK (status IN ('started', 'success', 'partial', 'failed'))
);

-- Create trigger to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_marketplaces_updated_at BEFORE UPDATE ON marketplaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_crops_updated_at BEFORE UPDATE ON crops
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_crop_varieties_updated_at BEFORE UPDATE ON crop_varieties
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_livestock_updated_at BEFORE UPDATE ON livestock
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_livestock_breeds_updated_at BEFORE UPDATE ON livestock_breeds
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversation_context_updated_at BEFORE UPDATE ON conversation_context
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
