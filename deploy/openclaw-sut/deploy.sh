#!/usr/bin/env bash
# deploy.sh — OpenClaw-SUT adapter: the single e2e deployment entry point
# (specs/openclaw-sut-adapter/spec.md R-D1).
#
# Ten ordered, fail-fast, individually idempotent stages:
#   1. preflight        docker + compose v2, Omega agent stopped, DAS client
#                       network present, orchestrator secret env file present
#   2. build            wrapper image openclaw-sut:2026.10.10-metta1 from
#                       Dockerfile.sut (pinned base openclaw/openclaw:2026.10.10,
#                       index digest verified at pull)
#   3. volume + seed    openclaw-sut-workspace named volume seeded from
#                       workspace-seed/ + the six skills in skills-sut/
#   4. runtime env      runtime.env written from the orchestrator-provided
#                       secret env file + discovered DAS origins; aborts on
#                       missing/empty values; NEVER prints values
#   5. onboard          non-interactive headless onboarding (official Docker
#                       image pattern: compose run --entrypoint node) + the
#                       benchmark config overlay (sut-config-overlay.json)
#   6. telegram         channels add --channel telegram --use-env
#   7. up               docker compose up -d + connect the gateway container
#                       to the omega-das-integration-client network
#   8. provider verify  a REAL one-token completion against
#                       https://api.asi1.ai/v1 through the SUT's configured
#                       provider credentials; abort asks to re-request the
#                       OPENCLAW_SUT_ASI1_API_KEY secret on auth failure
#   9. das lanes        TCP reach of write bridge + read proxy from inside
#                       the SUT container (client-network IPs)
#  10. smoke            metta runtime check ((|- ...) evaluates via the SUT
#                       metta skill) + skill-visibility check (skills list
#                       shows the six benchmark skills) + deployment report
#
# Security contract (spec invariant 5): no `set -x`, no echoing/env-dumping/
# catting of secret values; committed examples carry placeholders only. The
# runtime env file is written with umask 077 and never printed.
#
# Usage:
#   ./deploy.sh --secrets-file /path/to/orchestrator-secrets.env
#
# The orchestrator secret env file defines (shell KEY=VALUE lines):
#   OPENCLAW_SUT_ASI1_API_KEY        the ASI1 provider key
#   OPENCLAW_SUT_TELEGRAM_BOT_TOKEN  the Telegram bot token
#   OPENCLAW_SUT_GATEWAY_TOKEN       the OpenClaw Gateway auth token
# (the final runtime names OPENAI_API_KEY / CUSTOM_API_KEY … see stage 4
#  are derived from these; the file itself stays outside the repo.)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$SCRIPT_DIR"

# --- constants (mirror the harness + compose/Dockerfile in this directory)
SUT_IMAGE="openclaw-sut:2026.10.10-metta1"
BASE_IMAGE="openclaw/openclaw:2026.10.10"
BASE_DIGEST="sha256:1e5ee6c7d02d5b5f64f9cf26a30c7ef7d4ec292f0d25fa590f4b7e103e8bf799"
DAS_NETWORK="omega-das-integration-client"
GATEWAY_CONTAINER="openclaw-sut-gateway"
WORKSPACE_VOLUME="openclaw-sut-workspace"
CONTAINER_WRITE_BRIDGE="omega-das-write-bridge-write-bridge-1"
CONTAINER_READ_PROXY="omega-das-integration-read-proxy-1"
ASI1_BASE_URL="https://api.asi1.ai/v1"
ASI1_MODEL="asi1-ultra"
SEED_MARKER=".sut-seeded"
RUNTIME_ENV="runtime.env"
SUT_SKILLS="das-write das-retrieve metta pin das-extract-knowledge das-grounded-reasoning"

SECRETS_FILE="${SECRETS_ENV_FILE:-}"

log()  { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] FATAL: %s\n' "$*" >&2; exit 1; }

