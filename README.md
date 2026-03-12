# biologic

Monorepo for the Biologic edge service.

## What It Does

- Runs the Biologic machine edge service.
- Connects to NATS and translates commands into machine actions.
- Communicates with the Biologic device over the network (IP).

## Prerequisites

- Docker and Docker Compose installed
- Python 3.14+ and `uv` (for baremetal mode)
- Biologic device reachable on the network

## Environment Setup

From repo root:

```bash
cp edge/.env.example edge/.env
```

Edit `edge/.env` and configure:

- `MACHINE_ID`
- `NATS_SERVERS`
- `BIOLOGIC_IP`

## Run With Docker (Recommended)

All commands below are run from repo root.

Build and start:

```bash
docker compose -f edge/compose.yml up -d --build
```

View logs:

```bash
docker compose -f edge/compose.yml logs -f
```

Stop:

```bash
docker compose -f edge/compose.yml down
```

## Run Baremetal (uv)

From repo root:

```bash
uv sync --all-packages
uv run --package biologic-edge python edge/main.py
```

## Build and Push Image (GHCR)

Login:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

Build:

```bash
docker compose -f edge/compose.yml build
```

Push:

```bash
docker push ghcr.io/PUDAP/biologic-edge:latest
```

Or with Compose:

```bash
docker compose -f edge/compose.yml push
```

## Notes

- Docker build context is workspace root (`..` in `edge/compose.yml`).
- Dockerfile path is `edge/Dockerfile`.
