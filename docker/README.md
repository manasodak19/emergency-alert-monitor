# Docker Architecture & Configuration

All container configurations, reverse proxy definitions, and Compose orchestrations for the **Emergency Alert Monitor** system are isolated inside this directory.

```
docker/
├── compose.yaml                    # Multi-container orchestration (backend + nginx)
├── .dockerignore                   # Build exclusion rules
├── backend/
│   ├── Dockerfile                  # Python 3.11-slim container for Flask backend
│   └── Dockerfile.dockerignore     # BuildKit context ignore file
└── nginx/
    └── nginx.conf                  # Nginx reverse proxy configuration (Port 80 -> http://backend:5000)
```

## Service Overview

| Service | Container Image | Host Port | Container Port | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| **`nginx`** | `nginx:stable-alpine` | `80` | `80` | Reverse proxy gateway, client header forwarding, isolation layer |
| **`backend`** | `emergency-alert-monitor:local` | *None* | `5000` | Flask API application, isolated on `eam-net` bridge network |

---

## Commands

### Option A: Running from Repository Root (Recommended)

```bash
# Build and start services in background
docker compose -f docker/compose.yaml up --build -d

# Check service status and health checks
docker compose -f docker/compose.yaml ps

# View live logs
docker compose -f docker/compose.yaml logs -f

# Stop services (keeps your database volumes intact)
docker compose -f docker/compose.yaml down

# Stop and wipe volumes (fresh database next start)
docker compose -f docker/compose.yaml down -v
```

### Option B: Running from inside the `docker/` Directory

```bash
cd docker

docker compose up --build -d
docker compose ps
docker compose logs -f
docker compose down
```

---

## Single Container Build (Optional)

```bash
docker build -f docker/backend/Dockerfile -t emergency-alert-monitor:local .
```
