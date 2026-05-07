#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCHMATE_BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${RESEARCH_AGENT_TOKEN:?set RESEARCH_AGENT_TOKEN}"
MEMORY_ID="${1:?usage: memory_update.sh MEMORY_ID [content]}"
CONTENT="${2:-updated memory content}"

curl -sS \
  -H "X-Internal-Token: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X PATCH \
  -d "{\"content\":\"${CONTENT}\"}" \
  "${BASE_URL}/v1/memory/${MEMORY_ID}"
