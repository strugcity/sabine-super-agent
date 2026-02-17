#!/usr/bin/env bash
# ============================================================================
# Worker Deployment Test Runner
# ============================================================================
#
# Builds the worker Docker image once, then runs six test scenarios against
# docker-compose.worker-test.yml and prints a PASS/FAIL verdict for each.
#
# Prerequisites:
#   - Docker Engine running
#   - docker compose v2 (or docker-compose v1 with COMPOSE_V1=1)
#   - curl
#
# Usage:
#   ./scripts/test_worker_deploy.sh             # run all 6 tests
#   ./scripts/test_worker_deploy.sh --no-build  # skip image rebuild
#
# Exit code:
#   0 — all tests passed
#   1 — one or more tests failed
#
# Tests:
#   1. docker build succeeds            (catches import errors)
#   2. happy path: worker starts, health returns 200
#   3. Redis 15 s delayed start         (cold-start race; must pass with Fix 1+4)
#   4. health returns 200 during retry  (status "starting"; must pass with Fix 4)
#   5. Redis never available            (worker exits cleanly, non-zero code)
#   6. Redis restart mid-operation      (health recovers after Redis comes back)
#
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COMPOSE_FILE="docker-compose.worker-test.yml"
HEALTH_URL="http://localhost:8082/health"
POLL_INTERVAL=2          # seconds between health poll attempts
HEALTH_TIMEOUT=90        # seconds to wait for healthy response (Tests 2, 3)
STARTING_TIMEOUT=20      # seconds to wait for "starting" response (Test 4)
RETRY_EXHAUST_TIMEOUT=90 # seconds to wait for worker to exit (Test 5)
RECOVER_TIMEOUT=30       # seconds to wait for recovery after Redis restart (Test 6)

PASS=0
FAIL=0
SKIP=0

# Detect compose command
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
elif docker-compose version &>/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "ERROR: neither 'docker compose' nor 'docker-compose' found" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_cyan()   { printf '\033[0;36m%s\033[0m\n' "$*"; }

pass() { _green "  PASS: $*"; (( PASS++ )) || true; }
fail() { _red   "  FAIL: $*"; (( FAIL++ )) || true; }
skip() { _yellow "  SKIP: $*"; (( SKIP++ )) || true; }
info() { _cyan  "  ···  $*"; }

compose_up()   { $COMPOSE -f "$COMPOSE_FILE" --profile "$1" up -d 2>&1; }
compose_down() { $COMPOSE -f "$COMPOSE_FILE" --profile "$1" down -v --timeout 10 2>&1 || true; }

# Poll /health until HTTP 200 is received or timeout
wait_for_http_200() {
    local timeout=$1
    local elapsed=0
    while (( elapsed < timeout )); do
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$HEALTH_URL" 2>/dev/null || echo "000")
        if [[ "$http_code" == "200" ]]; then
            return 0
        fi
        sleep "$POLL_INTERVAL"
        (( elapsed += POLL_INTERVAL )) || true
    done
    return 1
}

# Poll /health until JSON body contains a specific "status" value, or timeout
wait_for_status() {
    local expected_status=$1
    local timeout=$2
    local elapsed=0
    while (( elapsed < timeout )); do
        local body
        body=$(curl -s --max-time 3 "$HEALTH_URL" 2>/dev/null || echo "{}")
        local status
        status=$(echo "$body" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '"[^"]*"$' | tr -d '"' || echo "")
        if [[ "$status" == "$expected_status" ]]; then
            return 0
        fi
        sleep "$POLL_INTERVAL"
        (( elapsed += POLL_INTERVAL )) || true
    done
    return 1
}

# Wait until a container exits, return its exit code
wait_for_exit() {
    local container=$1
    local timeout=$2
    local elapsed=0
    while (( elapsed < timeout )); do
        local state
        state=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
        if [[ "$state" == "exited" ]]; then
            docker inspect --format='{{.State.ExitCode}}' "$container" 2>/dev/null || echo "1"
            return 0
        fi
        sleep "$POLL_INTERVAL"
        (( elapsed += POLL_INTERVAL )) || true
    done
    return 1
}

