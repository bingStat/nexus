#!/bin/sh
# Nexus Shell Agent v2 for N1 (Pure Shell)
# Features: Auth headers, last_seen, fail/complete status, safe JSON output

API_URL="${NEXUS_API_URL:-https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1}"
API_KEY="${NEXUS_API_KEY:-}"
DEVICE_ID="${DEVICE_ID:-n1}"
DEVICE_NAME="${DEVICE_NAME:-$DEVICE_ID}"
POLL_SEC=2
HB_SEC=15
LAST_HB=0

echo "[Agent] Starting Pure Shell Agent for [$DEVICE_ID]..."
if [ -n "$API_KEY" ]; then
    echo "[Agent] API Key authentication enabled."
fi

# Function to build curl auth headers
get_headers() {
    if [ -n "$API_KEY" ]; then
        echo -H "Authorization: Bearer $API_KEY" -H "apikey: $API_KEY"
    fi
}

get_now_iso() {
    # Generate ISO8601 UTC timestamp
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

get_now_epoch() {
    date +%s
}

while true; do
    NOW=$(get_now_epoch)
    
    # Heartbeat every HB_SEC seconds
    if [ $((heartbeat_counter % 5)) -eq 0 ]; then
        curl -s -X POST "$API_URL/devices" \
             -H "Content-Type: application/json" \
             -H "Prefer: resolution=merge-duplicates" \
             $(get_headers) \
             -d "{\"device_id\":\"$DEVICE_ID\",\"name\":\"$DEVICE_NAME\",\"last_seen\":\"now()\"}" >/dev/null &
    fi
    heartbeat_counter=$((heartbeat_counter + 1))

    # Fetch 1 pending command
    # Using simple grep for JSON parsing (assuming standard PostgREST array output format)
    RESP=$(curl -s "$API_URL/commands?status=eq.pending&target_device=eq.$DEVICE_ID&order=created_at.asc&limit=1" -H "Content-Type: application/json" $(get_headers))
    
    # Check if empty array or error
    if [ "$RESP" != "[]" ] && [ -n "$RESP" ] && echo "$RESP" | grep -q '"id"'; then
        TASK_ID=$(echo "$RESP" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)
        CMD=$(echo "$RESP" | grep -o '"command":"[^"]*' | head -1 | cut -d'"' -f4)

        if [ -n "$TASK_ID" ] && [ -n "$CMD" ]; then
            echo "[Agent] Executing [$TASK_ID]: $CMD"
            
            # CAS: Update to running
            curl -s -X PATCH "$API_URL/commands?id=eq.$TASK_ID&status=eq.pending" \
                 -H "Content-Type: application/json" \
                 $(get_headers) \
                 -d '{"status":"running"}' > /dev/null
            
            # Execute command
            OUT=$(eval "$CMD" 2>&1)
            EXIT_CODE=$?
            
            if [ $EXIT_CODE -eq 0 ]; then
                STATUS="completed"
            else
                STATUS="failed"
            fi
            
            echo "[Agent] Task $STATUS (exit $EXIT_CODE)"

            # Safe JSON encode output (simple replacement for newlines and quotes)
            SAFE_OUT=$(echo "$OUT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | tr '\n' '\\' | sed 's/\\/\\n/g' )
            
            curl -s -X PATCH "$API_URL/commands?id=eq.$TASK_ID" \
                 -H "Content-Type: application/json" \
                 $(get_headers) \
                 -d "{\"status\":\"$STATUS\",\"output\":\"$SAFE_OUT\"}" > /dev/null
        fi
    fi
    
    sleep $POLL_SEC
done
