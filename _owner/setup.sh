#!/usr/bin/env bash
# Run by an org owner after the scaffold pull request merges and before the publish pull request merges.
# The checks ruleset requires Registry Gate, which exists once validate.yml has run on a pull request.
set -euo pipefail

repo=TableProApp/integrations
here=$(cd "$(dirname "$0")" && pwd)

gh api -X PATCH "repos/$repo" \
  -F has_wiki=false -F has_projects=false -F has_discussions=false \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=BLANK \
  -F delete_branch_on_merge=true -F allow_auto_merge=false >/dev/null

gh api -X PUT "repos/$repo/private-vulnerability-reporting"
gh api -X PUT "repos/$repo/immutable-releases"
gh api -X PUT "repos/$repo/actions/permissions" -F enabled=true -f allowed_actions=all -F sha_pinning_required=true
gh api -X PUT "repos/$repo/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false
gh api -X PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=first_time_contributors

while IFS='|' read -r name color description; do
  gh label create "$name" --repo "$repo" --color "$color" --description "$description" --force
done <<'LABELS'
new integration|0e8a16|Adds an entry
update|1d76db|Changes an entry
removal|b60205|Removes an entry
curation|5319e7|Changes curation files
tooling|c5def5|Changes scripts, schemas or workflows
tier: official|0052cc|Entry is Official
tier: partner|006b75|Entry is Partner
tier: community|bfdadc|Entry is Community
tier change|d93f0b|Changes an entry's tier
grace period|fbca04|Entry has a pre-policy grace period
needs owner consent|e99695|Author is not the owner; needs consent in a comment
multiple entries|e99695|Touches more than one entry
waiting on author|fef2c0|Closes after 21 days without a reply
stale|ededed|No reply for 14 days
health|f9d0c4|Weekly health check
report|d73a4a|Report about a listed entry
removal request|d73a4a|Publisher asks to archive or remove
suggestion|c2e0c6|Suggested integration
LABELS

existing=$(gh api "repos/$repo/rulesets" --jq '.[].name')
for file in "$here/ruleset-checks.json" "$here/ruleset-review.json"; do
  name=$(jq -r .name "$file")
  if grep -Fxq "$name" <<<"$existing"; then
    echo "Ruleset already exists: $name"
  else
    gh api -X POST "repos/$repo/rulesets" --input "$file" >/dev/null
    echo "Created ruleset: $name"
  fi
done

if ! gh api "repos/$repo/pages" >/dev/null 2>&1; then
  gh api -X POST "repos/$repo/pages" -f build_type=workflow >/dev/null
fi
gh api -X PUT "repos/$repo/pages" -f build_type=workflow -f cname=integrations.tablepro.app

echo "Next: add the CNAME integrations -> tableproapp.github.io (DNS only). Once the certificate is issued:"
echo "  gh api -X PUT repos/$repo/pages -F https_enforced=true"
