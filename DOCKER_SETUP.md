# Docker Setup for oan

This guide will help you run the entire oan application stack using Docker, including PostgreSQL, Redis, Python app, and automated data scraping.

## Prerequisites

- Docker (v20.10+)
- Docker Compose (v1.29+)
- Your API keys and credentials (see Configuration section below)

## Quick Start

### 1. Clone/Prepare Repository
```bash
cd /path/to/oan
```

### 2. Configure Environment Variables

Copy the `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` and add your actual API keys:
```
MEITY_API_KEY_VALUE=your_actual_key
OPENAI_API_KEY=your_actual_key
# ... etc
```

### 3. Start the Docker Stack

Build and start all services:
```bash
docker-compose up --build
```

Or run in the background:
```bash
docker-compose up -d --build
```

### 4. What Happens on Startup

When you run `docker-compose up`, the following happens automatically:

1. **PostgreSQL Container** starts and initializes
2. **Redis Container** starts and initializes
3. **Python App Container** starts and:
   - Waits for PostgreSQL to be ready
   - Waits for Redis to be ready
   - Runs database migrations using Alembic
   - **Runs all data scrapers** (`python scripts/run_all_scrapers.py`)
   - Starts the FastAPI application on port 8000

### 5. Monitor the Process

View logs to see the startup process:
```bash
# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f app
docker-compose logs -f postgres
docker-compose logs -f redis
```

## Services Overview

### PostgreSQL
- **Container**: `oan_postgres`
- **Port**: 5432 (accessible from host at localhost:5432)
- **Default credentials**:
  - User: `postgres`
  - Password: `postgres`
  - Database: `oan`
- **Data persistence**: Stored in `postgres_data` volume

### Redis
- **Container**: `oan_redis`
- **Port**: 6379 (accessible from host at localhost:6379)
- **Data persistence**: Stored in `redis_data` volume

### FastAPI Application
- **Container**: `oan_app`
- **Port**: 8000 (accessible from host at localhost:8000)
- **Health check endpoint**: `http://localhost:8000/health`
- **API documentation**: `http://localhost:8000/docs` (Swagger UI)

## Common Commands

### Start services
```bash
docker-compose up -d
```

### Stop services
```bash
docker-compose down
```

### Stop and remove volumes (reset everything)
```bash
docker-compose down -v
```

### Rebuild and restart
```bash
docker-compose up --build -d
```

### View service status
```bash
docker-compose ps
```

### Access PostgreSQL directly
```bash
docker exec -it oan_postgres psql -U postgres -d oan
```

### Access Redis directly
```bash
docker exec -it oan_redis redis-cli
```

### Run a command in app container
```bash
docker exec -it oan_app /bin/bash
```

### Run scrapers manually
```bash
docker exec -it oan_app python scripts/run_all_scrapers.py
```

### View migration history
```bash
docker exec -it oan_app alembic history
```

### Run new migrations
```bash
docker exec -it oan_app alembic upgrade head
```

## Configuration

### Environment Variables

The application reads configuration from `.env` file. Key variables:

```
# Database (auto-set from docker-compose)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/oan

# Redis (auto-set from docker-compose)
REDIS_HOST=redis
REDIS_PORT=6379

# API Keys (must be set in .env)
MEITY_API_KEY_VALUE=
OPENAI_API_KEY=
MAPBOX_API_TOKEN=
# ... see .env.example for all options
```

### Database Configuration

The `docker-compose.yml` sets these environment variables:
- `DB_USER`: postgres
- `DB_PASSWORD`: postgres
- `DB_NAME`: oan
- `DB_PORT`: 5432

To change these, either:
1. Add to `.env`:
   ```
   DB_USER=myuser
   DB_PASSWORD=mypassword
   DB_NAME=mydb
   ```
2. Or modify `docker-compose.yml` directly

## Data Scrapers

The scrapers run automatically on container startup. They:

1. Clear existing market prices
2. Sync data from NMIS API in this order:
   - Marketplaces
   - Crops
   - Livestock
   - Crop varieties
   - Livestock varieties
   - Crop prices
   - Livestock prices
3. Log execution metrics to the database

**Scraper Status**: Check logs for scraper completion:
```bash
docker-compose logs app | grep "scraper\|Scraper"
```

**Manual Execution**: To run scrapers again:
```bash
docker exec -it oan_app python scripts/run_all_scrapers.py
```

**Schedule Periodic Runs**: Consider using Kubernetes CronJobs or add a scheduled task to supervisord configuration if needed.

## Troubleshooting

### Services won't start
```bash
# Check logs
docker-compose logs

# Verify Docker and Compose versions
docker --version
docker-compose --version
```

### Database connection errors
```bash
# Verify PostgreSQL is healthy
docker-compose ps

# Check PostgreSQL logs
docker-compose logs postgres

# Test connection
docker exec -it oan_postgres pg_isready
```

### Redis connection errors
```bash
# Verify Redis is healthy
docker-compose ps

# Check Redis logs
docker-compose logs redis

# Test connection
docker exec -it oan_redis redis-cli ping
```

### Scrapers failing
```bash
# Check full logs
docker-compose logs app

# Verify API keys are set
docker exec -it oan_app env | grep -i key

# Run scrapers with verbose output
docker exec -it oan_app python scripts/run_all_scrapers.py -v
```

### Port conflicts
If port 8000, 5432, or 6379 are already in use, modify `docker-compose.yml`:

```yaml
ports:
  - "9000:8000"  # Change 8000 to 9000 on host
```

## Production Considerations

For production deployments:

1. **Use environment-specific configs**: Create separate `.env.prod` files
2. **Use secrets management**: Use Docker Secrets or your orchestration platform's secrets
3. **Set restart policies**: Already configured as `restart: unless-stopped`
4. **Backup volumes**: Implement backup strategy for `postgres_data` and `redis_data`
5. **Set resource limits**: Add memory/CPU limits in compose file
6. **Use a reverse proxy**: Put Nginx/Traefik in front
7. **Enable logging**: Configure Docker logging drivers
8. **Update base images**: Regularly update Python, PostgreSQL, Redis images

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/documentation)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