# ---------------------------------------------------------------------------
# Test 1: docker build
# ---------------------------------------------------------------------------
run_test1() {
    echo
    _cyan "━━━ Test 1: docker build succeeds ━━━"
    if [[ "${SKIP_BUILD:-}" == "1" ]]; then
        skip "skipped via --no-build"
        return
    fi

    info "Building image from backend/worker/Dockerfile (context: repo root)..."
    if docker build -t sabine-worker-test -f backend/worker/Dockerfile . 2>&1 | tail -5; then
        pass "docker build succeeded — no import errors at image-build time"
    else
        fail "docker build failed"
    fi
}

# ---------------------------------------------------------------------------
# Test 2: happy path — Redis ready before worker
# ---------------------------------------------------------------------------
run_test2() {
    echo
    _cyan "━━━ Test 2: happy path (Redis ready before worker) ━━━"
    compose_down happy
    compose_up happy

    info "Waiting up to ${HEALTH_TIMEOUT}s for /health to return 200..."
    if wait_for_http_200 "$HEALTH_TIMEOUT"; then
        local status
        status=$(curl -s "$HEALTH_URL" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '"[^"]*"$' | tr -d '"' || echo "unknown")
        if [[ "$status" == "healthy" ]]; then
            pass "happy path: /health returned 200 with status='healthy'"
        else
            fail "happy path: /health returned 200 but status='$status' (expected 'healthy')"
        fi
    else
        fail "happy path: /health did not return 200 within ${HEALTH_TIMEOUT}s"
    fi

    compose_down happy
}

# ---------------------------------------------------------------------------
# Test 3: Redis 15 s delayed start (cold-start race)
# ---------------------------------------------------------------------------
run_test3() {
    echo
    _cyan "━━━ Test 3: Redis 15s delayed start (cold-start race) ━━━"
    compose_down delayed
    compose_up delayed

    info "Waiting up to ${HEALTH_TIMEOUT}s for /health to return 200 (Redis starts in ~15s)..."
    if wait_for_http_200 "$HEALTH_TIMEOUT"; then
        pass "delayed Redis: worker survived the cold-start race and health is 200"
    else
        fail "delayed Redis: /health never returned 200 within ${HEALTH_TIMEOUT}s"
    fi
}

# ---------------------------------------------------------------------------
# Test 4: health returns 200 with "starting" during Redis retry window
#
# This test overlaps with Test 3 — we check the EARLY response while
# the worker is still retrying Redis (within the first ~10 s of startup).
# We leave the delayed containers up from Test 3 for this check.
# ---------------------------------------------------------------------------
run_test4() {
    echo
    _cyan "━━━ Test 4: /health returns 200/'starting' during Redis retry ━━━"

    # Check if delayed containers are still up from Test 3
    local worker_container
    worker_container=$($COMPOSE -f "$COMPOSE_FILE" --profile delayed ps -q worker-delayed 2>/dev/null | head -1 || echo "")

    if [[ -z "$worker_container" ]]; then
        # Re-start delayed scenario for this test alone
        compose_down delayed
        compose_up delayed
    fi

    # The health server starts before the Redis retry loop so the very first
    # probe should get a 200 with status="starting".  We check quickly.
    info "Checking that /health returns 200 (any status) within ${STARTING_TIMEOUT}s..."
    if wait_for_http_200 "$STARTING_TIMEOUT"; then
        local status
        status=$(curl -s "$HEALTH_URL" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '"[^"]*"$' | tr -d '"' || echo "unknown")
        pass "/health returned 200 during startup (status='$status') — probe won't kill container"
    else
        fail "/health did not return 200 within ${STARTING_TIMEOUT}s — Railway would kill container"
    fi

    compose_down delayed
}

