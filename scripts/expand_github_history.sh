#!/usr/bin/env bash
set -euo pipefail

REPO="org-beaconstone/titan"
OWNER="org-beaconstone"
NAME="titan"
DEFAULT_BRANCH=$(gh repo view "$REPO" --json defaultBranchRef --jq '.defaultBranchRef.name')
ACTOR_NAME=$(gh api user --jq '.name // .login')
ACTOR_EMAIL="lsmith@oneatlassian.atlassian.com"
BASE=tmp_rovodev_titan/api_seed_extra
mkdir -p "$BASE/docs/releases" "$BASE/services/api" "$BASE/services/exporter" "$BASE/services/worker"

mkblob() {
  local file="$1"
  gh api -X POST repos/$OWNER/$NAME/git/blobs -f content=@"$file" -f encoding=utf-8 --jq '.sha'
}
get_head_sha() { gh api repos/$OWNER/$NAME/git/ref/heads/$1 --jq '.object.sha'; }
get_commit_tree() { gh api repos/$OWNER/$NAME/git/commits/$1 --jq '.tree.sha'; }

create_tree_and_commit() {
  local branch="$1"; local base_sha="$2"; local msg="$3"; local date="$4"; shift 4
  local base_tree new_tree new_commit payload commit_payload
  base_tree=$(get_commit_tree "$base_sha")
  payload="$(mktemp)"
  {
    printf '{"base_tree":"%s","tree":[' "$base_tree"
    local first=1
    while (( "$#" )); do
      local path="$1" file="$2"; shift 2
      local blob_sha
      blob_sha=$(mkblob "$file")
      if [[ $first -eq 0 ]]; then printf ','; fi
      first=0
      python3 - <<PY
import json
print(json.dumps({"path": "$path", "mode": "100644", "type": "blob", "sha": "$blob_sha"}))
PY
    done
    printf ']}'
  } > "$payload"
  new_tree=$(gh api -X POST repos/$OWNER/$NAME/git/trees --input "$payload" --jq '.sha')
  rm -f "$payload"
  commit_payload="$(mktemp)"
  python3 - <<PY > "$commit_payload"
import json
print(json.dumps({
  "message": "$msg",
  "tree": "$new_tree",
  "parents": ["$base_sha"],
  "author": {"name": "$ACTOR_NAME", "email": "$ACTOR_EMAIL", "date": "$date"},
  "committer": {"name": "$ACTOR_NAME", "email": "$ACTOR_EMAIL", "date": "$date"}
}))
PY
  new_commit=$(gh api -X POST repos/$OWNER/$NAME/git/commits --input "$commit_payload" --jq '.sha')
  rm -f "$commit_payload"
  gh api -X PATCH repos/$OWNER/$NAME/git/refs/heads/$branch -f sha="$new_commit" -F force=true >/dev/null
  echo "$new_commit"
}

create_branch_from() {
  local new_branch="$1" from_branch="$2"
  local sha
  sha=$(get_head_sha "$from_branch")
  gh api -X POST repos/$OWNER/$NAME/git/refs -f ref="refs/heads/$new_branch" -f sha="$sha" >/dev/null || true
}

ensure_pr() {
  local branch="$1" title="$2" body="$3"
  local pr
  pr=$(gh pr list -R "$REPO" --head "$branch" --json number --jq '.[0].number // empty')
  if [[ -z "$pr" ]]; then
    gh pr create -R "$REPO" --base "$DEFAULT_BRANCH" --head "$branch" --title "$title" --body "$body" >/dev/null
    pr=$(gh pr view -R "$REPO" "$branch" --json number --jq '.number')
  fi
  echo "$pr"
}

# Add follow-up branches and PRs for review and readiness workflows.
create_branch_from "feature/review-queue-hardening" "$DEFAULT_BRANCH"
cat > "$BASE/services/api/review_queue.py" <<'EOF'
def classify_review_risk(changed_files: int, ci_green: bool) -> str:
    if changed_files > 20 or not ci_green:
        return "high"
    if changed_files > 8:
        return "medium"
    return "low"
EOF
create_tree_and_commit "feature/review-queue-hardening" "$(get_head_sha feature/review-queue-hardening)" "feat(review): add review queue risk classifier" "2026-04-16T10:00:00Z" \
  services/api/review_queue.py "$BASE/services/api/review_queue.py" >/dev/null

create_branch_from "feature/datadog-auth-examples" "$DEFAULT_BRANCH"
cat > "$BASE/docs/datadog-auth-examples.md" <<'EOF'
# Datadog authentication examples

