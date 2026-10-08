#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$CONTEXT/rules"
cp "$(dirname "${BASH_SOURCE[0]}")/prompt.md" "$CONTEXT/prompt.md"
gh pr view "$PR" --json title,body,comments,reviews > "$CONTEXT/pr.json"
gh api graphql --paginate \
  -F owner="${REPO%%/*}" \
  -F name="${REPO#*/}" \
  -F pr="$PR" \
  -f query='
    query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100, after: $endCursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              isResolved
              resolvedBy { login }
              path
              line
              comments(first: 20) { nodes { databaseId author { login } body createdAt } }
            }
          }
        }
      }
    }' \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
         | {id: .comments.nodes[0].databaseId,
            resolved: .isResolved, resolved_by: .resolvedBy.login, path, line,
            comments: [.comments.nodes[] | {author: .author.login, body, at: .createdAt}]}]' \
  | jq -s 'add // []' > "$CONTEXT/review-threads.json"

read -r draft head < <(gh pr view "$PR" --json isDraft,headRefOid --jq '"\(.isDraft) \(.headRefOid)"')
open=$(jq --arg author "$AUTHOR" --arg marker "$MARKER" '[.[] | select(.comments[0].author == $author and (.comments[0].body | contains($marker)) and (.resolved | not))] | length' \
  "$CONTEXT/review-threads.json")
approved=$(gh api --paginate "repos/$REPO/pulls/$PR/reviews?per_page=100" | jq -s --arg author "$AUTHOR[bot]" --arg marker "$MARKER" --arg head "$head" '[.[][] | select(.user.login == $author and .state == "APPROVED" and (.body // "" | contains($marker)) and .commit_id == $head)] | length')
reviewed=$(gh api "repos/$REPO/commits/$head/status" | jq --arg status "$STATUS" '[.statuses[] | select(.context == $status)] | length')

# Mentions since this reviewer's last answer: a comment of its own
# that doesn't open a review thread. Read from the PR as well as the
# triggering comment, since a waiting run is replaced by the next
# event's, and a thread reply fires a review event alongside.
asked=$(jq -s --arg author "$AUTHOR" --arg marker "$MARKER" --arg mention "$MENTION" '
  [(.[0].comments[] | {who: .author.login, body, at: .createdAt, answer: true}),
   (.[0].reviews[] | {who: .author.login, body, at: .submittedAt, answer: false}),
   (.[1][].comments | to_entries[] | .value + {who: .value.author, answer: (.key > 0)})]
  | (map(select(.who == $author and .answer and (.body | contains($marker))) | .at) | max // "") as $answered
  | map(select(.who != $author and .at > $answered
               and ((.body // "") | test($mention + "([^a-zA-Z0-9_-]|$)"; "i"))))
  | length' "$CONTEXT/pr.json" "$CONTEXT/review-threads.json")
skip=""
if [ "$draft" = true ]; then
  skip="the PR is a draft"
elif [ "$approved" -gt 0 ] && [ "$reviewed" -gt 0 ]; then
  skip="already approved $head"
elif [ "$reviewed" -gt 0 ] && [ "$open" -gt 0 ]; then
  skip="already reviewed $head and $open threads are unresolved"
fi
mode=review
case "$EVENT" in
  issue_comment|pull_request_review_comment)
    skip="comment events answer questions only"
    ;;
esac
if [ -n "$skip" ]; then
  mode=skip
  if [ "$asked" -gt 0 ] || grep -qiE "$MENTION([^a-zA-Z0-9_-]|$)" <<< "$COMMENT"; then
    mode=answer
  fi
fi
{
  echo "head=$head"
  echo "open=$open"
  echo "skip=$skip"
  echo "mode=$mode"
  echo "run=$([ "$mode" = skip ] && echo false || echo true)"
} >> "$GITHUB_OUTPUT"
echo "$AUTHOR: $mode ($skip)"

if [ "$mode" != skip ]; then
rev=$(jq -r '.nodes["niteo-claude"].locked.rev // "main"' nix/flake.lock 2>/dev/null || echo main)
echo "teamniteo/claude@$rev: $RULES"
for rule in $RULES; do
  curl -fsSL -o "$CONTEXT/rules/$rule.md" \
    "https://raw.githubusercontent.com/teamniteo/claude/$rev/rules/$rule.md"
done
fi
