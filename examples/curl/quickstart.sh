#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCHMATE_BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${RESEARCH_AGENT_TOKEN:?set RESEARCH_AGENT_TOKEN}"
MESSAGE="${1:-请简短说明 ResearchMate 当前能力。}"

curl -sS -H "X-Internal-Token: ${TOKEN}" "${BASE_URL}/v1/readyz"
echo

SESSION_ID="$(
  curl -sS \
    -H "X-Internal-Token: ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"user_id":"local"}' \
    "${BASE_URL}/v1/sessions" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["session_id"])'
)"

curl -N -sS \
  -H "X-Internal-Token: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"${MESSAGE}\"}" \
  "${BASE_URL}/v1/chat/${SESSION_ID}"