# The official image pattern for pre-start CLI work (the gateway container
# does not exist yet): a one-off container from the gateway service with the
# node entrypoint and the CLI's dist/index.js entry (docs: "Pre-start
# onboarding and config writes run through openclaw-gateway directly").
sut_cli() {
  docker compose run -T --rm --no-deps --entrypoint node gateway \
    dist/index.js "$@"
}
# Post-start CLI work: exec inside the running gateway container (the image
# WORKDIR is /app, so `node dist/index.js` is the in-container CLI form).
sut_exec() {
  docker compose exec -T gateway "$@"
}

# ---------------------------------------------------------------------------
# Stage 1 — preflight
# ---------------------------------------------------------------------------
stage1_preflight() {
  log "stage 1/10: preflight"
  command -v docker >/dev/null 2>&1 || fail "docker is not installed"
  docker version >/dev/null 2>&1 || fail "docker daemon is unreachable"
  docker compose version >/dev/null 2>&1 || fail "docker compose v2 is not installed (docker compose version)"

  local running
  running="$(docker ps --filter "name=omega-curiosity" --format '{{.Names}}')"
  if [ -n "$running" ]; then
    fail "the Omega agent container is RUNNING ($running) — the ASI1 key quota is shared between both agents; stop it first: sudo systemctl stop omega-curiosity.service"
  fi

  docker network inspect "$DAS_NETWORK" >/dev/null 2>&1 \
    || fail "docker network $DAS_NETWORK does not exist — start the DAS compose stack first"

  if [ -z "$SECRETS_FILE" ]; then
    fail "no secrets env file given — pass --secrets-file <path> (orchestrator-provided, outside this repo)"
  fi
  [ -f "$SECRETS_FILE" ] || fail "secrets env file not found: $SECRETS_FILE"
  [ -s "$SECRETS_FILE" ] || fail "secrets env file is empty: $SECRETS_FILE"

  [ -f "Dockerfile.sut" ]      || fail "Dockerfile.sut missing next to deploy.sh"
  [ -f "docker-compose.yml" ]  || fail "docker-compose.yml missing next to deploy.sh"
  [ -f "sut-config-overlay.json" ] || fail "sut-config-overlay.json missing next to deploy.sh"
  [ -d "workspace-seed" ]      || fail "workspace-seed/ missing next to deploy.sh"
  log "stage 1/10: preflight OK"
}

# ---------------------------------------------------------------------------
# Stage 2 — build the SUT wrapper image (pinned base, digest verified)
# ---------------------------------------------------------------------------
stage2_build() {
  log "stage 2/10: build $SUT_IMAGE (base $BASE_IMAGE)"
  [ -f "metta-libs/lib_nal.metta" ] || fail "metta-libs/lib_nal.metta is missing — the orchestrator commits the vendored libs (see metta-libs/README.md)"
  [ -f "metta-libs/lib_pln.metta" ] || fail "metta-libs/lib_pln.metta is missing — the orchestrator commits the vendored libs (see metta-libs/README.md)"

  log "stage 2/10: pulling pinned base $BASE_IMAGE"
  docker pull "$BASE_IMAGE" >/dev/null
  local digests
  digests="$(docker image inspect "$BASE_IMAGE" --format '{{json .RepoDigests}}')"
  case "$digests" in
    *"$BASE_DIGEST"*) ;;
    *) fail "pinned base digest mismatch: $BASE_IMAGE does not resolve to $BASE_DIGEST (got: $digests)" ;;
  esac
  log "stage 2/10: base digest verified ($BASE_DIGEST)"

  docker build -f Dockerfile.sut -t "$SUT_IMAGE" .
  log "stage 2/10: built $SUT_IMAGE"
}

