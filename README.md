# biologic

PUDA edge service for BioLogic potentiostats (SP, VSP, VMP, and similar EC-Lab instruments).

Connects to NATS, advertises electrochemical techniques as machine commands, and talks to the instrument over Ethernet.

## Prerequisites

- Windows host with the BioLogic EC-Lab / `puda-biologic` native libraries
- Python 3.14+ and `uv` (for baremetal)
- Docker and Docker Compose (optional)
- Potentiostat reachable on the network

## Environment Setup

From repo root:

```bash
cp .env.example .env
```

Edit `.env` and fill in:

- `MACHINE_ID` — machine identifier (default: `biologic`)
- `NATS_SERVERS` — comma-separated NATS server URLs
- `BIOLOGIC_IP` — Ethernet address of the potentiostat

## Run With Docker (Recommended)

All commands below run from repo root.

Build and start:

```bash
docker compose -f compose.yml up -d --build
```

View logs:

```bash
docker compose -f compose.yml logs -f
```

Stop:

```bash
docker compose -f compose.yml down
```

## Run Baremetal (uv)

```bash
uv sync
uv run python main.py
```

On Windows you can also double-click `start_edge.bat`.

## Build and Push Image (GHCR)

Login:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

Build and push:

```bash
docker compose -f compose.yml build
docker compose -f compose.yml push
```

## Notes

- Docker build context is the repository root.
- Dockerfile path is `Dockerfile`.
- `MACHINE_ID` in `.env` is used for NATS subject routing and Docker image/container naming.
- The EC-Lab driver is Windows-only. Linux can load the edge process but cannot talk to hardware.
