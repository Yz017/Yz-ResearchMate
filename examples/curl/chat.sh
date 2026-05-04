#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCHMATE_BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${RESEARCH_AGENT_TOKEN:?set RESEARCH_AGENT_TOKEN}"
SESSION_ID="${1:?usage: chat.sh SESSION_ID [message]}"
MESSAGE="${2:-请简短说明 ResearchMate 当前能力。}"

curl -N -sS \
  -H "X-Internal-Token: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"${MESSAGE}\"}" \
  "${BASE_URL}/v1/chat/${SESSION_ID}"
