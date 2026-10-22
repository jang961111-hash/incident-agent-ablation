#!/bin/bash
# pptx -> pdf -> png(60dpi) 순차 렌더 + 대조표. 사용: bash deck/concepts/render.sh
cd "$(dirname "$0")"
PROFILE=""
PV="${PREVIEW_DIR:-/tmp/concepts_preview}"; mkdir -p "$PV"
# 미리보기: Noto Sans KR 미설치 환경이라 렌더용 사본만 Nanum Gothic 으로 만든다 (제출 pptx 는 Noto Sans KR)
(cd .. && DECK_FONT="Nanum Gothic" OUT_DIR="$PV" NODE_PATH=node_modules node concepts/build_concepts.js >/dev/null)
# pptxgenjs 가 동아시아 글꼴 charset 을 -122(중국어)로 써서 한글 대체 글꼴이 들쭉날쭉해진다: 129(한글)로 고친다
fixcs() { python3 - "$@" <<'PY'
import sys, zipfile, shutil, os
for f in sys.argv[1:]:
    t = f + ".tmp"
    with zipfile.ZipFile(f) as zi, zipfile.ZipFile(t, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            b = zi.read(it.filename)
            if it.filename.endswith(".xml"): b = b.replace(b'charset="-122"', b'charset="129"')
            zo.writestr(it, b)
    shutil.move(t, f)
PY
}
fixcs concept_*.pptx "$PV"/concept_*.pptx
for f in concept_*.pptx; do
  n="${f%.pptx}"
  cp "$PV/$f" "./_pv_$f"
  perl -e 'alarm 120; exec @ARGV' nice -n 10 soffice $PROFILE --headless --convert-to pdf --outdir . "_pv_$f" >/dev/null 2>&1 || echo "render fail: $f"
  rm -f "${n}"-*.png
  pdftoppm -r 60 -png "_pv_$n.pdf" "$n" && rm -f "_pv_$n.pdf" "_pv_$f"
done
python3 - <<'EOF'
from PIL import Image, ImageDraw, ImageFont
import glob, os
names = {1: "Corporate Red Executive", 2: "Ops Console Dark", 3: "Fintech Minimal", 4: "Architecture Blueprint", 5: "Warm Story"}
font = None
for fp in ["/System/Library/Fonts/AppleSDGothicNeo.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf"]:
    if os.path.exists(fp): font = ImageFont.truetype(fp, 26); small = ImageFont.truetype(fp, 18); break
rows = sorted(glob.glob("concept_*.pptx"))
tw, th, lab, pad = 600, 338, 260, 16
sheet = Image.new("RGB", (lab + 3 * (tw + pad) + pad, len(rows) * (th + pad) + pad), "white")
d = ImageDraw.Draw(sheet)
for r, f in enumerate(rows):
    n = f[:-5]; k = int(n.split("_")[1]); y = pad + r * (th + pad)
    d.text((pad, y + 10), f"{k}.", fill="black", font=font)
    d.text((pad, y + 50), names[k], fill="black", font=small)
    for c, p in enumerate(sorted(glob.glob(n + "-*.png"))[:3]):
        im = Image.open(p).convert("RGB").resize((tw, th))
        x = lab + pad + c * (tw + pad); sheet.paste(im, (x, y)); d.rectangle([x, y, x + tw - 1, y + th - 1], outline="#BBBBBB")
sheet.save("contact_sheet.png"); print("sheet", sheet.size)
EOF
