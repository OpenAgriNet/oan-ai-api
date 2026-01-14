-- Migration 002: Add Indexes
-- Creates indexes for all tables to optimize query performance

-- Marketplace indexes
CREATE INDEX IF NOT EXISTS idx_marketplace_name ON marketplaces(name);
CREATE INDEX IF NOT EXISTS idx_marketplace_region ON marketplaces(region);
CREATE INDEX IF NOT EXISTS idx_marketplace_name_lower ON marketplaces(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_marketplace_name_amharic ON marketplaces(name_amharic);
CREATE INDEX IF NOT EXISTS idx_marketplace_coords ON marketplaces(latitude, longitude);

-- Crop indexes
CREATE INDEX IF NOT EXISTS idx_crop_name ON crops(name);
CREATE INDEX IF NOT EXISTS idx_crop_name_lower ON crops(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_crop_name_amharic ON crops(name_amharic);
CREATE INDEX IF NOT EXISTS idx_crop_category ON crops(category);

-- Crop variety indexes
CREATE INDEX IF NOT EXISTS idx_variety_crop ON crop_varieties(crop_id);
CREATE INDEX IF NOT EXISTS idx_variety_name ON crop_varieties(name);
CREATE INDEX IF NOT EXISTS idx_variety_nmis_id ON crop_varieties(nmis_variety_id);

-- Livestock indexes
CREATE INDEX IF NOT EXISTS idx_livestock_name ON livestock(name);
CREATE INDEX IF NOT EXISTS idx_livestock_name_lower ON livestock(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_livestock_name_amharic ON livestock(name_amharic);
CREATE INDEX IF NOT EXISTS idx_livestock_category ON livestock(category);

-- Livestock breed indexes
CREATE INDEX IF NOT EXISTS idx_breed_livestock ON livestock_breeds(livestock_id);
CREATE INDEX IF NOT EXISTS idx_breed_name ON livestock_breeds(name);
CREATE INDEX IF NOT EXISTS idx_breed_nmis_id ON livestock_breeds(nmis_breed_id);

-- Market price indexes (critical for query performance)
CREATE INDEX IF NOT EXISTS idx_price_marketplace ON market_prices(marketplace_id);
CREATE INDEX IF NOT EXISTS idx_price_crop ON market_prices(crop_id);
CREATE INDEX IF NOT EXISTS idx_price_variety ON market_prices(variety_id);
CREATE INDEX IF NOT EXISTS idx_price_livestock ON market_prices(livestock_id);
CREATE INDEX IF NOT EXISTS idx_price_breed ON market_prices(breed_id);
CREATE INDEX IF NOT EXISTS idx_price_date ON market_prices(price_date DESC);
CREATE INDEX IF NOT EXISTS idx_price_fetched ON market_prices(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_crop_lookup ON market_prices(marketplace_id, crop_id, price_date DESC);
CREATE INDEX IF NOT EXISTS idx_price_livestock_lookup ON market_prices(marketplace_id, livestock_id, price_date DESC);

-- Conversation context indexes
CREATE INDEX IF NOT EXISTS idx_context_conversation ON conversation_context(conversation_id);
CREATE INDEX IF NOT EXISTS idx_context_user ON conversation_context(user_id);
CREATE INDEX IF NOT EXISTS idx_context_state ON conversation_context(state);
CREATE INDEX IF NOT EXISTS idx_context_active ON conversation_context(is_active, expires_at);
CREATE INDEX IF NOT EXISTS idx_context_type ON conversation_context(context_type);

-- Scraper log indexes
CREATE INDEX IF NOT EXISTS idx_scraper_type ON scraper_logs(scraper_type);
CREATE INDEX IF NOT EXISTS idx_scraper_status ON scraper_logs(status);
CREATE INDEX IF NOT EXISTS idx_scraper_started ON scraper_logs(started_at DESC);