# ---------------------------------------------------------------------------
# Stage 3 — workspace volume + seed
# ---------------------------------------------------------------------------
stage3_volume() {
  log "stage 3/10: workspace volume + seed"
  docker volume create "$WORKSPACE_VOLUME" >/dev/null

  if docker run --rm --entrypoint sh \
      -v "$WORKSPACE_VOLUME:/var/openclaw/workspace" "$SUT_IMAGE" \
      -c "test -f /var/openclaw/workspace/$SEED_MARKER" 2>/dev/null; then
    log "stage 3/10: volume already seeded ($SEED_MARKER present)"
    return 0
  fi

  docker run --rm --entrypoint sh \
    -v "$WORKSPACE_VOLUME:/var/openclaw/workspace" \
    -v "$REPO_ROOT/skills-sut:/skills-src:ro" \
    -v "$SCRIPT_DIR/workspace-seed:/seed-src:ro" \
    "$SUT_IMAGE" -c '
      set -e
      cp -r /seed-src/. /var/openclaw/workspace/
      mkdir -p /var/openclaw/workspace/skills
      cp -r /skills-src/. /var/openclaw/workspace/skills/
      touch /var/openclaw/workspace/'"$SEED_MARKER"'
    '
  log "stage 3/10: volume seeded (workspace-seed/ + the six skills from skills-sut/)"
}