Export jobs authenticate with:
- `DATADOG_API_KEY`
- `DATADOG_APP_KEY`

Example:
```bash
export DATADOG_API_KEY=example-api-key
export DATADOG_APP_KEY=example-app-key
```
EOF
create_tree_and_commit "feature/datadog-auth-examples" "$(get_head_sha feature/datadog-auth-examples)" "docs(datadog): add authentication examples" "2026-04-16T12:00:00Z" \
  docs/datadog-auth-examples.md "$BASE/docs/datadog-auth-examples.md" >/dev/null

pr_review=$(ensure_pr "feature/review-queue-hardening" "feat: add review queue risk classifier" "Adds a simple risk heuristic to help prioritize review work.")
pr_auth=$(ensure_pr "feature/datadog-auth-examples" "docs: add Datadog authentication examples" "Adds concrete environment variable examples for local setup.")

# Add review comments and labels for readiness and risk tracking.
gh pr edit -R "$REPO" "$pr_review" --add-label "review-priority" || true
gh pr edit -R "$REPO" "$pr_auth" --add-label "documentation" || true
gh pr comment -R "$REPO" "$pr_review" --body "Risk note: touches review prioritization logic and should be checked carefully before merge. CI context looks important here."
gh pr comment -R "$REPO" "$pr_review" --body "Readiness note: logic is small, but I would want passing CI and one more reviewer before merging."
gh pr comment -R "$REPO" "$pr_auth" --body "This one looks close to ready. The examples are clear and the scope is docs-only."

# Build release history directly on main with older timestamps.
main_sha=$(get_head_sha "$DEFAULT_BRANCH")
cat > "$BASE/docs/releases/v2.3.0.md" <<'EOF'
# Titan v2.3.0
- baseline exporter support
- existing retry policy
EOF
sha_v230=$(create_tree_and_commit "$DEFAULT_BRANCH" "$main_sha" "release: prepare v2.3.0 baseline" "2026-03-01T09:00:00Z" \
  docs/releases/v2.3.0.md "$BASE/docs/releases/v2.3.0.md")
gh api -X POST repos/$OWNER/$NAME/git/refs -f ref="refs/tags/v2.3.0" -f sha="$sha_v230" >/dev/null || true
gh release create -R "$REPO" v2.3.0 --target "$sha_v230" --title "v2.3.0" --notes "Baseline release for exporter and retry policy." >/dev/null || true

cat > "$BASE/services/exporter/datadog_export.py" <<'EOF'
from .datadog_auth import datadog_auth_headers

def export_dashboards() -> dict[str, object]:
    return {"resource": "dashboard", "auth_headers_present": all(datadog_auth_headers().values())}

def export_monitors() -> dict[str, object]:
    return {"resource": "monitor", "auth_headers_present": True}

def export_metrics() -> dict[str, object]:
    return {"resource": "metric", "auth_headers_present": True}
EOF
sha_metrics=$(create_tree_and_commit "$DEFAULT_BRANCH" "$sha_v230" "feat(exporter): add datadog metric export" "2026-03-12T11:30:00Z" \
  services/exporter/datadog_export.py "$BASE/services/exporter/datadog_export.py")

cat > "$BASE/.tmp_release_ci.yml" <<'EOF'
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo "smoke checks"
      - run: echo "release diagnostics"
EOF
sha_ci=$(create_tree_and_commit "$DEFAULT_BRANCH" "$sha_metrics" "ci: add release diagnostics output" "2026-03-18T14:00:00Z" \
  .github/workflows/ci.yml "$BASE/.tmp_release_ci.yml")

cat > "$BASE/docs/releases/v2.4.0.md" <<'EOF'
# Titan v2.4.0
- Datadog metric export
- improved release diagnostics
EOF
sha_v240=$(create_tree_and_commit "$DEFAULT_BRANCH" "$sha_ci" "release: prepare v2.4.0" "2026-03-20T16:00:00Z" \
  docs/releases/v2.4.0.md "$BASE/docs/releases/v2.4.0.md")
gh api -X POST repos/$OWNER/$NAME/git/refs -f ref="refs/tags/v2.4.0" -f sha="$sha_v240" >/dev/null || true
gh release create -R "$REPO" v2.4.0 --target "$sha_v240" --title "v2.4.0" --notes "Adds Datadog metric export and improved release diagnostics." >/dev/null || true

echo "Expanded history completed: PRs $pr_review $pr_auth, releases v2.3.0 v2.4.0"
