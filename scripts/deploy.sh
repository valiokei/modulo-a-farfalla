#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Engine and the Docker Compose plugin first." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required (docker compose)." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Create it from the template, then set the required secrets:" >&2
  echo "  cp .env.example .env" >&2
  exit 1
fi

docker compose --env-file .env config -q
docker compose --env-file .env up --build -d

http_port="$(awk -F= '$1 == "HTTP_PORT" { print $2; exit }' .env | tr -d '[:space:]')"
echo "Modulo a Farfalla is starting at http://localhost:${http_port:-8080}"
echo "Follow startup logs with: docker compose logs -f"
