#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCHMATE_BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${RESEARCH_AGENT_TOKEN:?set RESEARCH_AGENT_TOKEN}"
JOB_ID="${1:?usage: kb_job.sh JOB_ID}"

curl -sS \
  -H "X-Internal-Token: ${TOKEN}" \
  "${BASE_URL}/v1/knowledge/jobs/${JOB_ID}"
