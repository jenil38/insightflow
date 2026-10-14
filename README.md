# InsightFlow

End-to-end data analytics platform that takes a CSV, Excel, or JSON upload through profiling, cleaning, visualization, machine learning, explainability, and AI-powered conversation, all from a single workspace.

## Features

**Data Management**: Upload CSV/Excel/JSON, profile columns automatically, get quality scores with actionable warnings, and clean data with a preview-before-apply workflow. Original uploads are preserved; cleaning creates a separate copy you can revert at any time.

**Analytics**: Auto-generated dashboards with KPIs, time series, distributions, and category breakdowns. Custom query builder for ad-hoc analysis with configurable aggregations, dimensions, filters, and chart types. Saveable dashboard layouts.

**Machine Learning**: Leaderboard of 12+ models (Random Forest, XGBoost, LightGBM, CatBoost, SVM, etc.) with automatic hyperparameter tuning. Leak-free pipeline using `ColumnTransformer` + `OneHotEncoder` inside sklearn `Pipeline` so encoding fits only on training data. Stratified splits, cross-validation, baseline comparisons, and reproducibility metadata on every run.

**Explainability**: Feature importance via model-native methods and SHAP, with one-hot importance aggregated back to original columns. Confusion matrices for classifiers, actual-vs-predicted and residual plots for regressors.

**AI Copilot**: LLM-powered data Q&A grounded in computed statistics, not raw data. Prompt-injection defenses, conversation history, and smart suggested questions derived from the actual dataset. Provider-agnostic with circuit breaker for reliability.

**Guided Analysis**: One-click pipeline that chains profiling, quality assessment, cleaning, analytics, training, explainability, and summarization. Each step reports its real outcome and duration.

**PDF Reports**: Downloadable reports with profile, quality scores, analytics, and model results.

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic v2 |
| ML | scikit-learn, XGBoost, LightGBM, CatBoost, SHAP |
| Frontend | React 18, Vite, TailwindCSS, TanStack Query + Table, Recharts, React Hook Form + Zod |
| Infrastructure | Docker Compose, PostgreSQL (prod), SQLite (dev), nginx |

## Quick Start

### Local Development

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

```bash
# Frontend
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open http://localhost:5173. The API runs on http://localhost:8000.

### Docker

```bash
cp .env.docker.example .env
# Edit .env: set JWT_SECRET and POSTGRES_PASSWORD
docker compose up --build
```

Open http://localhost:5173. Backend, frontend, and PostgreSQL run as separate services.

## Project Structure

```
backend/
  app/
    core/          # Config, exceptions, logging, middleware, serialization
    services/      # Business logic (ML, chat, cleaning, profiling, etc.)
    *.py           # Route modules (datasets, ml, chat, cleaning, etc.)
  alembic/         # Database migrations
  tests/           # 106 tests (auth, datasets, ML pipeline, security)
frontend/
  src/
    api/           # Axios client and endpoint functions
    app/           # Providers (auth, theme, query), router
    components/    # Shared UI kit (30+ accessible components)
    features/      # Feature panels (explorer, models, copilot, etc.)
    pages/         # Route pages (login, register, datasets, workspace)
    lib/           # Formatting utilities
```

## Architecture Highlights

- **No data leakage**: Encoding and imputation happen inside `sklearn.Pipeline` via `ColumnTransformer`, fitted only on training data
- **Per-model isolation**: One failing estimator is recorded and skipped, not an abort of the entire leaderboard
- **Multi-tenant security**: Every dataset endpoint verifies ownership; 106 tests include cross-tenant isolation checks
- **Prompt injection defense**: Dataset content is fenced as untrusted data in the LLM system prompt, with regex-based detection as defense in depth
- **Circuit breaker**: LLM provider failures trip a circuit breaker to prevent cascading timeouts
- **Non-destructive cleaning**: Original upload is always preserved; cleaning writes a copy; revert restores the original
- **Accessible frontend**: WAI-ARIA tabs, focus-trapped modals, skip-to-content link, keyboard navigation, screen reader announcements, light/dark theme

## Configuration

All configuration is via environment variables. See [`backend/.env.example`](backend/.env.example) for the full list.

| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET` | Yes (prod) | Signing key for auth tokens |
| `DATABASE_URL` | No | Defaults to SQLite for dev |
| `GROQ_API_KEY` | No | Enables the AI Copilot (Groq/OpenAI-compatible) |
| `CORS_ORIGINS` | No | Comma-separated allowed origins |
| `MAX_UPLOAD_SIZE_MB` | No | Upload size limit (default: 50) |

## Testing

```bash
cd backend
python -m pytest tests/ -v
```

106 tests covering authentication, dataset CRUD, ML pipeline (training, history, explainability, reports), data quality, cleaning, analytics, security (tenant isolation, inactive users, password reset), and file validation.

