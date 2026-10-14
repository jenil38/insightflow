#!/usr/bin/env bash
# Provisions everything InsightFlow's backend needs on Azure: a resource
# group, Azure Container Registry, a Container Apps environment, a PostgreSQL
# Flexible Server + database, and the container app itself - then builds and
# deploys the first image so the app create step has something real to run.
#
# Safe to re-run: every resource is created only if it does not already exist
# (the one genuinely non-idempotent Azure CLI call here, `postgres
# flexible-server create`, is guarded the same way). Re-running after a
# partial failure picks up where it left off instead of erroring on
# already-created resources.
#
# Requires: the Azure CLI (`az`), logged in (`az login`) with the subscription
# you want to use already selected (`az account set --subscription <id>`).
#
# Secrets are never written to this file or to any file in this repo. Export
# them in your shell first:
#
#   export POSTGRES_ADMIN_PASSWORD='...'   # choose a strong password
#   export JWT_SECRET='...'                # e.g. `openssl rand -base64 48`
#   export GROQ_API_KEY=''                 # optional - blank disables the AI features
#   export FRONTEND_ORIGIN='https://your-app.vercel.app'
#
# Then run:
#
#   bash deploy/azure/setup.sh
#
# See docs/DEPLOY_AZURE.md for the full walkthrough, including generating
# JWT_SECRET and finding FRONTEND_ORIGIN.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./vars.sh
source "$SCRIPT_DIR/vars.sh"

# --------------------------------------------------------------- required env

required_vars=(POSTGRES_ADMIN_PASSWORD JWT_SECRET FRONTEND_ORIGIN)
missing=()
for v in "${required_vars[@]}"; do
  if [ -z "${!v:-}" ]; then
    missing+=("$v")
  fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "Missing required environment variable(s): ${missing[*]}" >&2
  echo "Export them and re-run. See the comment at the top of this script." >&2
  exit 1
fi

# GROQ_API_KEY is genuinely optional - an empty value disables the AI
# Copilot/agent and nothing else. Default it so set -u does not trip below.
GROQ_API_KEY="${GROQ_API_KEY:-}"

# --------------------------------------------------------------- prerequisites

# Both are one-time, subscription-wide, and safe to repeat: `extension add
# --upgrade` is a no-op update if already installed, and `provider register`
# just re-confirms an already-registered provider.
echo "Checking the containerapp CLI extension and resource providers..."
az extension add --name containerapp --upgrade --output none
az provider register --namespace Microsoft.ContainerRegistry --wait
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.DBforPostgreSQL --wait

echo "== InsightFlow Azure setup =="
echo "Resource group:     $RESOURCE_GROUP ($LOCATION)"
echo "Container registry:  $ACR_NAME"
echo "Container app:       $CONTAINER_APP_NAME"
echo "Postgres server:      $POSTGRES_SERVER_NAME"
echo

# ------------------------------------------------------------- resource group

if ! az group show --name "$RESOURCE_GROUP" &>/dev/null; then
  echo "Creating resource group $RESOURCE_GROUP..."
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
else
  echo "Resource group $RESOURCE_GROUP already exists, skipping."
fi

# --------------------------------------------------------------------- ACR

if ! az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Creating container registry $ACR_NAME..."
  az acr create \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --sku Basic \
    --output none
else
  echo "Container registry $ACR_NAME already exists, skipping."
fi

ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)"

# ----------------------------------------------------- build the first image

# ACR Tasks builds in the cloud, so this needs no local Docker install and
# matches exactly how the GitHub Actions workflow builds later on.
if [ -n "${IMAGE_SOURCE:-}" ]; then
  # Subscriptions that block ACR Tasks (e.g. Azure for Students) cannot use
  # az acr build, so import an image that CI already built and published.
  echo "Importing $IMAGE_SOURCE into $ACR_NAME..."
  az acr import \
    --name "$ACR_NAME" \
    --source "$IMAGE_SOURCE" \
    --image "$IMAGE_NAME:$IMAGE_TAG" \
    --force \
    --output none
else
  echo "Building the backend image (this can take a few minutes the first time)..."
  az acr build \
    --registry "$ACR_NAME" \
    --image "$IMAGE_NAME:$IMAGE_TAG" \
    --file backend/Dockerfile \
    "$SCRIPT_DIR/../../backend" \
    --output none
fi

# ------------------------------------------------------ Container Apps env

if ! az containerapp env show --name "$CONTAINERAPPS_ENV" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Creating Container Apps environment $CONTAINERAPPS_ENV..."
  az containerapp env create \
    --name "$CONTAINERAPPS_ENV" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
