# Nominatim Setup Guide

> **⚠️ IMPORTANT:** You must set up Nominatim before running the main application, as the app depends on Nominatim for geocoding services.

## Overview

Nominatim is an open-source geocoding service that provides reverse geocoding functionality for the OAN AI API. This service is required for location-based features in the application.

## Prerequisites

- Docker and Docker Compose installed
- At least 8GB of available RAM
- Sufficient disk space 

## Setup Instructions

### 1. Add Nominatim to your Docker Compose

Add the following service configuration to your `docker-compose.yml` file:

```yaml
services:
  nominatim:
    image: mediagis/nominatim:5.1
    container_name: nominatim
    shm_size: 4g 
    mem_limit: 8g 
    cpus: 4.0 
    environment:
      - PBF_URL=https://download.geofabrik.de/asia/india-latest.osm.pbf
      - REPLICATION_URL=https://download.geofabrik.de/asia/india-updates/
    volumes:
      - nominatim-data:/var/lib/postgresql/16/main
    ports:
      - "8080:8080"
    restart: unless-stopped
    networks:
      - svanetwork

volumes:
  nominatim-data:
    driver: local

networks:
  svanetwork:
    driver: bridge
```

### 2. Start Nominatim Service

```bash
# Start only the Nominatim service first
docker-compose up nominatim -d

# Monitor the logs to see the import progress
docker-compose logs -f nominatim
```

### 3. Wait for Initial Setup

The initial setup will take some time (30-60 minutes or more based on your device specifications) as it downloads and imports the India OSM data. You'll see logs indicating the import progress.

### 4. Verify Setup

Once the import is complete, verify that Nominatim is working:

```bash
# Test the service
curl "http://localhost:8080/search?q=New+Delhi&format=json&limit=1"
```

You should receive a JSON response with location data.

### 5. Start the Main Application

Only after Nominatim is fully set up and running, start your main application:

```bash
# Start all services
docker-compose up -d
```

## Configuration

The service is configured to:
- Use India OSM data for comprehensive coverage
- Enable automatic updates via replication
- Run on port 8080 (configurable)
- Use persistent storage for the database

## Troubleshooting

- **High memory usage**: Ensure you have at least 8GB RAM available
- **Slow import**: This is normal for the initial setup with India data
- **Connection refused**: Wait for the import to complete before testing
- **Out of disk space**: Ensure you have at least 20GB free space

## API Usage

Once running, Nominatim provides a REST API accessible at `http://localhost:8080`. The main application uses this service for geocoding operations.