# ---------------------------------------------------------------------------
# Stage 4 — runtime env from the orchestrator secrets + discovered DAS origins
# ---------------------------------------------------------------------------
stage4_runtime_env() {
  log "stage 4/10: writing $RUNTIME_ENV (values never printed)"
  local wb_ip rp_ip
  wb_ip="$(docker inspect -f \
    "{{with index .NetworkSettings.Networks \"$DAS_NETWORK\"}}{{.IPAddress}}{{end}}" \
    "$CONTAINER_WRITE_BRIDGE" 2>/dev/null || true)"
  rp_ip="$(docker inspect -f \
    "{{with index .NetworkSettings.Networks \"$DAS_NETWORK\"}}{{.IPAddress}}{{end}}" \
    "$CONTAINER_READ_PROXY" 2>/dev/null || true)"
  [ -n "$wb_ip" ] || fail "could not resolve the write-bridge IP on $DAS_NETWORK (is the DAS stack running?)"
  [ -n "$rp_ip" ] || fail "could not resolve the read-proxy IP on $DAS_NETWORK (is the DAS stack running?)"

  (
    set -a
    # shellcheck disable=SC1090
    . "$SECRETS_FILE"
    set +a

    asi1_key="${OPENCLAW_SUT_ASI1_API_KEY:-${OPENAI_API_KEY:-}}"
    tg_token="${OPENCLAW_SUT_TELEGRAM_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
    gw_token="${OPENCLAW_SUT_GATEWAY_TOKEN:-${OPENCLAW_GATEWAY_TOKEN:-}}"

    # abort on missing/empty — NAMES only, never values
    [ -n "$asi1_key" ] || { printf '[deploy] FATAL: required secret is empty: OPENCLAW_SUT_ASI1_API_KEY\n' >&2; exit 1; }
    [ -n "$tg_token" ] || { printf '[deploy] FATAL: required secret is empty: OPENCLAW_SUT_TELEGRAM_BOT_TOKEN\n' >&2; exit 1; }
    [ -n "$gw_token" ] || { printf '[deploy] FATAL: required secret is empty: OPENCLAW_SUT_GATEWAY_TOKEN\n' >&2; exit 1; }

    umask 077
    {
      printf '# generated by deploy.sh stage 4 — NEVER commit or print this file\n'
      printf 'OPENAI_API_KEY=%s\n' "$asi1_key"
      printf 'CUSTOM_API_KEY=%s\n' "$asi1_key"
      printf 'TELEGRAM_BOT_TOKEN=%s\n' "$tg_token"
      printf 'OPENCLAW_GATEWAY_TOKEN=%s\n' "$gw_token"
      printf 'OPENCLAW_STATE_DIR=/var/openclaw/state\n'
      printf 'OPENCLAW_SUT_WORKSPACE=/var/openclaw/workspace\n'
      printf 'OPENCLAW_SUT_DAS_ENABLED=1\n'
      printf 'OPENCLAW_SUT_WRITE_REQUIRE_REF=1\n'
      printf 'OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN=http://%s:8080\n' "$wb_ip"
      printf 'OPENCLAW_SUT_READ_PROXY_ORIGIN=http://%s:8080\n' "$rp_ip"
      printf 'OPENCLAW_SUT_METTA_LIB_DIR=/opt/sut-metta\n'
    } > "$RUNTIME_ENV"
  )
  log "stage 4/10: $RUNTIME_ENV written (secrets: OPENAI_API_KEY/CUSTOM_API_KEY/TELEGRAM_BOT_TOKEN/OPENCLAW_GATEWAY_TOKEN; origins: $wb_ip $rp_ip)"
}

# ---------------------------------------------------------------------------
# Stage 5 — non-interactive onboarding + benchmark config overlay
# ---------------------------------------------------------------------------
stage5_onboard() {
  log "stage 5/10: onboarding the gateway (non-interactive, headless pattern)"
  # Idempotency (orchestrator fix 2026-11-03): if /var/openclaw/state/openclaw.json
  # already exists (prior successful onboarding), skip the onboard CLI call
  # entirely — re-running onboard against existing state fails generically.
  # The overlay patch below is still applied unconditionally (it is idempotent).
  #
  # Official headless bootstrap flags (docs.openclaw.ai/install/docker):
  # token auth via the OPENCLAW_GATEWAY_TOKEN env SecretRef, OpenAI-compatible
  # custom provider = ASI1 (CUSTOM_API_KEY env ref, base URL, model), skip
  # channels/daemon/bootstrap. --skip-bootstrap keeps the seeded AGENTS.md the
  # only standing instruction (workspace-seed/ owns the workspace files).
  # Idempotency guard: check if the state volume already has an onboarded
  # config. If so, skip the onboard CLI call (it fails on re-run) and go
  # straight to the overlay patch (which is independently idempotent).
  if docker compose run -T --rm --no-deps --entrypoint sh gateway \
      -c "test -f /var/openclaw/state/openclaw.json" 2>/dev/null; then
    log "stage 5/10: gateway already onboarded — skipping onboard CLI (idempotent re-run)"
  else
    sut_cli onboard \
      --non-interactive --accept-risk --skip-health --mode local \
      --auth-choice custom-api-key \
      --custom-base-url "$ASI1_BASE_URL" \
      --custom-model-id "$ASI1_MODEL" \
      --custom-compatibility openai \
      --secret-input-mode ref \
      --gateway-auth token \
      --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
      --skip-channels --no-install-daemon --skip-bootstrap
  fi

  log "stage 5/10: applying the benchmark config overlay (sut-config-overlay.json)"
  sut_cli config patch --file /var/openclaw/sut-config-overlay.json

  # autonomous/scheduled OFF is enforced by the overlay (cron.enabled=false);
  # heartbeat off is defense-in-depth via the CLI (tolerant: the overlay is
  # the hard gate, and the command surface is verified at smoke)
  sut_cli system heartbeat disable >/dev/null 2>&1 \
    && log "stage 5/10: heartbeat disabled" \
    || log "stage 5/10: heartbeat disable skipped (non-fatal; cron stays disabled via the overlay)"
}

# ---------------------------------------------------------------------------
# Stage 6 — Telegram channel (operator oversight only)
# ---------------------------------------------------------------------------
stage6_telegram() {
  log "stage 6/10: adding the Telegram channel (token from TELEGRAM_BOT_TOKEN env only)"
  sut_cli channels add --channel telegram --use-env
}

# ---------------------------------------------------------------------------
# Stage 7 — compose up + DAS network attach
# ---------------------------------------------------------------------------
stage7_up() {
  log "stage 7/10: docker compose up -d"
  docker compose up -d
  local attached
  attached="$(docker network inspect -f '{{range .Containers}}{{.Name}} {{end}}' "$DAS_NETWORK" 2>/dev/null || true)"
  case " $attached " in
    *" $GATEWAY_CONTAINER "*)
      log "stage 7/10: gateway already attached to $DAS_NETWORK" ;;
    *)
      docker network connect "$DAS_NETWORK" "$GATEWAY_CONTAINER"
      log "stage 7/10: gateway attached to $DAS_NETWORK" ;;
  esac
}

