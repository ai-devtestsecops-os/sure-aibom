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
    cards/cards.json                ai-bom/cards 의 승인 카드 (호 단위, 190장. ISO/IEC 42001 은 원문·구절을 빼고 제목만). 규제 판정 화면이 조항의 원문과 사실을 보여 줄 때 쓴다
    cards/vocabulary.json, cards/profile.json   통제 어휘, 매핑 프로파일 (ai-bom/cards 그대로)
    cards/boms/*.cdx.json, boms/index.json   예제 BOM 과 목록 (고위험·투명성 의무·범용 AI 모델 하나씩 손으로 만든 것, ai-bom/cards/judge/examples). 화면이 브라우저 안에서 판정하므로 BOM 자체를 두고,
                                    목록에 기본 시스템 프로파일(위험등급·역할)과 파이썬 엔진의 판정 요약을 적어 둔다
추출기 초안과 승인 카드의 비교는 내부용이라 문서 사이트에 싣지 않는다.
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
KEEP = ("aibom_cli_sources.json", "aibom_cli_spdx_sources.json")
CARDS = os.path.join(AIBOM, "cards")
# 규제 판정 화면의 예제 BOM: 고위험 시스템, 투명성 의무만 걸리는 시스템, 범용 AI 모델 하나씩 손으로 만든 작은 BOM (ai-bom/cards/judge/examples).
# (파일, 기본 시스템 프로파일, 버튼 이름, 설명). 위험등급은 시스템 축(high_risk / minimal_risk)에 얹히는 것(limited_risk·gpai·gpai_systemic)을 더한 목록
# 공개 사이트에 올리는 복사본에서는 설명 속성(aibom:example)의 내부용 문구를 바꾼다
EXAMPLE_BOMS = (("recruit-screening.cdx.json", {"risk_class": ["high_risk"], "role": ["provider"]}, "고위험 AI 시스템 · 채용 심사",
                 "채용 지원자를 평가하는 고위험 AI 시스템. 개인데이터 데이터셋에 원래 수집 목적이 빠져 있어 10조(2)(b) 가 부분 반영이다"),
                ("support-chatbot.cdx.json", {"risk_class": ["minimal_risk", "limited_risk"], "role": ["provider"]}, "투명성 의무 · 고객 상담 챗봇",
                 "사람과 대화하는 챗봇. 고위험이 아니라 고위험 조항은 비적용이고 투명성 의무(50조)만 걸린다"),
                ("foundation-llm.cdx.json", {"risk_class": ["minimal_risk", "gpai"], "role": ["provider"]}, "범용 AI 모델 · 기반 LLM",
                 "범용 AI 모델 제공자. 53조와 부속서 XI·XII 의 모델 문서 항목을 본다. 체계적 위험은 없어 55조는 비적용이다"))
HAND_MADE = "채용 심사 AI 를 가정해 손으로 만든 작은 BOM"


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


def public_card(card):
    """TITLE_ONLY 출처의 카드는 원문과 구절을 빼고 제목만 남긴다 (저작권). fact 의 개념·호·조건은 남긴다."""
    if card["regulation"]["title"].startswith("ISO/IEC"):
        card = json.loads(json.dumps(card))
        card["source"] = {"clause_id": card["source"]["clause_id"]}
        for f in card["facts"]:
            for k in ("highlight", "highlight_en", "gap_highlight", "gap_highlight_en"):
                f.pop(k, None)
        card["obligation"]["text"] = ""
        card["notes"] = ""
        for key in ("conditions", "exceptions"):          # 조건·예외 문구도 원문 조각이라 비운다
            card[key] = [{**x, "text": ""} for x in card.get(key, [])]
    return card


def cards():
    """ai-bom/cards 의 카드·어휘·프로파일을 복사하고, 예제 BOM 판정 기록을 만든다."""
    sys.path.insert(0, CARDS); sys.path.insert(0, os.path.join(CARDS, "judge"))
    from common import load_cards, load_gold
    import judge as J
    out = os.path.join(OUT, "cards"); os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):                         # 화면이 안 읽는 파일은 두지 않는다 (예전의 추출 비교 등)
        if name.endswith(".json"):
            os.remove(os.path.join(out, name))
    approved, gold = load_cards(), load_gold()
    shown = approved or gold          # 승인된 카드가 생기면 그것을, 아직 없으면 정답 카드를 보여 준다
    with open(os.path.join(out, "cards.json"), "w", encoding="utf-8") as fh:
        json.dump([public_card(c) for c in shown], fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "source.json"), "w", encoding="utf-8") as fh:
        json.dump({"cards": "approved" if approved else "gold", "count": len(shown)}, fh)
    with open(os.path.join(CARDS, "vocabulary.json"), encoding="utf-8") as fh:
        voc = json.load(fh)
    for c in voc["concepts"]:
        c.pop("synonyms_private", None)                  # 저작권 있는 원문의 구절은 문서 사이트에 싣지 않는다
    with open(os.path.join(out, "vocabulary.json"), "w", encoding="utf-8") as fh:
        json.dump(voc, fh, ensure_ascii=False, indent=1)
    shutil.copy(os.path.join(CARDS, "profiles", "aibom-cyclonedx.json"), os.path.join(out, "profile.json"))
    # 예제 BOM. 화면이 브라우저 안에서 판정하므로(cards.js 의 judgeBom) 판정 기록이 아니라 BOM 자체를 둔다. 시스템 프로파일은 화면의 기본값
    index = []
    boms = os.path.join(out, "boms"); os.makedirs(boms, exist_ok=True)
    for name in os.listdir(boms):
        os.remove(os.path.join(boms, name))
    old = os.path.join(out, "judgments")                 # 예전의 미리 낸 판정 기록. 더는 안 쓴다
    if os.path.isdir(old):
        shutil.rmtree(old)
    bom_paths = [(os.path.join(CARDS, "judge", "examples", n), system, label, note) for n, system, label, note in EXAMPLE_BOMS]
    profile = J.load_profile(os.path.join(CARDS, "profiles", "aibom-cyclonedx.json"))
    for path, system, label, note in bom_paths:
        name = os.path.basename(path)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            bom = json.load(fh)
        for prop in (bom.get("metadata") or {}).get("properties") or []:
            if prop.get("name") == "aibom:example":
                prop["value"] = prop["value"].replace("특허 실시예를 흉내 낸 작은 BOM", HAND_MADE)
        with open(os.path.join(boms, name), "w", encoding="utf-8") as fh:
            json.dump(bom, fh, ensure_ascii=False, indent=1)
        record = J.judge(bom, shown, profile, system)      # 파이썬 엔진의 결과를 같이 적어 둔다 (화면과 맞는지 보는 기준)
        index.append({"file": name, "subject": record["bom"]["subject"], **({"label": label} if label else {}), "note": note,
                      "size": os.path.getsize(os.path.join(boms, name)), "system_profile": system, "engine_summary": record["summary"]})
    with open(os.path.join(boms, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    return len(shown), len(index)


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
    n_cards, n_judg = cards()
    print(f"{OUT}: 복사 {len(COPY)}개, properties 키 {len(pr)}개, 카드 {n_cards}장, 판정 기록 {n_judg}개")


if __name__ == "__main__":
    main()
