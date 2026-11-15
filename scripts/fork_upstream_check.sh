#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: scripts/fork_upstream_check.sh [PATH...]' \
    '       scripts/fork_upstream_check.sh --search "terms"' \
    '       scripts/fork_upstream_check.sh --help' \
    'Without paths, checks branch changes plus uncommitted and untracked files.'
}

mode=paths
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --search)
    if [[ $# -ne 2 || -z "$2" ]]; then usage >&2; exit 2; fi
    mode=search
    terms=$2
    shift 2
    ;;
esac
for arg in "$@"; do
  if [[ "$arg" == -* ]]; then usage >&2; exit 2; fi
done
for tool in gh jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$tool" >&2
    exit 1
  fi
done
UPSTREAM_REPO=${UPSTREAM_REPO:-chunkhound/chunkhound}

# Sanitize even titles and paths: pasted output must not create cross-references.
sanitize='
  def safe:
    gsub("[A-Za-z][A-Za-z0-9+.-]*://[^[:space:]]+"; "[URL omitted]")
    | gsub("([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#(?<n>[0-9]+)"; "upstream item \(.n)")
    | gsub("[[:cntrl:]]"; " ");
'
if [[ "$mode" == search ]]; then
  printf 'Issues\n'
  gh issue list -R "$UPSTREAM_REPO" --state all --search "$terms" --limit 20 \
    --json number,title,state,updatedAt |
    jq -r "$sanitize"'.[] | "upstream issue \(.number)  \(.state)  \(.updatedAt[:10])  \(.title | safe)"'
  printf '\nPull requests\n'
  gh pr list -R "$UPSTREAM_REPO" --state all --search "$terms" --limit 20 \
    --json number,title,state,updatedAt |
    jq -r "$sanitize"'.[] | "upstream PR \(.number)  \(.state)  \(.updatedAt[:10])  \(.title | safe)"'
  exit 0
fi

if [[ $# -eq 0 ]]; then
  base=$(git merge-base HEAD origin/main)
  changed=$(mktemp)
  trap 'rm -f "$changed"' EXIT
  git diff --name-only -z "$base" -- > "$changed"
  git ls-files --others --exclude-standard -z >> "$changed"
  mapfile -d '' -t paths < "$changed"
  if [[ ${#paths[@]} -eq 0 ]]; then
    echo 'No changed paths; supply PATH arguments to check upstream activity.'
    exit 0
  fi
else
  paths=("$@")
fi

gh pr list -R "$UPSTREAM_REPO" --state open --limit 200 \
  --json number,title,author,isDraft,updatedAt,files |
  jq -r "$sanitize"'
    ($ARGS.positional | map(sub("/+$"; "")) | unique) as $paths
    | length as $total
    | [ .[]
        | . + {overlap: ([.files[].path
            | select(. as $file | any($paths[];
                . as $prefix | $prefix == "" or $file == $prefix or ($file | startswith($prefix + "/"))))] | unique)}
        | select(.overlap | length > 0)
      ] | sort_by(.number) | reverse
    | (if length == 0 then "No open upstream pull request touches these paths."
       else .[] |
         "upstream PR \(.number)  \(.updatedAt[:10])  \(.author.login | safe)  \(if .isDraft then "[draft]  " else "" end)\(.title | safe)",
         (.overlap[:10][] | "  \(. | safe)"),
         (if (.overlap | length) > 10 then "  … and \((.overlap | length) - 10) more" else empty end)
       end),
      "\(length) of \($total) open upstream pull requests overlap"
  ' --args "${paths[@]}"