# ---------------------------------------------------------------------------
# Stage 8 — provider verify (REAL one-token completion through the SUT creds)
# ---------------------------------------------------------------------------
stage8_provider_verify() {
  log "stage 8/10: provider verify (one-token completion against $ASI1_BASE_URL)"
  # The call uses the exact provider tuple the SUT turns use: the CUSTOM_API_KEY
  # env ref (written by stage 5's onboarding), the same base URL and model.
  # The key is read from the container env inside the python process — it is
  # never echoed, never passed on a command line.
  if sut_exec python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request

key = os.environ.get("CUSTOM_API_KEY", "")
if not key:
    print("provider-verify: CUSTOM_API_KEY is missing from the container env")
    sys.exit(3)

req = urllib.request.Request(
    "https://api.asi1.ai/v1/chat/completions",
    data=json.dumps({
        "model": "asi1-ultra",
        "messages": [{"role": "user", "content": "OK"}],
        "max_tokens": 1,
    }).encode("utf-8"),
    headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("provider-verify: HTTP %s model=asi1-ultra" % resp.status)
except urllib.error.HTTPError as exc:
    print("provider-verify: HTTP %s" % exc.code)
    sys.exit(1 if exc.code in (401, 403) else 2)
except OSError as exc:
    print("provider-verify: request failed (%s)" % exc.__class__.__name__)
    sys.exit(2)
PY
  then
    log "stage 8/10: provider verify OK"
  else
    rc=$?
    if [ "$rc" -eq 1 ]; then
      fail "provider auth failed (HTTP 401/403) — re-request the OPENCLAW_SUT_ASI1_API_KEY secret and re-run deploy.sh"
    fi
    fail "provider verify failed (exit $rc) — check the endpoint, the key, and the SUT container env"
  fi
}

# ---------------------------------------------------------------------------
# Stage 9 — DAS lanes reachable from inside the SUT container
# ---------------------------------------------------------------------------
stage9_das_lanes() {
  log "stage 9/10: DAS lanes reachable from inside the SUT container"
  sut_exec python3 - <<'PY' || fail "DAS lane(s) unreachable from the SUT container — check the $DAS_NETWORK attachment and the DAS origins in runtime.env"
import os, socket, sys
from urllib.parse import urlsplit

failed = []
for var in ("OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN",
            "OPENCLAW_SUT_READ_PROXY_ORIGIN"):
    origin = os.environ.get(var, "")
    if not origin:
        print("%s: MISSING from the container env" % var)
        failed.append(var)
        continue
    u = urlsplit(origin)
    try:
        socket.create_connection((u.hostname, u.port or 80), timeout=5).close()
        print("%s: reachable (%s:%s)" % (var, u.hostname, u.port))
    except OSError as exc:
        print("%s: UNREACHABLE (%s)" % (var, exc.__class__.__name__))
        failed.append(var)
sys.exit(1 if failed else 0)
PY
  log "stage 9/10: DAS lanes OK"
}

# ---------------------------------------------------------------------------
# Stage 10 — smoke: metta runtime + skill visibility + deployment report
# ---------------------------------------------------------------------------
stage10_smoke() {
  log "stage 10/10: smoke"

  # (a) metta runtime check: the strictly-2-argument NAL operator evaluates
  # through the SUT metta skill (fresh ephemeral atomspace, vendored libs).
  # OPENCLAW_SUT_WORKSPACE is pointed at a scratch dir so the smoke episode
  # does not touch the seeded workspace's history.metta ledger.
  local metta_out
  # NOTE: `docker compose exec` requires env-var options BEFORE the service
  # name; passing `-e` after `gateway` makes the container try to exec `-e`
  # as the executable (RCA of the first smoke failure). Using `env` inside
  # the container sets the var correctly on any base.
  if metta_out="$(sut_exec env OPENCLAW_SUT_WORKSPACE=/tmp/sut-smoke python3 \
      /var/openclaw/workspace/skills/metta/metta_run.py \
      '(|- ((--> smoke-a smoke-b) (stv 1.0 0.9)) ((--> smoke-a smoke-c) (stv 1.0 0.9)))' 2>&1)"; then
    case "$metta_out" in
      *"(stv "*) log "stage 10/10: metta runtime OK — (|- ...) evaluates with (stv ...) output" ;;
      *) fail "metta runtime check failed: no (stv ...) in the interpreter output (got: $metta_out)" ;;
    esac
  else
    fail "metta runtime check failed: $metta_out"
  fi

  # (b) skill-visibility check: the six benchmark skills are listed.
  local skills_list missing=""
  skills_list="$(sut_exec node dist/index.js skills list 2>&1)" \
    || fail "skills list failed — check the gateway health and the workspace skills/ seeding"
  for skill in $SUT_SKILLS; do
    case "$skills_list" in
      *"$skill"*) ;;
      *) missing="$missing $skill" ;;
    esac
  done
  [ -z "$missing" ] || fail "skill-visibility check failed — missing from skills list:$missing"
  log "stage 10/10: all six benchmark skills visible ($SUT_SKILLS)"

  # (c) deployment report (no secrets)
  cat <<REPORT