else
  echo "Container Apps environment $CONTAINERAPPS_ENV already exists, skipping."
fi

# -------------------------------------------------------------- PostgreSQL

if ! az postgres flexible-server show --name "$POSTGRES_SERVER_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Creating PostgreSQL Flexible Server $POSTGRES_SERVER_NAME (Burstable B1ms)..."
  # --public-access 0.0.0.0 is Azure's special value for "allow access from
  # any Azure service" - not the open internet. Container Apps consumption
  # plan has no fixed egress IP to allow individually without a VNet, which
  # is the right next step for a real production deployment but adds cost
  # and complexity this demo setup deliberately avoids. See docs/DEPLOY_AZURE.md.
  az postgres flexible-server create \
    --name "$POSTGRES_SERVER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --admin-user "$POSTGRES_ADMIN_USER" \
    --admin-password "$POSTGRES_ADMIN_PASSWORD" \
    --sku-name Standard_B1ms \
    --tier Burstable \
    --storage-size 32 \
    --version 16 \
    --public-access 0.0.0.0 \
    --yes \
    --output none
else
  echo "PostgreSQL server $POSTGRES_SERVER_NAME already exists, skipping."
fi

if ! az postgres flexible-server db show --server-name "$POSTGRES_SERVER_NAME" --resource-group "$RESOURCE_GROUP" --database-name "$POSTGRES_DB_NAME" &>/dev/null; then
  echo "Creating database $POSTGRES_DB_NAME..."
  az postgres flexible-server db create \
    --server-name "$POSTGRES_SERVER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --database-name "$POSTGRES_DB_NAME" \
    --output none
else
  echo "Database $POSTGRES_DB_NAME already exists, skipping."
fi

POSTGRES_HOST="$(az postgres flexible-server show --name "$POSTGRES_SERVER_NAME" --resource-group "$RESOURCE_GROUP" --query fullyQualifiedDomainName -o tsv)"
DATABASE_URL="postgresql+psycopg2://${POSTGRES_ADMIN_USER}:${POSTGRES_ADMIN_PASSWORD}@${POSTGRES_HOST}:5432/${POSTGRES_DB_NAME}?sslmode=require"

# ---------------------------------------------------------------- container app

if ! az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Creating container app $CONTAINER_APP_NAME..."
  az containerapp create \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$CONTAINERAPPS_ENV" \
    --image "$ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG" \
    --target-port 8000 \
    --ingress external \
    --min-replicas 0 \
    --max-replicas 2 \
    --cpu 0.5 \
    --memory 1.0Gi \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-identity system \
    --secrets \
      "database-url=$DATABASE_URL" \
      "jwt-secret=$JWT_SECRET" \
      "groq-api-key=$GROQ_API_KEY" \
    --env-vars \
      "ENVIRONMENT=production" \
      "DEBUG=false" \
      "DATABASE_URL=secretref:database-url" \
      "JWT_SECRET=secretref:jwt-secret" \
      "GROQ_API_KEY=secretref:groq-api-key" \
      "GROQ_MODEL=openai/gpt-oss-20b" \
      "CORS_ORIGINS=$FRONTEND_ORIGIN" \
      "FRONTEND_URL=$FRONTEND_ORIGIN" \
    --output none
else
  echo "Container app $CONTAINER_APP_NAME already exists; updating its secrets, env vars and image instead of recreating it."
  az containerapp secret set \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --secrets \
      "database-url=$DATABASE_URL" \
      "jwt-secret=$JWT_SECRET" \
      "groq-api-key=$GROQ_API_KEY" \
    --output none
  az containerapp update \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG" \
    --set-env-vars \
      "ENVIRONMENT=production" \
      "DEBUG=false" \
      "DATABASE_URL=secretref:database-url" \
      "JWT_SECRET=secretref:jwt-secret" \
      "GROQ_API_KEY=secretref:groq-api-key" \
      "GROQ_MODEL=openai/gpt-oss-20b" \
      "CORS_ORIGINS=$FRONTEND_ORIGIN" \
      "FRONTEND_URL=$FRONTEND_ORIGIN" \
    --output none
fi

APP_URL="$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"

echo
echo "== Done =="
echo "Backend URL:  https://$APP_URL"
echo "Health check: curl https://$APP_URL/health"
echo
echo "Next: point your Vercel frontend's VITE_API_BASE at https://$APP_URL"
echo "      and set up .github/workflows/deploy-azure.yml (see docs/DEPLOY_AZURE.md)"
echo "      so future backend changes redeploy with one click."
