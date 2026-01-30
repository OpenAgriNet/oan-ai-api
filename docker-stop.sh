#!/bin/bash

# Docker Stop Script for OAN AI API

set -e

echo "🛑 Stopping OAN AI API Docker Container..."
echo ""

docker-compose down

echo ""
echo "✅ Container stopped successfully"