[deploy] ================= deployment report =================
image:            $SUT_IMAGE (base $BASE_IMAGE @$BASE_DIGEST)
gateway:          $GATEWAY_CONTAINER (compose service gateway)
workspace volume: $WORKSPACE_VOLUME -> /var/openclaw/workspace (seeded)
state volume:     openclaw-sut-state -> /var/openclaw/state (OPENCLAW_STATE_DIR)
das network:      $DAS_NETWORK (attached)
provider:         $ASI1_BASE_URL model=$ASI1_MODEL (verified, one-token completion)
das lanes:        write-bridge + read-proxy reachable from the SUT
skills:           $SUT_SKILLS (all visible)
metta:            swipl:10.0.2 + PeTTa v1.0.4 (/opt/petta) + vendored lib_nal.metta/lib_pln.metta (/opt/sut-metta) — NAL evaluates
secrets:          OPENAI_API_KEY/CUSTOM_API_KEY/TELEGRAM_BOT_TOKEN/OPENCLAW_GATEWAY_TOKEN present (values never printed)
harness:          python3 tests/reasoning-windowless-room/run_benchmark.py --agent-profile openclaw full --two-phase --run-id <run-id>
[deploy] =====================================================
REPORT
}

usage() {
  cat <<USAGE
usage: ./deploy.sh --secrets-file <path-to-orchestrator-secrets.env>

Stages run in order (each idempotent; re-run after a fix resumes):
  1 preflight, 2 build, 3 volume+seed, 4 runtime env, 5 onboard+overlay,
  6 telegram, 7 up+network, 8 provider verify, 9 das lanes, 10 smoke.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --secrets-file) SECRETS_FILE="${2:?--secrets-file needs a path}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unknown argument: $1 (see --help)" ;;
  esac
done

stage1_preflight
stage2_build
stage3_volume
stage4_runtime_env
stage5_onboard
stage6_telegram
stage7_up
stage8_provider_verify
stage9_das_lanes
stage10_smoke
log "deployment complete — the SUT is ready for the openclaw-profile harness run"