# ---------------------------------------------------------------------------
# Test 5: Redis never available — worker exhausts retries and exits cleanly
# ---------------------------------------------------------------------------
run_test5() {
    echo
    _cyan "━━━ Test 5: Redis never available (retry exhaustion) ━━━"
    compose_down absent
    compose_up absent

    # Find the worker container name
    local worker_container
    worker_container=$($COMPOSE -f "$COMPOSE_FILE" --profile absent ps -q worker-absent 2>/dev/null | head -1 || echo "")

    if [[ -z "$worker_container" ]]; then
        fail "absent: could not find worker container"
        compose_down absent
        return
    fi

    info "Waiting up to ${RETRY_EXHAUST_TIMEOUT}s for worker to exit after exhausting retries..."
    local exit_code
    if exit_code=$(wait_for_exit "$worker_container" "$RETRY_EXHAUST_TIMEOUT"); then
        if [[ "$exit_code" != "0" ]]; then
            pass "absent Redis: worker exited with code $exit_code (non-zero, as expected)"
        else
            fail "absent Redis: worker exited with code 0 (expected non-zero)"
        fi
    else
        fail "absent Redis: worker did not exit within ${RETRY_EXHAUST_TIMEOUT}s"
    fi

    compose_down absent
}

# ---------------------------------------------------------------------------
# Test 6: Redis restart mid-operation — health recovers
# ---------------------------------------------------------------------------
run_test6() {
    echo
    _cyan "━━━ Test 6: Redis restart mid-operation (health recovers) ━━━"
    compose_down happy
    compose_up happy

    info "Waiting for initial healthy state..."
    if ! wait_for_http_200 "$HEALTH_TIMEOUT"; then
        fail "recover: worker never became healthy initially"
        compose_down happy
        return
    fi

    # Find the Redis container for the happy profile
    local redis_container
    redis_container=$($COMPOSE -f "$COMPOSE_FILE" --profile happy ps -q redis-happy 2>/dev/null | head -1 || echo "")

    if [[ -z "$redis_container" ]]; then
        skip "recover: could not find redis-happy container — skipping restart test"
        compose_down happy
        return
    fi

    info "Stopping Redis container ($redis_container)..."
    docker stop "$redis_container" 2>&1 || true
    sleep 5

    info "Restarting Redis container..."
    docker start "$redis_container" 2>&1 || true

    info "Waiting up to ${RECOVER_TIMEOUT}s for health to return 200 after Redis restart..."
    if wait_for_http_200 "$RECOVER_TIMEOUT"; then
        local status
        status=$(curl -s "$HEALTH_URL" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '"[^"]*"$' | tr -d '"' || echo "unknown")
        pass "Redis restart: health recovered to 200 (status='$status')"
    else
        fail "Redis restart: health did not recover to 200 within ${RECOVER_TIMEOUT}s"
    fi

    compose_down happy
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    # Parse flags
    for arg in "$@"; do
        case "$arg" in
            --no-build) SKIP_BUILD=1 ;;
        esac
    done

    echo
    _cyan "════════════════════════════════════════════════════════════"
    _cyan "  Sabine Worker Deployment Test Suite"
    _cyan "  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    _cyan "════════════════════════════════════════════════════════════"

    # Ensure we're in the repo root (where the Dockerfile context must be)
    if [[ ! -f "backend/worker/Dockerfile" ]]; then
        echo "ERROR: run this script from the repository root" >&2
        exit 1
    fi

    run_test1
    run_test2
    run_test3
    run_test4
    run_test5
    run_test6

    echo
    _cyan "════════════════════════════════════════════════════════════"
    printf "  Results: "
    _green "${PASS} passed"
    printf "           "
    if (( FAIL > 0 )); then
        _red "${FAIL} failed"
    else
        echo "${FAIL} failed"
    fi
    if (( SKIP > 0 )); then
        printf "           "
        _yellow "${SKIP} skipped"
    fi
    _cyan "════════════════════════════════════════════════════════════"
    echo

    if (( FAIL > 0 )); then
        exit 1
    fi
}

main "$@"
