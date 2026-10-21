#!/usr/bin/env bash
# 진행판 작업 로그 맨 위에 실제 시각을 찍어 한 줄 추가한다. 시각을 손으로 적지 않기 위함.
#   scripts/log.sh "base 측정 완료"
set -euo pipefail
F="$(cd "$(dirname "$0")/.." && pwd)/PROGRESS.md"
python3 - "$F" "$(date '+%m/%d %H:%M')" "$(date '+%H:%M')" "$*" <<'PY'
import re, sys, pathlib
f, stamp, hm, msg = pathlib.Path(sys.argv[1]), *sys.argv[2:]
s = f.read_text()
s = re.sub(r"갱신: .*", f"갱신: {stamp}", s, count=1)
s = s.replace("## 작업 로그\n\n", f"## 작업 로그\n\n- {hm} {msg}\n", 1)
f.write_text(s)
PY
