"""Evaluation harness for the tool-calling agent (Phase 3).

Run from `backend/` as `python -m evals ...`. This package is deliberately not
under `app/`: nothing in the application imports it, no route reaches it, and it
is excluded from the production image (see `backend/.dockerignore`). See
`backend/PHASE3_PLAN.md` for the design and what is deliberately not measured.
"""
