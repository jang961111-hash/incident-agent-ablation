"""Canva로 가져갈 pptx 의 모든 글자에 한글 글꼴을 직접 적는다.

Canva 는 테마 글꼴(+mn-lt)과 맥 전용 글꼴을 읽지 못해 한글 글상자가 겹쳐 보인다.
슬라이드, 레이아웃, 마스터의 run 속성(rPr, defRPr, endParaRPr)에 latin, ea 글꼴과 lang=ko-KR 을 넣는다.
이미 latin 이 있으면(예: Courier New 코드) 그대로 두고 ea 만 더한다.

    python3 scripts/canva_fonts.py deck/incident-agent-ablation_5min_canva.pptx [--font "Noto Sans KR"]
"""
import argparse
import re
import shutil
import zipfile

ap = argparse.ArgumentParser()
ap.add_argument("pptx")
ap.add_argument("--font", default="Noto Sans KR")
a = ap.parse_args()
F = a.font
TAGS = ("a:rPr", "a:defRPr", "a:endParaRPr")


def fix(xml: str) -> str:
    xml = xml.replace('lang="en-US"', 'lang="ko-KR"')
    for tag in TAGS:
        # 자기 닫힘 → 글꼴 자식을 붙여 연다
        xml = re.sub(rf"<{tag}([^>]*?)/>", rf'<{tag}\1><a:latin typeface="{F}"/><a:ea typeface="{F}"/></{tag}>', xml)

        def body(m):
            attrs, inner = m.group(1), m.group(2)
            if "<a:latin" not in inner:
                inner += f'<a:latin typeface="{F}"/>'
            if "<a:ea" not in inner:
                inner = re.sub(r"(<a:latin [^>]*/>)", rf'\1<a:ea typeface="{F}"/>', inner, count=1)
            return f"<{tag}{attrs}>{inner}</{tag}>"
        xml = re.sub(rf"<{tag}((?:\s[^>]*)?)>(.*?)</{tag}>", body, xml, flags=re.S)
    return xml


tmp = a.pptx + ".tmp"
n = 0
with zipfile.ZipFile(a.pptx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for it in zin.infolist():
        d = zin.read(it.filename)
        if re.match(r"ppt/(slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$", it.filename):
            d = fix(d.decode()).encode()
            n += 1
        zout.writestr(it, d)
shutil.move(tmp, a.pptx)
print(f"{a.pptx}: {n}개 XML 에 '{F}' 지정")
