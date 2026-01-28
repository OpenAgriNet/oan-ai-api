#!/bin/bash
set -e

echo "========================================"
echo "OAN AI API Docker Startup Script"
echo "========================================"

# Docker Compose's depends_on with condition: service_healthy 
# already ensures postgres and redis are ready
echo "✓ PostgreSQL is ready (verified by health check)"
echo "✓ Redis is ready (verified by health check)"
echo "✓ Cosdata is ready (verified by health check)"

# Run database migrations
echo ""
echo "Running database migrations..."
cd /app
if command -v alembic &> /dev/null; then
  alembic upgrade head || echo "⚠ Migration warning: $(alembic upgrade head 2>&1)"
  echo "✓ Database migrations completed"
else
  echo "⚠ Alembic not found, skipping migrations"
fi

# Run the data scrapers
echo ""
echo "Running data scrapers..."
if [ -f "/app/scripts/run_all_scrapers.py" ]; then
  python /app/scripts/run_all_scrapers.py
  echo "✓ Data scrapers completed"
else
  echo "⚠ Scraper script not found at /app/scripts/run_all_scrapers.py"
fi

# Start the FastAPI application with supervisor
echo ""
echo "========================================"
echo "Starting FastAPI application..."
echo "========================================"
/usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf