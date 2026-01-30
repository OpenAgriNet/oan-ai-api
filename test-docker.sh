#!/bin/bash

# Docker Test Script - Verify all services are working

set -e

echo "🧪 Testing OAN AI API Docker Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
PASSED=0
FAILED=0

# Function to test endpoint
test_endpoint() {
    local name=$1
    local url=$2
    local expected=$3
    
    echo -n "Testing $name... "
    
    response=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    
    if [ "$response" = "$expected" ]; then
        echo -e "${GREEN}✓ PASSED${NC} (HTTP $response)"
        ((PASSED++))
    else
        echo -e "${RED}✗ FAILED${NC} (Expected HTTP $expected, got $response)"
        ((FAILED++))
    fi
}

# Function to test service
test_service() {
    local name=$1
    local container=$2
    
    echo -n "Testing $name... "
    
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "not found")
        if [ "$status" = "running" ]; then
            echo -e "${GREEN}✓ PASSED${NC} (Container running)"
            ((PASSED++))
        else
            echo -e "${RED}✗ FAILED${NC} (Container status: $status)"
            ((FAILED++))
        fi
    else
        echo -e "${RED}✗ FAILED${NC} (Container not found)"
        ((FAILED++))
    fi
}

echo "1️⃣  Container Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
test_service "Backend Container" "oan_app"
test_service "PostgreSQL Container" "oan_postgres"
test_service "Redis Container" "oan_redis"
echo ""

echo "2️⃣  HTTP Endpoints"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
test_endpoint "Health Check" "http://localhost:8000/health" "200"
test_endpoint "API Docs" "http://localhost:8000/docs" "200"
test_endpoint "OpenAPI Schema" "http://localhost:8000/openapi.json" "200"
echo ""

echo "3️⃣  Database Connection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -n "Testing PostgreSQL... "
if docker exec oan_postgres pg_isready -U oan_user -d oan_db > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PASSED${NC} (Database ready)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAILED${NC} (Database not ready)"
    ((FAILED++))
fi
echo ""

echo "4️⃣  Redis Connection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -n "Testing Redis... "
if docker exec oan_redis redis-cli ping | grep -q "PONG"; then
    echo -e "${GREEN}✓ PASSED${NC} (Redis responding)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAILED${NC} (Redis not responding)"
    ((FAILED++))
fi
echo ""

echo "5️⃣  API Endpoints"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
test_endpoint "Chat Endpoint" "http://localhost:8000/chat" "405"  # POST only, so 405 is expected
test_endpoint "Transcribe Endpoint" "http://localhost:8000/transcribe/" "422"  # POST with body required
test_endpoint "TTS Endpoint" "http://localhost:8000/tts/" "422"  # POST with body required
echo ""

echo "6️⃣  Database Tables"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -n "Testing Marketplaces Table... "
count=$(docker exec oan_postgres psql -U oan_user -d oan_db -t -c "SELECT COUNT(*) FROM marketplaces;" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$count" -gt "0" ]; then
    echo -e "${GREEN}✓ PASSED${NC} ($count records)"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠ WARNING${NC} (No records - run populate_db.py)"
fi

echo -n "Testing Crop Prices Table... "
count=$(docker exec oan_postgres psql -U oan_user -d oan_db -t -c "SELECT COUNT(*) FROM crop_prices;" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$count" -gt "0" ]; then
    echo -e "${GREEN}✓ PASSED${NC} ($count records)"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠ WARNING${NC} (No records - run populate_db.py)"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Test Results"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    echo ""
    echo "🎉 Docker setup is working correctly!"
    echo ""
    echo "Next steps:"
    echo "  1. Start frontend: cd agriSulopa/oan-ui-service && npm run dev"
    echo "  2. Open http://localhost:8082"
    echo "  3. Test voice chat with microphone"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Some tests failed${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check logs: ./docker-logs.sh"
    echo "  2. Restart: ./docker-restart.sh"
    echo "  3. Check status: docker-compose ps"
    echo ""
    exit 1
fi

