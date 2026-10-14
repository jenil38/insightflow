#!/usr/bin/env bash
# Deletes the entire resource group setup.sh created - every resource inside
# it, in one command, so nothing keeps billing after a demo. This does not
# touch anything outside that resource group: not the Azure AD app
# registration used for GitHub OIDC (see docs/DEPLOY_AZURE.md), not your
# Vercel frontend, not the repository itself.
#
# Requires confirmation: run with no arguments to be asked to type the
# resource group's name back, or pass --yes to skip that for scripted use.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./vars.sh
source "$SCRIPT_DIR/vars.sh"

SKIP_CONFIRM=false
if [ "${1:-}" = "--yes" ]; then
  SKIP_CONFIRM=true
fi

if ! az group show --name "$RESOURCE_GROUP" &>/dev/null; then
  echo "Resource group $RESOURCE_GROUP does not exist - nothing to tear down."
  exit 0
fi

echo "This will permanently delete resource group '$RESOURCE_GROUP' and"
echo "everything in it: the container app, container registry, Container"
echo "Apps environment, and the PostgreSQL server (and all its data)."
echo

if [ "$SKIP_CONFIRM" = false ]; then
  read -r -p "Type the resource group name to confirm ($RESOURCE_GROUP): " confirmation
  if [ "$confirmation" != "$RESOURCE_GROUP" ]; then
    echo "Confirmation did not match. Nothing was deleted."
    exit 1
  fi
fi

echo "Deleting resource group $RESOURCE_GROUP (this runs in the background)..."
az group delete --name "$RESOURCE_GROUP" --yes --no-wait

echo "Delete started. Check progress any time with:"
echo "  az group show --name $RESOURCE_GROUP"
echo "(it will error out once deletion finishes, which is the expected end state)"
