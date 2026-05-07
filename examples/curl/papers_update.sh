#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCHMATE_BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${RESEARCH_AGENT_TOKEN:?set RESEARCH_AGENT_TOKEN}"
PAPER_ID="${1:?usage: papers_update.sh PAPER_ID}"
RATING="${2:-4.5}"

curl -sS \
  -H "X-Internal-Token: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X PATCH \
  -d "{\"rating\":${RATING},\"tags\":[\"read\"]}" \
  "${BASE_URL}/v1/papers/${PAPER_ID}"
