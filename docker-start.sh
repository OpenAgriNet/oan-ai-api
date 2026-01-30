#!/bin/bash

# Docker Start Script for OAN AI API
# This script starts the Docker container without rebuilding

set -e

echo "🚀 Starting OAN AI API Docker Container..."
echo ""

# Start the containers
docker-compose up -d

# Wait for container to be ready
echo "⏳ Waiting for container to be ready..."
sleep 5

# Check status
echo ""
echo "✅ Container Status:"
docker-compose ps

echo ""
echo "📋 To view logs, run: docker-compose logs -f"
echo "📋 To stop, run: docker-compose down"
echo ""
echo "🌐 API available at: http://localhost:8000"
echo "🌐 WebSocket at: ws://localhost:8000/conv/ws?lang=en"

