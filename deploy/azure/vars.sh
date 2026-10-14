#!/usr/bin/env bash
# Shared resource names for setup.sh and teardown.sh, so the two scripts can
# never drift apart and target different resources by accident.
#
# Edit these before the first run of setup.sh. If you change
# CONTAINER_APP_NAME, ACR_NAME or RESOURCE_GROUP here, make the same edit in
# .github/workflows/deploy-azure.yml - the workflow does not read this file
# (it runs on GitHub's side, not against your checkout's filesystem state),
# so the two have to be kept in sync by hand.
#
# Nothing in this file is a secret. Real secrets (database password, JWT
# signing key, Groq API key) are never written to a file in this repo; they
# are read from environment variables you export yourself before running
# setup.sh, and stored only in Azure Container Apps' own secret store.

# Where everything lives. One resource group makes teardown.sh a single
# command that cannot leave anything behind.
RESOURCE_GROUP="${RESOURCE_GROUP:-insightflow-rg}"
LOCATION="${LOCATION:-northeurope}"

# Azure Container Registry. Names must be globally unique across all of Azure,
# lowercase alphanumeric only - change this to something unique to you before
# the first run.
ACR_NAME="${ACR_NAME:-insightflowacr}"

# Container Apps environment (the logical grouping Container Apps run inside)
# and the container app itself.
CONTAINERAPPS_ENV="${CONTAINERAPPS_ENV:-insightflow-env}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-insightflow-backend}"

# PostgreSQL Flexible Server. Server names are also globally unique across
# Azure - change this too.
POSTGRES_SERVER_NAME="${POSTGRES_SERVER_NAME:-insightflow-pg}"
POSTGRES_DB_NAME="${POSTGRES_DB_NAME:-insightflow}"
POSTGRES_ADMIN_USER="${POSTGRES_ADMIN_USER:-insightflow_admin}"

# Image name/tag used both by setup.sh's initial build and by the deploy
# workflow's subsequent ones.
IMAGE_NAME="${IMAGE_NAME:-insightflow-backend}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
