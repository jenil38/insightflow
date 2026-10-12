"""CV evaluation script for the natural-language tool-calling agent.

Separate from `backend/evals/` (the Phase 3 cassette harness, which replays
recorded responses against the agent code for CI regression gating). This
package makes live calls to measure the deployed model's accuracy, latency
and cost. See `eval_agent.py`.
"""
