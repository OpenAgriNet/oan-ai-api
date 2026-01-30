#!/bin/bash

# Docker Restart Script for OAN AI API
# This script rebuilds and restarts the Docker container

set -e

echo "🔄 Restarting OAN AI API Docker Container..."
echo ""

# Stop and remove existing containers
echo "📦 Stopping existing containers..."
docker-compose down

# Rebuild the image (to pick up code changes)
echo "🔨 Rebuilding Docker image..."
docker-compose build --no-cache

# Start the containers
echo "🚀 Starting containers..."
docker-compose up -d

# Wait for container to be ready
echo "⏳ Waiting for container to be ready..."
sleep 5

# Show logs
echo ""
echo "📋 Container logs (Ctrl+C to exit):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker-compose logs -f

