
# Docker Setup Guide

##  Delete All Docker Volumes and Prune System

```bash
docker system prune -a --volumes
```

---

##  Start Docker Compose with Rebuild and Detached Mode

```bash
docker compose up --build --force-recreate --detach
```

##  Stop Docker Compose and Remove Orphans

```bash
docker compose down --remove-orphans
```

##  Restart Docker Compose and View Logs

```bash
docker compose down --remove-orphans
docker compose up --build --force-recreate --detach
docker logs -f oan_app
```
