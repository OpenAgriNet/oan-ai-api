#!/bin/bash

echo "🔍 Voice Pipeline Diagnostics"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if container is running
echo "1️⃣  Container Status:"
if docker ps | grep -q "oan_app"; then
    echo "   ✅ Backend container is running"
else
    echo "   ❌ Backend container is NOT running"
    echo "   Run: ./docker-start.sh"
    exit 1
fi
echo ""

# Check for recent errors
echo "2️⃣  Recent Errors (last 5 minutes):"
errors=$(docker-compose logs --since 5m app 2>&1 | grep -i "error\|exception\|failed\|traceback" | tail -10)
if [ -z "$errors" ]; then
    echo "   ✅ No errors found"
else
    echo "   ❌ Errors detected:"
    echo "$errors" | sed 's/^/   /'
fi
echo ""

# Check WebSocket connections
echo "3️⃣  WebSocket Activity (last 5 minutes):"
ws_activity=$(docker-compose logs --since 5m app 2>&1 | grep -i "websocket\|pipeline started" | tail -5)
if [ -z "$ws_activity" ]; then
    echo "   ⚠️  No WebSocket activity detected"
    echo "   Have you tried connecting from the frontend?"
else
    echo "   ✅ WebSocket activity found:"
    echo "$ws_activity" | sed 's/^/   /'
fi
echo ""

# Check ASR activity
echo "4️⃣  ASR Activity (last 5 minutes):"
asr_activity=$(docker-compose logs --since 5m app 2>&1 | grep -i "asr\|transcription" | tail -5)
if [ -z "$asr_activity" ]; then
    echo "   ⚠️  No ASR activity detected"
else
    echo "   ✅ ASR activity found:"
    echo "$asr_activity" | sed 's/^/   /'
fi
echo ""

# Check LLM activity
echo "5️⃣  LLM Activity (last 5 minutes):"
llm_activity=$(docker-compose logs --since 5m app 2>&1 | grep -i "llm\|agent\|generation" | tail -5)
if [ -z "$llm_activity" ]; then
    echo "   ⚠️  No LLM activity detected"
    echo "   This might be where it's stuck!"
else
    echo "   ✅ LLM activity found:"
    echo "$llm_activity" | sed 's/^/   /'
fi
echo ""

# Check for hanging processes
echo "6️⃣  Recent Turn Activity:"
turn_activity=$(docker-compose logs --since 5m app 2>&1 | grep -i "turn\|speech start\|speech end" | tail -10)
if [ -z "$turn_activity" ]; then
    echo "   ⚠️  No turn activity"
else
    echo "$turn_activity" | sed 's/^/   /'
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💡 Recommendations:"
echo ""
echo "If no LLM activity:"
echo "  1. Check if agent import works: docker exec oan_app python test-agent-import.py"
echo "  2. Restart backend: ./docker-restart.sh"
echo "  3. Check full logs: docker-compose logs -f app"
echo ""
echo "If ASR works but no LLM:"
echo "  1. Agent might be stuck loading"
echo "  2. Check for import errors in logs"
echo "  3. Verify GEMINI_API_KEY in .env"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

