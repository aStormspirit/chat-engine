#!/usr/bin/env bash
# Deploys APP_IMAGE with docker compose and rolls back if the healthcheck fails.
#
# Usage:  APP_IMAGE=<dockerhub-user>/<repo>:<tag> ./deploy.sh
# When REGISTRY_USER is set, the registry password is read from stdin.
set -euo pipefail

: "${APP_IMAGE:?APP_IMAGE is required}"
export APP_IMAGE

cd "$(dirname "$0")"

for required in .env accounts.json docker-compose.yml; do
  if [[ ! -f $required ]]; then
    echo "Missing $(pwd)/$required" >&2
    exit 1
  fi
done
mkdir -p sessions

# Same rule as Docker: the first path component is a registry host only if it
# looks like one; otherwise the image lives on Docker Hub.
registry=()
first_component="${APP_IMAGE%%/*}"
if [[ $APP_IMAGE == */* && ($first_component == *.* || $first_component == *:* || $first_component == localhost) ]]; then
  registry=("$first_component")
fi

if [[ -n ${REGISTRY_USER:-} ]]; then
  docker login "${registry[@]}" --username "$REGISTRY_USER" --password-stdin
  trap 'docker logout "${registry[@]}" >/dev/null' EXIT
fi

previous="$(sed -n 's/^APP_IMAGE=//p' .env | tail -n 1)"

echo "Deploying ${APP_IMAGE} (previous: ${previous:-none})"
docker compose pull app

if ! docker compose up -d --no-build --wait --wait-timeout 120 app; then
  echo "Deployment failed, recent logs:" >&2
  docker compose logs --tail 100 app >&2 || true
  if [[ -n $previous && $previous != "$APP_IMAGE" ]]; then
    echo "Rolling back to ${previous}" >&2
    APP_IMAGE="$previous" docker compose up -d --no-build app
  fi
  exit 1
fi

if grep -q '^APP_IMAGE=' .env; then
  sed -i "s|^APP_IMAGE=.*|APP_IMAGE=${APP_IMAGE}|" .env
else
  printf '\nAPP_IMAGE=%s\n' "$APP_IMAGE" >> .env
fi

docker image prune -f >/dev/null
echo "Deployed ${APP_IMAGE}"
