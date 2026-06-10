#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${BACKEND_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing canonical backend test environment at ${PYTHON_BIN}. Run backend/scripts/bootstrap_test_env.sh first." >&2
  exit 1
fi

SUITE="${1:-all}"

case "${SUITE}" in
  feedback)
    TESTS=(
      tests.test_feedback_report_api
      tests.test_feedback_retention
    )
    ;;
  invite-auth)
    TESTS=(
      tests.test_invite_flow
      tests.test_auth_cookie_session
      tests.test_rate_limit_hardening
    )
    ;;
  proxy-cache)
    TESTS=(
      tests.test_proxy_and_cache_hardening
    )
    ;;
  admin)
    TESTS=(
      tests.test_admin_secure_actions_phase2
    )
    ;;
  session-mfa)
    TESTS=(
      tests.test_privileged_session_mfa_enforcement
    )
    ;;
  all)
    TESTS=(
      tests.test_feedback_report_api
      tests.test_feedback_retention
      tests.test_invite_flow
      tests.test_auth_cookie_session
      tests.test_proxy_and_cache_hardening
      tests.test_admin_secure_actions_phase2
      tests.test_rate_limit_hardening
      tests.test_privileged_session_mfa_enforcement
    )
    ;;
  *)
    echo "Unknown suite: ${SUITE}" >&2
    echo "Expected one of: feedback, invite-auth, proxy-cache, admin, session-mfa, all" >&2
    exit 1
    ;;
esac

cd "${BACKEND_DIR}"
"${PYTHON_BIN}" -m unittest "${TESTS[@]}"
