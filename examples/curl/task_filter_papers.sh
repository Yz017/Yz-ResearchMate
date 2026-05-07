#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCHMATE_BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${RESEARCH_AGENT_TOKEN:?set RESEARCH_AGENT_TOKEN}"
QUERY="${1:-RAG agent shortlist}"

curl -sS \
  -H "X-Internal-Token: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"kind\":\"filter-papers\",\"user_id\":\"local\",\"params\":{\"query\":\"${QUERY}\",\"top_n\":50,\"max_iter\":3}}" \
  "${BASE_URL}/v1/tasks/run"
