#!/usr/bin/env python3
"""ai-bom 의 데이터에서 필드 레퍼런스 뷰어가 읽는 파일을 만든다 → docs/mapping-viewer/data/.

    conda run -n ai-bom python docs/mapping-viewer/export_data.py      # aibom-cli/ 에서. ai-bom 은 옆 폴더(../ai-bom)

복사하는 것 (ai-bom/data 그대로):
    aibom_v0.6_cyclonedx.json       CycloneDX 1.7 전체 + v0.6 추가 필드 (added, origin, reference)
    aibom_v0.6_spdx.json            SPDX 3.0.1 전체 + v0.6 추가 필드 (added, path = 대응하는 CycloneDX 경로)
    cdx_spdx_mapping.json           기존 필드의 형식 간 대응
    requirement_field_mapping.json  규제 요구사항 → 필드
만드는 것:
    aibom_v0.6_links.json           v0.6 추가 필드의 형식 간 대응. CycloneDX 쪽 추가 필드 중 SPDX 에 원래 있던 값은
                                    v0.5 때 분석한 매핑(aibom_v0.5_spdx_mapping.json)에서, SPDX 쪽 추가 속성은 그 행의 path 에서
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
COPY = ("aibom_v0.6_cyclonedx.json", "aibom_v0.6_spdx.json", "cdx_spdx_mapping.json", "requirement_field_mapping.json")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def save(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def parse_spdx(text):
    """'AI::AIPackage.ai_hyperparameter.key, Core::Element.name' → [(profile, class, property), ...]. 세 번째 마디(사전 항목의 칸)는 뗀다."""
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part or "::" not in part:
            continue
        profile, rest = part.split("::", 1)
        bits = rest.split(".")
        out.append({"profile": profile, "class": bits[0], "property": bits[1] if len(bits) > 1 else ""})
    return out


def links():
    added_cdx = {r["path"] for r in load("aibom_v0.6_cyclonedx.json") if r.get("added")}
    v05 = {r["path"]: r for r in load("aibom_v0.5_spdx_mapping.json") if r.get("path")}
    out = []
    for path in sorted(added_cdx):                       # CycloneDX 에 더한 필드 중 SPDX 에 원래 있던 값
        row = v05.get(path)
        targets = parse_spdx(row["spdx"]) if row and row.get("spdx") not in (None, "", "-") else []
        if targets:
            out.append({"path": path, "targets": targets, "source": "spdx-base"})
    for r in load("aibom_v0.6_spdx.json"):               # SPDX 에 더한 속성은 자기 CycloneDX 경로를 안다
        if r.get("added") and r.get("path") and r.get("property"):
            out.append({"path": r["path"], "targets": [{"profile": r["profile"], "class": r["class"], "property": r["property"]}],
                        "source": "spdx-added"})
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
        if name.endswith(".json"):
            os.remove(os.path.join(OUT, name))
    for name in COPY:
        shutil.copy(os.path.join(DATA, name), os.path.join(OUT, name))
    lk = links(); save("aibom_v0.6_links.json", lk)
    pr = properties(); save("aibom_v0.6_properties.json", pr)
    print(f"{OUT}: 복사 {len(COPY)}개, links {len(lk)}개 (spdx-base {sum(l['source'] == 'spdx-base' for l in lk)} · "
          f"spdx-added {sum(l['source'] == 'spdx-added' for l in lk)}), properties 키 {len(pr)}개")


if __name__ == "__main__":
    main()
