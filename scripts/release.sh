#!/usr/bin/env bash
# release.sh [-n|--dry-run] patch|minor|major|X.Y.Z
# Bump convention (CHANGELOG.md): patch = wording/bug fix · minor = something new to learn, old dirs still work · major = existing feature dirs/habits break.
# Steps: CHANGELOG `## Unreleased` must have bullets → becomes `## X.Y.Z — date`; bump plugin.json + marketplace.json; commit;
#        tag awesome-figma--vX.Y.Z (claude plugin tag --push); push main; GitHub Release with that changelog section (needs `gh` logged in).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
dry=0; case "${1:-}" in -n|--dry-run) dry=1; shift ;; esac
[ "$dry" = 1 ] || [ -z "$(git status --porcelain)" ] || { echo "release: working tree not clean" >&2; git status --short >&2; exit 1; }
cur=$(python3 -c "import json;print(json.load(open('.claude-plugin/plugin.json'))['version'])")
new=$(python3 - "$cur" "${1:-patch}" <<'PY'
import sys,re
cur,arg=sys.argv[1],sys.argv[2]
if re.fullmatch(r"\d+\.\d+\.\d+",arg): print(arg); sys.exit()
M,m,p=map(int,cur.split("."))
try: print({"major":f"{M+1}.0.0","minor":f"{M}.{m+1}.0","patch":f"{M}.{m}.{p+1}"}[arg])
except KeyError: sys.exit(f"release: unknown bump '{arg}' (patch|minor|major|X.Y.Z)")
PY
)
today=$(date +%Y-%m-%d)
notes=$(mktemp "${TMPDIR:-/tmp}/awesome-release.XXXXXX")
trap 'rm -f "$notes"' EXIT

# CHANGELOG: Unreleased must be non-empty; write it to $notes; rewrite the file unless dry-run
python3 - "$new" "$today" "$notes" "$dry" <<'PY'
import re,sys
v,d,notes,dry=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]=="1"
p='CHANGELOG.md'; s=open(p,encoding='utf-8').read()
m=re.search(r'^## Unreleased\n(.*?)(?=^## |\Z)',s,re.S|re.M)
if not m: sys.exit("release: CHANGELOG.md has no '## Unreleased' section")
body=m.group(1).strip("\n")
if not re.search(r'^\s*[-*] \S',body,re.M): sys.exit("release: '## Unreleased' in CHANGELOG.md is empty — write what changed before releasing")
if re.search(rf'^## {re.escape(v)} ',s,re.M): sys.exit(f"release: CHANGELOG.md already has a section for {v}")
open(notes,'w',encoding='utf-8').write(body+"\n")
if not dry:
    s=s[:m.start()]+f"## Unreleased\n\n## {v} — {d}\n\n"+body+"\n\n"+s[m.end():].lstrip("\n")
    open(p,'w',encoding='utf-8').write(s)
PY

if [ "$dry" = 1 ]; then
  echo "release (dry-run): $cur → $new  ($today)"; echo "--- notes:"; cat "$notes"; exit 0
fi

python3 - "$new" <<'PY'
import json,sys
v=sys.argv[1]
for path,key in (('.claude-plugin/plugin.json',None),('.claude-plugin/marketplace.json','plugins')):
    with open(path,encoding='utf-8') as f: d=json.load(f)
    if key: d[key][0]['version']=v
    else: d['version']=v
    with open(path,'w',encoding='utf-8') as f: json.dump(d,f,indent=2,ensure_ascii=False); f.write('\n')
PY

git add CHANGELOG.md .claude-plugin/plugin.json .claude-plugin/marketplace.json
git -c commit.template= commit -q -m "release: awesome-figma v$new"
claude plugin tag --push -m "awesome-figma v%s" .
git push
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh release create "awesome-figma--v$new" --title "awesome-figma v$new" --notes-file "$notes" && echo "GitHub Release awesome-figma v$new created"
else
  echo "gh not available / not logged in — create the GitHub Release by hand from tag awesome-figma--v$new with:"; cat "$notes"
fi
echo "released awesome-figma v$new (was $cur)"
