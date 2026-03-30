#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-}"
if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI (gh) is required."
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required."
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: gh is not authenticated. Run: gh auth login"
  exit 1
fi

PROTECTED_BRANCHES=("main" "master" "mh-main" "bh-main")
STATUS_CONTEXTS='["PR Governance Gate / governance"]'

echo "Applying OpenAgriNet governance to ${REPO}..."
for branch in "${PROTECTED_BRANCHES[@]}"; do
  resolved_branch="$(gh api "repos/${REPO}/branches/${branch}" --jq .name 2>/dev/null || true)"
  if [[ "${resolved_branch}" != "${branch}" ]]; then
    echo "Skipping missing branch: ${branch}"
    continue
  fi

  payload="$(
    jq -n \
      --argjson contexts "${STATUS_CONTEXTS}" \
      '{
        required_status_checks: {
          strict: true,
          contexts: $contexts
        },
        enforce_admins: true,
        required_pull_request_reviews: {
          dismiss_stale_reviews: true,
          require_code_owner_reviews: true,
          required_approving_review_count: 1,
          require_last_push_approval: true
        },
        restrictions: null,
        required_linear_history: false,
        allow_force_pushes: false,
        allow_deletions: false,
        required_conversation_resolution: true
      }'
  )"

  gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "repos/${REPO}/branches/${branch}/protection" \
    --input - <<<"${payload}" >/dev/null

  echo "Protected branch updated: ${branch}"
done

echo "Governance branch protection applied."
