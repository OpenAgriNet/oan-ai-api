#!/bin/bash

# Check recent logs for errors
echo "=== Checking Docker logs for errors ==="
echo ""

echo "1. Container Status:"
docker-compose ps
echo ""

echo "2. Recent Backend Logs (last 100 lines):"
docker-compose logs --tail=100 app
echo ""

echo "3. Checking for errors:"
docker-compose logs app | grep -i "error\|exception\|failed\|traceback" | tail -20
echo ""

echo "4. Checking for WebSocket activity:"
docker-compose logs app | grep -i "websocket\|pipeline\|turn" | tail -20
echo ""

echo "5. Checking for LLM activity:"
docker-compose logs app | grep -i "llm\|agent\|stream" | tail -20

