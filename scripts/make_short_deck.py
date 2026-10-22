"""전체 덱에서 5분 발표용 장만 뽑아 새 pptx 를 만든다 (장 순서도 바꿀 수 있다).

    python3 scripts/make_short_deck.py deck/incident-agent-ablation.pptx deck/incident-agent-ablation_5min.pptx
    python3 scripts/make_short_deck.py IN OUT --keep 1,2,3,6,4,11,16,17

뽑은 뒤 pptx 스킬의 clean.py 로 안 쓰는 슬라이드 파일을 지우면 더 가볍다 (없어도 열린다).
"""
import argparse
import re
import zipfile

# 표지 · 한 장 요약 · 실태 현황 · 문제 1 · 결론 · 기여도 표 · 시연 · 한계
DEFAULT_KEEP = [1, 2, 3, 6, 4, 11, 16, 17]

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--keep", default=",".join(map(str, DEFAULT_KEEP)))
a = ap.parse_args()
keep = [int(x) for x in a.keep.split(",")]

zin = zipfile.ZipFile(a.src)
rels = zin.read("ppt/_rels/presentation.xml.rels").decode()
rid2slide = {m.group(1): int(m.group(2))
             for m in re.finditer(r'Id="(rId\d+)"[^>]*Target="slides/slide(\d+)\.xml"', rels)}
pres = zin.read("ppt/presentation.xml").decode()
lst = re.search(r"<p:sldIdLst>(.*?)</p:sldIdLst>", pres, re.S).group(1)
by = {rid2slide[re.search(r'r:id="(rId\d+)"', it).group(1)]: it for it in re.findall(r"<p:sldId [^>]*/>", lst)}
pres = pres.replace(lst, "".join(by[k] for k in keep))
ids = {re.search(r'id="(\d+)"', by[k]).group(1) for k in keep}
pres = re.sub(r"<p14:sectionLst.*?</p14:sectionLst>",
              lambda m: re.sub(r'<p14:sldId id="(\d+)"/>', lambda x: x.group(0) if x.group(1) in ids else "", m.group(0)),
              pres, flags=re.S)
with zipfile.ZipFile(a.dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = pres.encode() if item.filename == "ppt/presentation.xml" else zin.read(item.filename)
        zout.writestr(item, data)
print(f"{a.dst}: {len(keep)}장 (원본 {len(by)}장)")
