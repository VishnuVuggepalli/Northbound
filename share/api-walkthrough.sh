#!/usr/bin/env bash
#
# Northbound API walkthrough — file → approve → apply a VLAN request, then comment.
#
# Browsers authenticate with the httpOnly session cookie (SameSite=Lax). API
# clients use the access_token the login response returns, as a Bearer header —
# that's what this script does.
#
# Usage:
#   NB_URL=http://localhost:8090 \
#   NB_ADMIN=admin NB_ADMIN_PW=admin123 \
#   ./api-walkthrough.sh
#
# Requires: curl, jq.
set -euo pipefail

NB_URL="${NB_URL:-http://localhost:8090}"
NB_ADMIN="${NB_ADMIN:-admin}"
NB_ADMIN_PW="${NB_ADMIN_PW:-admin123}"

command -v jq >/dev/null || { echo "need jq"; exit 1; }

api() {  # api METHOD PATH [json-body]
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -fsS -X "$method" "$NB_URL$path" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "$body"
  else
    curl -fsS -X "$method" "$NB_URL$path" -H "Authorization: Bearer $TOKEN"
  fi
}

echo "==> 1. Log in as $NB_ADMIN"
TOKEN=$(curl -fsS -X POST "$NB_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg u "$NB_ADMIN" --arg p "$NB_ADMIN_PW" '{username:$u,password:$p}')" \
  | jq -r '.access_token')
[[ -n "$TOKEN" && "$TOKEN" != "null" ]] || { echo "login failed"; exit 1; }
echo "    got token (${#TOKEN} chars)"

echo "==> 2. Pick a writable device"
DEVICE_ID=$(api GET /api/devices | jq -r '.[0].id')
echo "    device_id = $DEVICE_ID"

echo "==> 3. File a VLAN-create request"
REQ=$(api POST /api/requests/vlan "$(jq -n --arg d "$DEVICE_ID" \
  '{device_id:$d, action:"create", vlan_id:3997, name:"nb-demo",
    description:"created by api-walkthrough", reason:"demo"}')")
REQ_ID=$(echo "$REQ" | jq -r '.id')
echo "    request_id = $REQ_ID  status = $(echo "$REQ" | jq -r '.status')"

echo "==> 4. Approve it (admin only; no body)"
api POST "/api/requests/$REQ_ID/approve" | jq -r '"    status = \(.status)"'

echo "==> 5. Comment on the thread"
api POST "/api/requests/$REQ_ID/comments" \
  "$(jq -n '{body:"Applying now — VLAN 3997 is unused on this device."}')" >/dev/null
echo "    comment posted"

echo "==> 6. Apply"
echo "    (uncomment the next line to actually push to the device)"
# api POST "/api/requests/$REQ_ID/apply" | jq -r '"    status = \(.status)"'
#   On commit-confirm platforms the status becomes AWAITING_CONFIRM — then:
#   api POST "/api/requests/$REQ_ID/confirm" | jq -r '.status'

echo "==> 7. Read the timeline (transitions + comments)"
api GET "/api/requests/$REQ_ID/timeline" | jq -r '.[] | "    [\(.kind)] \(.actor_username // .actor // "system"): \(.body // (.from_status + " -> " + .to_status))"'

echo "done. (apply step left commented so this is read-safe by default.)"
