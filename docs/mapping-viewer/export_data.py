#!/usr/bin/env python3
"""ai-bom 의 데이터에서 필드 레퍼런스 뷰어가 읽는 파일을 만든다 → docs/mapping-viewer/data/.

    conda run -n ai-bom python docs/mapping-viewer/export_data.py      # aibom-cli/ 에서. ai-bom 은 옆 폴더(../ai-bom)

복사하는 것 (ai-bom/data 그대로):
    aibom_v0.6_cyclonedx.json       CycloneDX 1.7 전체 + v0.6 추가 필드 (added, origin, reference)
    aibom_v0.6_spdx.json            SPDX 3.0.1 전체 + v0.6 추가 필드 (added, path = 대응하는 CycloneDX 경로)
    aibom_v0.6_spdx_mapping.json    두 형식의 대응 (1.7 매핑 + v0.6 추가 필드. 엑셀의 CycloneDX v0.6↔SPDX v0.6 시트와 같은 표)
    aibom_v0.6_requirement_field_mapping.json  규제 요구사항 → v0.6 필드 (엑셀의 요구사항 매핑 시트와 같은 표).
                                    ISO/IEC 42001 행만 본문을 조항 제목으로 바꾼다 (public_requirements)
만드는 것:
    aibom_v0.6_properties.json      추가 필드를 --spec 1.7 로 낼 때의 properties 키 (정의서 생성 코드와 같은 규칙)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.dirname(os.path.dirname(HERE))
AIBOM = os.path.join(os.path.dirname(CLI), "ai-bom")
DATA = os.path.join(AIBOM, "data")
OUT = os.path.join(HERE, "data")
COPY = ("aibom_v0.6_cyclonedx.json", "aibom_v0.6_spdx.json", "aibom_v0.6_spdx_mapping.json",
        "aibom_v0.6_requirement_field_mapping.json")
# 여기서 만들지 않지만 뷰어가 읽는 파일 — tests/test_fields.py 가 만든다. 지우지 않는다.
KEEP = ("aibom_cli_sources.json",)


def save(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


# 저작권이 있는 표준. 필드 탐색기는 공개 문서 사이트에 실리므로 본문(원문 번역)을 싣지 않고 조항 제목만 싣는다.
# 엑셀은 내부용이라 그대로 둔다.
TITLE_ONLY = {"ISO/IEC 42001": "iso42001.json"}


def public_requirements(rows):
    """TITLE_ONLY 출처의 행은 본문을 그 조항의 한국어 제목으로, 본문에 기대는 칸(강조 문구, 비고)은 비운다."""
    titles = {}
    for source, name in TITLE_ONLY.items():
        with open(os.path.join(DATA, name), encoding="utf-8") as fh:
            titles[source] = {r["id"]: r.get("title_ko") or r.get("title") or "" for r in json.load(fh)}
    out = []
    for r in rows:
        if r["source"] in titles:
            title = titles[r["source"]].get(r["id"])
            if not title:
                raise SystemExit(f"export_data: {r['source']} {r['id']} 의 제목이 없다")
            r = {**r, "requirement_ko": title, "requirement_highlight": [], "requirement_gap_highlight": [], "note": ""}
        out.append(r)
    return out


def properties():
    sys.path.insert(0, os.path.join(AIBOM, "src"))
    from format.v0_6 import properties as P
    from format.fields import property_name
    out = []
    for group in (P.MODEL, P.DATASET):
        for n in P._rows(group):
            kids = P._children(n["path"])
            if not kids:
                out.append({"key": P._key(n), "path": n["path"], "group": group,
                            "description_ko": n["description_ko"], "allowed": P._enum_values(n["type"])})
            for c in kids:
                out.append({"key": f"{property_name(n['path'])}:<i>:{c['name']}", "path": n["path"], "child": c["name"],
                            "group": group, "description_ko": c["description_ko"], "allowed": P._enum_values(c["type"])})
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):                         # 뷰어가 안 읽는 파일은 두지 않는다
        if name.endswith(".json") and name not in KEEP:
            os.remove(os.path.join(OUT, name))
    for name in COPY:
        shutil.copy(os.path.join(DATA, name), os.path.join(OUT, name))
    with open(os.path.join(DATA, "aibom_v0.6_requirement_field_mapping.json"), encoding="utf-8") as fh:
        save("aibom_v0.6_requirement_field_mapping.json", public_requirements(json.load(fh)))
    pr = properties(); save("aibom_v0.6_properties.json", pr)
    print(f"{OUT}: 복사 {len(COPY)}개, properties 키 {len(pr)}개")


if __name__ == "__main__":
    main()
