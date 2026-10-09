#!/usr/bin/env bash
# Make the repository's labels match the list below, which is the source of truth,
# and make sure the standing "Next" and "Later" milestones exist.
#
#   .github/sync-labels.sh            create or update every listed label
#   .github/sync-labels.sh --prune    also delete labels that are not listed
#
# Labels describe what an issue is and what it waits on. The issue forms also set
# the matching issue type (Bug, Feature). When an issue ships is its milestone, not
# a label. Without --prune an unlisted label is only reported: deleting one strips
# it from every issue and pull request that carries it.

set -euo pipefail

REPO="${REPO:-Rouzax/TrackSplit}"

# name|colour|description
# Names and colours match CrateDigger's list; keep the two repos in step.
# .github/dependabot.yml applies "dependencies"; Dependabot silently drops a label that
# does not exist, so keep it listed.
LABELS="$(cat <<'EOF'
bug|d73a4a|Something isn't working
enhancement|a2eeef|New feature or request
documentation|0075ca|Improvements or additions to documentation
needs-info|fbca04|Waiting on the reporter for details
needs-upstream|5319e7|Waiting on an external project or tool: CrateDigger, ffmpeg, mutagen, a player
dependencies|0366d6|Pull requests that update a dependency file
question|d876e3|Further information is requested
duplicate|cfd3d7|This issue or pull request already exists
invalid|e4e669|This doesn't seem right
wontfix|ffffff|This will not be worked on
good first issue|7057ff|Good for newcomers
help wanted|008672|Extra attention is needed
EOF
)"

# title|description
MILESTONES="$(cat <<'EOF'
Next|Planned for the next release; renamed to its version when it ships.
Later|Accepted, not yet planned for a release.
EOF
)"

prune=false
case "${1:-}" in
    "") ;;
    --prune) prune=true ;;
    *) echo "usage: sync-labels.sh [--prune]" >&2; exit 2 ;;
esac

while IFS='|' read -r name color description; do
    gh label create "$name" --repo "$REPO" --color "$color" --description "$description" --force >/dev/null
    echo "ok       $name"
done <<< "$LABELS"

listed="$(cut -d'|' -f1 <<< "$LABELS")"
gh label list --repo "$REPO" --limit 200 --json name --jq '.[].name' | while IFS= read -r name; do
    grep -qxF "$name" <<< "$listed" && continue
    if $prune; then
        gh label delete "$name" --repo "$REPO" --yes >/dev/null
        echo "deleted  $name"
    else
        echo "unlisted $name (kept; --prune deletes it)"
    fi
done

# At release time "Next" is renamed to the version and closed, so recreating it here
# opens the fresh "Next" for the following release.
existing="$(gh api "repos/$REPO/milestones?state=all&per_page=100" --jq '.[].title')"
while IFS='|' read -r title description; do
    if grep -qxF "$title" <<< "$existing"; then
        echo "ok       milestone $title"
    else
        gh api "repos/$REPO/milestones" -f title="$title" -f description="$description" >/dev/null
        echo "created  milestone $title"
    fi
done <<< "$MILESTONES"
