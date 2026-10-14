# Deploying the backend to Azure

A from-scratch walkthrough for deploying InsightFlow's backend to Azure
Container Apps, written for someone who has not used Azure before. The
frontend keeps running on Vercel exactly as it does today; only the backend
moves.

**What this costs and how to stop paying**: read the [Cost](#cost) section
before you start, and run `deploy/azure/teardown.sh` as soon as you are done
with a demo or a round of screenshots.

## What gets created

- **Resource group** - one container for everything below, so deleting it
  deletes the whole deployment in one step.
- **Azure Container Registry (ACR, Basic tier)** - stores the backend's
  Docker image.
- **Container Apps environment + Container App (Consumption plan)** - runs
  the image. Consumption plan scales to zero: when nothing is using it, you
  are not billed for compute.
- **Azure Database for PostgreSQL Flexible Server (Burstable B1ms)** - the
  database. This one does **not** scale to zero and is the main ongoing cost;
  see [Cost](#cost).

Nothing about your Vercel frontend or your GitHub repository changes except
one new workflow file and (optionally) three repository secrets.

## Prerequisites

1. **An Azure account.** [azure.microsoft.com/free](https://azure.microsoft.com/free)
   gives new accounts a free credit, which is enough to run this whole setup
   for a while. You will be asked for a card for identity verification; the
   resources here are cheap enough (see [Cost](#cost)) that accidentally
   leaving them running for a few days is not going to be a shock, but
   `teardown.sh` exists so you do not have to find that out.
2. **The Azure CLI**, installed locally:
   [learn.microsoft.com/cli/azure/install-azure-cli](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli).
   Confirm it works: `az --version`.
3. **Log in and pick your subscription:**
   ```bash
   az login
   az account list --output table
   az account set --subscription "<the subscription id or name from above>"
   ```
4. **A GitHub CLI or just your browser**, for setting repository secrets
   later (`gh` is convenient but not required).

## Step 1: pick unique names

Two names must be globally unique across *all of Azure*, not just your
account: the container registry name and the PostgreSQL server name. Open
[`deploy/azure/vars.sh`](../deploy/azure/vars.sh) and change `ACR_NAME` and
`POSTGRES_SERVER_NAME` to something unlikely to collide (e.g. add your name
or a random suffix: `insightflowacr7k2`). Leave everything else as the
default unless you have a reason to change it.

## Step 2: run setup.sh

Generate two secrets and find your Vercel URL first:

```bash
# A strong random password for the database admin account
export POSTGRES_ADMIN_PASSWORD="$(openssl rand -base64 24)"

# The key the backend uses to sign login tokens - not your Vercel URL, not
# a password you reuse anywhere, just random bytes
export JWT_SECRET="$(openssl rand -base64 48)"

# Optional: enables the AI Copilot and the tool-calling agent. Leave empty to
# deploy without them - every other feature works fine without a key.
export GROQ_API_KEY=""

# Your actual deployed frontend origin, no trailing slash
export FRONTEND_ORIGIN="https://your-app.vercel.app"
```

Then, from the repository root:

```bash
bash deploy/azure/setup.sh
```

This takes several minutes the first time (mostly the PostgreSQL server and
the first image build). It prints the backend's URL when it finishes. Save
that URL - you need it in Step 4.

**Save `POSTGRES_ADMIN_PASSWORD` somewhere** (a password manager, not another
file in this repo) if you want to connect to the database directly later;
the backend itself only needs it inside the Container App secret the script
already set.

## Step 3: set up GitHub OIDC for automated deploys

`.github/workflows/deploy-azure.yml` deploys new backend code without ever
storing an Azure password in GitHub. It authenticates with a federated
credential instead: GitHub proves who it is directly to Azure AD.

1. **Create an Azure AD app registration and a federated credential for this
   repo.** Replace `<github-org>/<repo>` with yours:

   ```bash
   APP_ID="$(az ad app create --display-name insightflow-deploy --query appId -o tsv)"
   az ad sp create-for-rbac --id "$APP_ID" --skip-assignment --output none 2>/dev/null || true

   az ad app federated-credential create \
     --id "$APP_ID" \
     --parameters '{
       "name": "insightflow-main-branch",
       "issuer": "https://token.actions.githubusercontent.com",
       "subject": "repo:<github-org>/<repo>:ref:refs/heads/main",
       "audiences": ["api://AzureADTokenExchange"]
     }'
   ```

   The `subject` above only allows the workflow to authenticate when it runs
   against the `main` branch. That is intentional - it is also why
   `deploy-azure.yml` cannot be triggered from a fork or a pull request
   branch, only from `main`, by someone who can push to it or trigger
   `workflow_dispatch` there.

2. **Give that app permission to manage your resource group:**

   ```bash
   SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
   az role assignment create \
     --assignee "$APP_ID" \
     --role Contributor \
     --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/insightflow-rg"
   ```

   (Use whatever `RESOURCE_GROUP` you actually set in `vars.sh` if you
   changed it from the default `insightflow-rg`.)

3. **Set three GitHub repository secrets** (Settings → Secrets and variables
   → Actions → New repository secret), or with the `gh` CLI:

   ```bash
   gh secret set AZURE_CLIENT_ID --body "$APP_ID"
   gh secret set AZURE_TENANT_ID --body "$(az account show --query tenantId -o tsv)"
   gh secret set AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID"
   ```

   None of these three values are secret in the sense of a password - they
   identify *which* app registration and subscription to use. What makes
   this safe without a password is the federated credential from step 1: AWS
   Azure only accepts the exchange from GitHub Actions runs matching that
   exact `subject`.

4. **Create a GitHub Environment named `production`** (Settings →
   Environments → New environment, name it `production`) if you want an
   extra manual-approval gate before every deploy. `deploy-azure.yml` targets
   this environment; if you skip creating it, GitHub just treats it as
   unprotected.

## Step 4: point Vercel at the new backend

In your Vercel project settings, set the `VITE_API_BASE` environment
variable to the backend URL `setup.sh` printed (e.g.
`https://insightflow-backend.<something>.northeurope.azurecontainerapps.io`),
then redeploy the frontend (Vercel → Deployments → Redeploy, or push any
commit).

## Step 5: deploy backend code changes

From now on, deploying a backend change is:

```bash
git push origin main
```

then, from the GitHub Actions tab, run **Deploy backend to Azure**
manually (`workflow_dispatch` - it never runs on its own). Watch the run; its
last step prints the deployed URL again.

## Step 6: verify

```bash
curl https://<your-backend-url>/health
```

Expect something like:

```json
{"status":"ok","version":"1.0.0","environment":"production","database":"ok",
 "features":{"copilot":false,"email_delivery":false}, ...}
```

`"copilot": false` is correct if you left `GROQ_API_KEY` empty - that is the
honest "not configured" state, not an error. `"database": "ok"` confirms the
Container App actually reached the PostgreSQL server.

## Required environment variables

Everything the backend reads is an environment variable - nothing is
hard-coded, and `setup.sh` sets all of these as Container App secrets or
plain env vars already. Listed here for reference, in case you ever manage
the Container App directly instead of through `setup.sh`:

| Variable | Set by setup.sh as | Required | What it's for |
|---|---|---|---|
| `DATABASE_URL` | secret | Yes | PostgreSQL connection string, built from the server `setup.sh` creates |
| `JWT_SECRET` | secret | Yes | Signs login tokens. Must be the same value across restarts or existing sessions invalidate |
| `GROQ_API_KEY` | secret | No | Enables the AI Copilot and tool-calling agent. Empty = those features show "not configured" |
| `CORS_ORIGINS` | env var | Yes | Comma-separated list of origins allowed to call the API. Must include your exact Vercel origin |
| `FRONTEND_URL` | env var | No | Used in password-reset/verification email links |
| `ENVIRONMENT` | env var | Yes | Set to `production` by setup.sh - enables stricter checks (e.g. `JWT_SECRET` becomes mandatory) |
| `GROQ_MODEL` | env var | No | Defaults to a current Groq model; only matters if `GROQ_API_KEY` is set |
| `DEBUG` | env var | No | `false` in production |

## Cost

Prices are approximate (West Europe/North Europe, pay-as-you-go, late 2026)
and change over time - check the
[Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)
for current numbers.

| Resource | Idle | Active | Notes |
|---|---|---|---|
| Container Apps (Consumption) | **~$0** | a few cents/hour while handling traffic | Scales to zero replicas after inactivity - this is the whole point of the Consumption plan |
| Container Registry (Basic) | ~$0.17/day (~$5/month) | same | Flat fee regardless of traffic; the cheapest SKU |
| PostgreSQL Flexible Server (Burstable B1ms) | **~$12-15/month** | same, plus storage | **Does not scale to zero.** This runs continuously once created and is the cost that matters if you forget to tear down |

**If you only need this for a demo or screenshots**: run `setup.sh`, do what
you need, then run `deploy/azure/teardown.sh` the same day. The Container
Registry and PostgreSQL costs above are per-month rates; a few hours costs a
few cents.

```bash
bash deploy/azure/teardown.sh
```

This deletes the entire resource group - the container app, the registry,
the Container Apps environment, and the PostgreSQL server with all its data -
after asking you to type the resource group's name to confirm. It does
**not** delete the Azure AD app registration from Step 3 (that costs nothing
to leave, and you'll want it again next time) or anything on Vercel.

## Troubleshooting

- **`setup.sh` fails on `az acr create` or `az postgres flexible-server
  create` with a name-already-taken error**: those two names are global
  across Azure. Go back to Step 1 and pick different ones in `vars.sh`.
- **`/health` returns `"database": "unreachable"`**: usually the PostgreSQL
  firewall. `setup.sh` opens access for Azure services
  (`--public-access 0.0.0.0`, Azure's special value for that, not the open
  internet) - if you changed that, the container app cannot reach the
  database.
- **The deploy workflow fails to log in**: double check the `subject` in the
  federated credential matches your actual `<github-org>/<repo>` and branch
  exactly, and that all three `AZURE_*` secrets are set.
- **CORS errors in the browser console**: `CORS_ORIGINS` must match your
  Vercel origin exactly, including `https://` and with no trailing slash.