## Agent evaluation

`backend/evals/` is a harness that scores the tool-calling agent on 55 fixed cases
(read-only questions, tool arguments, out-of-scope questions, action behaviour, and
prompt-injection phrasings). It runs the real agent code with only the model swapped
for a live, recorded or replayed provider. See `backend/PHASE3_PLAN.md` for the design.

```bash
cd backend
python -m evals list                                            # the cases
python -m evals run --mode replay --tags all --check-baseline   # what CI runs
python -m evals run --mode live --tags smoke --repeats 3        # real model, for measuring; needs GROQ_API_KEY
python -m evals run --mode record --tags all                    # re-record cassettes AND produce a baseline candidate
python -m evals compare evals/baselines/<model>.json evals/results/<run>.json
python -m evals baseline --accept evals/results/<record-run>.json [--allow-regression]
python -m evals rescore evals/results/<run>.json                # re-apply scorers to stored records, no model call
```

- **CI runs replay only.** Live and record spend the Groq key and are limited to
  8,000 tokens a minute, so they are run by hand and paced (`--tpm`, default 6,000).
- **Replay proves the code around the model, not the model.** Cassettes are keyed on
  the full request, so a change to the system prompt, a tool description, or a tool's
  output makes replay fail as a stale cassette. That is the signal to run live.
- **The baseline and the cassettes describe the same run.** `baseline --accept` takes
  only a complete, error-free **record** run (not live, replay, partial, errored or
  budget-stopped), and refuses to overwrite a baseline with one that fails cases the
  current baseline passes unless you pass `--allow-regression`. A baseline is one
  repeat of each case, matching the one repeat CI replays.
- **Changing the prompt:**
  1. Edit it. `run --mode live --repeats 3` and `compare` it against the baseline to see
     the effect. This is measurement only; a live result cannot become the baseline.
  2. If the change is wanted, `run --mode record --tags all` (one repeat) rewrites the
     cassettes and produces the new baseline candidate; `compare` it, then
     `baseline --accept` it. Commit cassettes and baseline together.
  3. If you record with `--repeats N` for some reason, replay with `--repeats N` too;
     the baseline check reports a repeats mismatch explicitly.
- **Re-recording one case** (its question changed, say): `run --mode record --cases <id>`
  then `merge evals/results/<full-record>.json evals/results/<one-case>.json`, then
  `rescore` and `baseline --accept` the merged result. Both must be record runs with the
  same model, prompt and tools.
- **Replay fails on any error.** A stale cassette, an infrastructure error or a harness
  error in a replay is exit 1, with or without `--check-baseline`; a violated invariant
  is reported before all of those.
- **Record on the pinned stack** (Python 3.12 and `requirements.txt`): tool outputs
  depend on the pandas version, so cassettes recorded on a different one replay as stale.
- **Not measured:** whether free-text answers are faithful or good. There is no judge
  model; a passing run can still contain a poor answer.

## MCP server

`backend/mcp_server.py` exposes the same 13 tools the chat agent uses (11 read-only,
2 action) to any MCP client - Claude Desktop, an IDE - over stdio, so it can analyse an
InsightFlow dataset directly. It is a thin adapter: every tool calls
`app.services.tool_registry.execute_tool`, the same function the agent calls, so
behaviour and argument validation are defined once, in the registry.

It runs locally against your own InsightFlow database (whatever `DATABASE_URL` your
environment or `.env` already has) and acts as one user, named by `INSIGHTFLOW_USER_ID`.
A dataset id you do not own is refused the same way the REST API refuses it.
`apply_cleaning` and `train_model` are never executed from here: both return a
`pending_confirmation` payload describing what calling them for real would do, the
same approval gate the chat agent's confirmation card uses. To actually run one,
approve it in the agent chat or use the dataset's cleaning/training endpoint.

```bash
# from the repository root, not from backend/ - the module path is backend.mcp_server
INSIGHTFLOW_USER_ID=1 python -m backend.mcp_server
```

Example `claude_desktop_config.json` entry:

```json
{
  "mcpServers": {
    "insightflow": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "/absolute/path/to/insightflow",
      "env": {
        "INSIGHTFLOW_USER_ID": "1",
        "DATABASE_URL": "sqlite:///./insightflow.db"
      }
    }
  }
}
```
## Deploying to Azure

The backend can run on Azure Container Apps (Consumption plan, scale to
zero) with PostgreSQL Flexible Server, deployed via a manual-only GitHub
Actions workflow using OIDC (no stored Azure password). See
[`docs/DEPLOY_AZURE.md`](docs/DEPLOY_AZURE.md) for the full walkthrough,
including cost and teardown.

## License

MIT
