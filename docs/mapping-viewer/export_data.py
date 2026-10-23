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
    cards/cards.json                ai-bom/cards 의 규제 카드 132장 (ISO/IEC 42001 은 원문·구절을 빼고 제목만)
    cards/vocabulary.json, cards/profile.json   통제 어휘, 매핑 프로파일 (ai-bom/cards 그대로)
    cards/extraction.json           추출기가 카드마다 낸 초안과 정답의 비교 (자기 카드 용어 제외)
    cards/judgments/*.json          aibom-examples 의 BOM 에 판정 엔진을 돌린 기록 (옆 폴더가 있을 때만)
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
# aibom-examples 는 저장소 밖(/mnt/yhchoe/aibom-examples). AIBOM_EXAMPLES 로 바꿀 수 있다
EXAMPLES = os.environ.get("AIBOM_EXAMPLES") or os.path.join(os.path.dirname(os.path.dirname(CLI)), "aibom-examples", "results", "0.2.0")
EXAMPLE_BOMS = ("aiapp-demo.v0.6.cdx.json", "nanoGPT.v0.6.cdx.json", "python-slim.v0.6.cdx.json")


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
    return card


def cards():
    """ai-bom/cards 의 카드·어휘·프로파일을 복사하고, 추출기 비교와 예제 BOM 판정 기록을 만든다."""
    sys.path.insert(0, CARDS); sys.path.insert(0, os.path.join(CARDS, "extract")); sys.path.insert(0, os.path.join(CARDS, "judge"))
    from lexicon import build_lexicon, card_text, load_cards, load_vocab
    from extract import extract
    from build_cards import ABBR_TO_NAME
    import judge as J
    out = os.path.join(OUT, "cards"); os.makedirs(os.path.join(out, "judgments"), exist_ok=True)
    gold, vocab = load_cards(), load_vocab()
    iso = {c["card_id"] for c in gold if c["regulation"]["title"].startswith("ISO/IEC")}
    with open(os.path.join(out, "cards.json"), "w", encoding="utf-8") as fh:
        json.dump([public_card(c) for c in gold], fh, ensure_ascii=False, indent=1)
    shutil.copy(os.path.join(CARDS, "vocabulary.json"), os.path.join(out, "vocabulary.json"))
    shutil.copy(os.path.join(CARDS, "profiles", "aibom-cyclonedx.json"), os.path.join(out, "profile.json"))
    # 추출기 비교: 카드마다 자기 용어를 뺀 용어집으로 영어 원문을 추출해 정답과 맞춘다
    comparison = []
    for c in gold:
        lexicon = build_lexicon(gold, vocab, {c["card_id"]})
        pred, explain = extract(ABBR_TO_NAME[c["card_id"].split("-")[1]], c["source"]["clause_id"], card_text(c), lexicon, vocab)
        gold_concepts = {f["concept"]: f for f in c["facts"]}
        pred_facts = [f for f in pred["facts"] if f["concept"] != "UNRESOLVED"]
        hidden = c["card_id"] in iso
        comparison.append({
            "card_id": c["card_id"], "confidence": pred["confidence"], "status": pred["status"],
            "actor": pred["obligation"]["actor"], "action": pred["obligation"]["action"], "object": pred["obligation"]["object"],
            "object_scope": pred["obligation"]["object_scope"], "gold_actor": c["obligation"]["actor"],
            "facts": [{"concept": f["concept"], "clause": f.get("clause"), "span": None if hidden else (f.get("highlight_en") or f.get("gap_highlight_en")),
                       "gold_clause": gold_concepts.get(f["concept"], {}).get("clause"),
                       "result": "hit" if f["concept"] in gold_concepts else "extra"} for f in pred_facts],
            "missed": [k for k in gold_concepts if k not in {f["concept"] for f in pred_facts}],
            "conditions": [] if hidden else [x["text"] for x in pred["conditions"]],
            "exceptions": [] if hidden else [x["text"] for x in pred["exceptions"]],
        })
    with open(os.path.join(out, "extraction.json"), "w", encoding="utf-8") as fh:
        json.dump(comparison, fh, ensure_ascii=False, indent=1)
    # 예제 BOM 판정
    index = []
    profile = J.load_profile(os.path.join(CARDS, "profiles", "aibom-cyclonedx.json"))
    bom_paths = [os.path.join(CARDS, "judge", "examples", "recruit-screening.cdx.json")]       # 특허 실시예를 흉내 낸 작은 BOM
    if os.path.isdir(EXAMPLES):
        bom_paths += [os.path.join(EXAMPLES, n) for n in EXAMPLE_BOMS]
    if True:
        for path in bom_paths:
            name = os.path.basename(path)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                bom = json.load(fh)
            record = J.judge(bom, gold, profile, {})
            fname = name.replace(".cdx.json", ".json")
            with open(os.path.join(out, "judgments", fname), "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=1)
            index.append({"file": fname, "subject": record["bom"]["subject"], "summary": record["summary"]})
    with open(os.path.join(out, "judgments", "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    return len(gold), len(index)


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
