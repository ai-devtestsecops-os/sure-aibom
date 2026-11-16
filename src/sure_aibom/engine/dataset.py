"""스캔 대상 안의 데이터셋을 찾아 type=data 컴포넌트로 만든다 (D-BOM). 병합과 M-BOM 보강 뒤, 규제 정규화 앞에서 돈다.

출처 두 가지:
    1) Hugging Face 데이터셋 참조
       - cdxgen 이 로컬 모델 README 의 datasets: 로 만든 type=data 컴포넌트 (purl, data[].name "datasets/<id>", group "datasets",
         data[].contents.url 의 허브 데이터셋 주소에서 id 를 얻는다)
       - 로컬 모델 README 의 YAML 헤더에서 model-index[].results[].dataset.type(평가). cdxgen 은 평가 데이터셋을 표시 이름만
         적어 두므로 sure-aibom 이 README 를 직접 읽는다. 읽을 README 는 cdxgen 이 모델 컴포넌트의 evidence 에 남긴 것이다.
       - 스캔 대상 디렉터리의 파이썬 소스에서 load_dataset("owner/name") — 첫 위치 인자가 허브 id 모양일 때만.
         load_dataset("csv", data_files=…) 같은 로컬 빌더와 파일 경로는 허브 id 가 아니라 넘긴다.
         revision="…" 인자가 문자열이면 그 리비전으로 묻는다. 같은 id 를 리비전을 달리해(또는 없이) 부르면 정하지 않고 최신으로 묻는다.
       - 코드가 부르는 허브 모델(pkg:huggingface 모델 컴포넌트)의 모델 카드. 모델마다 GET {HF_ENDPOINT}/api/models/<id> 를
         한 번 불러 응답 cardData 의 datasets(학습)와 model-index[].results[].dataset.type(평가)을 모은다. 허브 id 꼴인 것만.
         허브 모델인지는 model.py 의 hub_model_id 로 가른다 (로컬 모델 파일에서 찾은 모델은 뺀다).
       - scan --data hf://datasets/<id>[@<리비전>] 으로 직접 준 것 (huggingface_hub 의 HfFileSystem 표기). 코드에서 찾은 것과 같은 모양으로
         만든다. 리비전은 코드의 revision= 보다 우선한다. 저장소는 있는데 그 리비전이 없다고 허브가 답하면(404) scan 이 도구를 돌리기
         전에 오류로 끝낸다 (missing_revisions). 저장소가 없는 것과 비공개인 것은 허브가 둘 다 401 로 답해 구분하지 않는다.
       리비전(--data 나 코드의 revision=)이 있으면 GET {HF_ENDPOINT}/api/datasets/<id>/revision/<리비전> 으로 묻고 version 은 응답의 전체
       커밋 해시이며, 조회가 안 되면 리비전을 그대로 둔다. datasets-server 는 최신 리비전만 보므로 최신이 아니면 /size·/statistics 를 묻지 않는다.
       네트워크가 닿으면 GET {HF_ENDPOINT}/api/datasets/<id> 로 채우고, 닿지 않으면 이름·purl 만 두고 한 번 알린다.
       규제 필드는 size·modality·availability·provenance·statistics 에 더해 intendedUse(task_categories·task_ids),
       collectionProcess(annotations_creators·language_creators)를 카드 머리말에서 읽고, provenance 에는 source_datasets 의 상위 데이터셋도 넣는다.
       datasets-server 의 /size(README 앞머리에 크기가 없을 때의 바이트 크기)와 /statistics(config·split 별 열 통계)도 본다.
       컴포넌트가 없으면 만들고(bom-ref = purl pkg:huggingface/datasets/<id>), 있으면 제자리에서 채운다.
       허브가 돌려준 id 가 정식 id 다: 옛 이름(imdb → stanfordnlp/imdb)이나 두 이름(bookcorpus, bookcorpus/bookcorpus)으로 부른
       같은 데이터셋은 정식 id 의 컴포넌트 하나로 모으고 (purl·bom-ref 를 바꾸고, 가리키던 관계·modelCard ref 도 따라간다) 한 번만 조회한다.
       조회한 컴포넌트의 purl·bom-ref 는 pkg:huggingface/datasets/<정식 id> 다 (cdxgen 이 purl 없이 만든 것도 맞춘다).
    2) 로컬 데이터 파일: scan --data 로 지목한 경로(hf:// 로 시작하지 않는 값)에서만 읽는다. 스캔 대상은 데이터 파일을 찾으려고 걷지 않는다
       (확장자만으로 추측하면 웹앱의 아이콘 같은 것도 데이터셋이 된다).
       경로 하나가 컴포넌트 하나 (bom-ref "data:local/<폴더 이름>@", 이름이 겹치면 -2, -3 을 붙인다). 파일 하나를 지목하면
       그 파일만으로 만든다. 같은 경로를 두 번 주면 한 번만 읽는다.
       data[] 의 단위는 파일 종류에 따라 둘이다. 표·레코드 파일(csv, parquet, jsonl, npy …)은 파일마다 componentData 하나
       {type: dataset, name: <폴더 이름>/<상대 경로>}. 매체 파일(이미지·오디오)은 폴더 단위로 하나
       {name: <폴더 이름>/<하위 폴더>/*.<형식>, 형식이 섞이면 *.{jpg,png}} — 이미지 수십만 장이 원소 수십만 개가 되지 않게, 그리고 CycloneDX 의
       componentData 가 "데이터의 모음" 단위이기 때문이다. 원소에는 type 과 name 만 적는다. 파일별 크기·해시·행 수 같은 도구 사실은
       정의서(aibom:dataset:*)에 없는 키라 출력에 넣지 않는다. 값은 전부 컴포넌트의 규제 필드로 모은다: 크기 합은 size, 확장자는
       modality, 표 파일의 열 통계와 매체 파일의 헤더(이미지 너비·높이, 오디오 길이) 분포는 statistics — datasets-server 가 image·audio
       열에 주는 것과 같은 종류다. 지목한 곳이라 json·txt 도 데이터로 치되, README·LICENSE·*config.json·
       dataset_info.json 같은 잘 알려진 메타데이터 이름은 뺀다. 점으로 시작하는 폴더·파일, SKIP_DIRS, 지목한 경로 밖으로
       나가는 심볼릭 링크는 건너뛴다.
       규제 필드는 size·modality·statistics 셋만 채운다 — 출처(provenance)와 가용성(availability)은 파일만 보고 알 수 없다.
       분석은 표준 라이브러리만 쓴다 (parquet·arrow·feather 는 pyarrow 가 있을 때만). pickle 은 절대 읽지 않는다.
       열 통계(숫자 열은 min·max·mean·median·std, 글 열은 길이의 그 통계, 라벨 열은 n_unique·mode·frequencies)는
       csv·tsv·jsonl·json·parquet·arrow 에서 64 MB 까지만 낸다. 허브 datasets-server 가 주는 것과 같은 종류다.

데이터셋 사실(size, modality, availability, provenance, statistics)은 aibom-internal:dataset:* 프로퍼티로 컴포넌트에 두고,
form 이 고른 형태의 자리로 옮기며 지운다 — 출력에는 남지 않는다.

관계: 로컬 데이터셋, 코드에서 찾은 HF 데이터셋, --data 로 준 HF 데이터셋은 metadata.component(루트)가 dependsOn 한다. 허브·로컬 모델 카드의
datasets 와 model-index, GGUF 헤더의 general.datasets 에서 온 것은 그 모델이 dependsOn 하고 모델카드
modelParameters.datasets 에 ref 로 적는다 (루트는 잇지 않는다). 모델 카드 조회가 실패한 허브 모델은 그대로 둔다.
학습(datasets, general.datasets)·평가(model-index) 역할과 허브 응답의 lastModified 는 CycloneDX 에 자리가 없어 facts(메모리 부가
기록, facts.py)에 두고 SPDX 변환기가 trainedOn·testedOn 관계와 releaseTime 으로 적는다. CycloneDX 출력에는 없다.
"""
from __future__ import annotations

import ast
import csv
import json
import math
import os
import re
import struct
import zipfile
from collections import Counter
from statistics import fmean, median, stdev
from pathlib import Path, PurePosixPath
from typing import Iterable

import yaml

from ..external import hub
from ..utils.files import SKIP_DIRS, inside, notebook_code, relative
from ..utils.licenses import card_licenses
from .facts import Facts
from .merge import fill_missing
from .form import INTERNAL_PREFIX
from .model import MODEL_TYPE, _inside_file, hub_model_id

DATA_TYPE = "data"
DATASET_KIND = "dataset"       # data[].type 의 다섯 값 중 D-BOM 으로 치는 것
LOCAL_REF_PREFIX = "data:local/"

HF_DATASETS_PURL = "pkg:huggingface/datasets/"
_HF_DATASET_PURL = re.compile(r"^pkg:huggingface/datasets/(?P<id>[^@?#]+)")
_HF_DATASET_URL = re.compile(r"^https?://huggingface\.co/datasets/(?P<id>[^?#]+?)/?$")
_HF_ID = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?$")
HF_DATA_ARG = "hf://datasets/"                   # scan --data 로 허브 데이터셋을 주는 표기. huggingface_hub 의 HfFileSystem 경로와 같다
_HF_REVISION = re.compile(r"^[^\s@]+$")          # 브랜치·태그·커밋 해시. 짧은 해시도 허브가 전체 해시로 풀어 준다

CARD_NAME = "readme.md"                          # 로컬 모델 폴더의 모델 카드 (대소문자 무시)
CARD_MAX_BYTES = 8 * 1024 ** 2                   # 모델 카드를 통째로 읽는 상한
_FRONT_MATTER = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)   # README 맨 앞의 YAML 헤더

# 확장자 → 모달리티. --data 로 지목한 경로 안에서 이 확장자의 파일이 데이터다.
MODALITY_BY_EXTENSION: dict[str, str] = {
    "csv": "structured", "tsv": "structured", "parquet": "structured", "arrow": "structured", "feather": "structured",
    "npy": "structured", "npz": "structured",
    "jsonl": "text", "ndjson": "text", "json": "text", "txt": "text",
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image",
    "wav": "audio", "mp3": "audio", "flac": "audio",
}
DATA_EXTENSIONS = frozenset(MODALITY_BY_EXTENSION)
MEDIA_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "wav", "mp3", "flac"})   # 폴더 단위(이미지끼리, 오디오끼리)로 묶는 파일. 나머지는 파일마다
FORMAT_ALIASES = {"jpeg": "jpg"}                                                      # 같은 형식의 다른 확장자는 이름에서 하나로
# 샤드: 한 분할을 크기 때문에 여러 조각으로 나눈 파일. train-00001-of-00004.parquet, part-0001.csv. 조각들은 원소 하나로 합친다
_SHARD_STEM = re.compile(r"^(?P<stem>.+?)-\d+-of-\d+$|^(?P<stem2>.+?)[-_]\d{4,}$")
METADATA_NAMES = frozenset({"metadata.csv", "metadata.jsonl"})       # Hugging Face imagefolder·audiofolder 의 주석 표. file_name 열이 있어야 한다
FILE_COLUMNS = frozenset({"file_name", "file", "filename", "path", "filepath", "image", "audio"})   # 주석 표에서 파일을 가리키는 열 (통계 안 냄)
SPLIT_NAMES = frozenset({"train", "training", "test", "testing", "eval", "evaluation", "validation", "valid", "val", "dev"})  # 허브의 분할 이름. 클래스 폴더가 아니다
ANNOTATION_DIRS = frozenset({"labels", "annotations"})                # YOLO labels/*.txt, COCO annotations/*.json. 데이터가 아니라 주석
# 데이터 경로 안에 있어도 데이터가 아닌 잘 알려진 이름 (문서·설정·datasets 의 save_to_disk 메타데이터)
_NON_DATA_NAME = re.compile(r"^(requirements[\w.-]*\.txt|readme.*|license.*|notice.*|changelog.*|package(-lock)?\.json"
                            r"|tsconfig\.json|.*config\.json|manifest\.json|composer\.json"
                            r"|dataset_info\.json|dataset_dict\.json|state\.json)$", re.IGNORECASE)

# 허브 modality:<x> 태그 → v0.6 허용값. 태그가 있으면 이것을 쓰고, 없을 때만 task_categories 로 추론한다.
MODALITY_BY_TAG: dict[str, str] = {"text": "text", "image": "image", "audio": "audio", "video": "video",
                                   "tabular": "structured", "timeseries": "timeseries", "graph": "graph"}

# task_categories → 모달리티 (접두어 일치, 우선순위 순)
MODALITY_BY_TASK: tuple[tuple[str, str], ...] = (
    ("text-to-speech", "audio"), ("text-to-audio", "audio"), ("text-to-video", "video"),        # "text-" 보다 먼저 봐야 한다
    ("text-", "text"), ("token-classification", "text"), ("question-answering", "text"), ("summarization", "text"),
    ("translation", "text"), ("fill-mask", "text"), ("sentence-similarity", "text"), ("feature-extraction", "text"),
    ("image-", "image"), ("object-detection", "image"), ("depth-estimation", "image"), ("mask-generation", "image"),
    ("zero-shot-image", "image"), ("unconditional-image", "image"),
    ("audio-", "audio"), ("automatic-speech-recognition", "audio"), ("voice-", "audio"),
    ("video-", "video"),
    ("tabular-", "structured"), ("time-series", "timeseries"), ("graph-", "graph"),
)

# load_dataset 의 첫 인자가 이것이면 허브 id 가 아니라 로컬 빌더다
LOCAL_BUILDERS = frozenset({"csv", "json", "jsonl", "parquet", "text", "arrow", "pandas", "imagefolder", "audiofolder",
                            "videofolder", "webdataset", "xml", "sql", "generator", "spark", "polars"})

JSON_PARSE_LIMIT = 64 * 1024 ** 2               # json 배열 길이를 세려고 통째로 읽는 상한
CSV_FIELD_LIMIT = 2 ** 31 - 1                   # csv 모듈 기본값 131072 는 문서 하나가 한 칸인 NLP 표에 모자란다
# 파일 하나를 읽다 나는 예외 — 크기·해시만 적고 계속 간다
_READ_ERRORS = (OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile, csv.Error, SyntaxError, TypeError, AttributeError)
STATISTIC_KEYS = ("min", "max", "mean", "median", "std")      # datasets-server 가 숫자형 열에 주는 통계. v0.6 의 예시(mean, median, range …)와 같은 계열
MEASURE_BY_COLUMN_TYPE = {"string_text": "length", "list": "length", "image": "width", "audio": "duration"}   # 숫자가 아닌 열은 무엇의 통계인지
LABEL_COLUMN_TYPES = frozenset({"class_label", "string_label", "bool"})
FREQUENCIES_LIMIT = 10                                        # 범주가 이보다 많으면 frequencies·mode 는 적지 않는다 (n_unique 만)
STATISTICS_REQUEST_LIMIT = 12                                 # 데이터셋 하나에 config×split 통계 조회 상한
STATISTICS_FILE_LIMIT = JSON_PARSE_LIMIT                      # 로컬 파일 열 통계는 이 크기까지만 (값을 메모리에 올린다)


# ── 진입점 ──────────────────────────────────────────────────────────────────

def discover_datasets(merged: dict, target: str, log=print, report: dict | None = None, data_paths: Iterable[str] = (),
             model_infos: dict | None = None, hub_reachable: bool | None = None, facts: Facts | None = None) -> dict:
    """병합 문서에 데이터셋 컴포넌트를 더한다. 찾은 것이 없으면 문서는 바이트 단위로 그대로다.
    data_paths 는 scan --data 값들로, 로컬 데이터 경로이거나 hf://datasets/<id>[@<리비전>] 꼴의 허브 데이터셋이다 (split_data_args).
    model_infos 는 M-BOM 보강이 받아 둔 허브 모델 id → Hub API 응답이고,
    주면 허브 모델 카드를 다시 받지 않는다 (주지 않으면 여기서 받는다). hub_reachable 은 M-BOM 보강이 허브에 닿는지 본
    결과이고, None 이면 물을 것이 있을 때 여기서 본다. report 를 주면 hub_unreachable(허브에 물을 것이 있는데 허브에 닿지
    않았는지), empty_data_paths(데이터 파일이 하나도 없던 경로), unresolved_hub_data(허브에 닿는데 조회가 안 된 --data 허브 데이터셋)를
    적는다. facts 를 주면 모델 카드 데이터셋의 역할(학습·평가)과 허브 응답의 lastModified 를 거기 적는다 (문서에는 자리가 없다)."""
    local_paths, given = split_data_args(data_paths)              # given: --data 로 준 허브 데이터셋 id → 리비전 (안 주면 None)
    components: list[dict] = merged.setdefault("components", [])
    by_hf_id: dict[str, dict] = {}
    for comp in components:
        hf_id = hf_dataset_id_of(comp)
        if hf_id and hf_id not in by_hf_id:
            by_hf_id[hf_id] = comp

    root = Path(target)
    code_calls = _scan_sources(root, log) if root.is_dir() else {}      # id → [(그것을 부른 소스 파일, revision= 값)]
    revisions = _code_revisions(code_calls, log)                         # 물을 리비전. --data 로 준 것이 코드의 것보다 우선한다
    for hf_id, revision in given.items():
        if revision:
            if revisions.get(hf_id, revision) != revision:
                log(f"[dataset] {hf_id}: --data revision {revision} used over {revisions[hf_id]} in code")
            revisions[hf_id] = revision

    # --data 로 준 것도 코드에서 찾은 것과 같은 모양으로 만들고 루트가 dependsOn 한다. evidence 에는 코드에서 찾은 위치만 적는다
    new_refs: list[str] = []
    for hf_id in sorted(set(code_calls) | set(given)):
        comp = by_hf_id.get(hf_id)
        if comp is None:
            comp = _new_hf_component(hf_id)
            components.append(comp)
            by_hf_id[hf_id] = comp
            new_refs.append(comp["bom-ref"])
        if hf_id in given:
            log(f"[dataset] {hf_id}: given with --data" + (f" at revision {given[hf_id]}" if given[hf_id] else ""))
        if hf_id in code_calls:
            occurrences = comp.setdefault("evidence", {}).setdefault("occurrences", [])
            known = {o.get("location") for o in occurrences}
            occurrences.extend({"location": loc} for loc in dict.fromkeys(loc for loc, _ in code_calls[hf_id]) if loc not in known)

    # 로컬 모델 카드는 파일이라 네트워크 없이 읽는다. 여기서 생긴 데이터셋도 아래 허브 확인과 조회에 들어간다.
    if root.is_dir():
        _datasets_from_local_model_cards(merged, root, by_hf_id, log, facts)
    _datasets_named_by_models(merged, by_hf_id, facts)

    # 허브에 닿는지는 한 번만 본다. 물을 것(허브 모델의 카드, 허브 데이터셋)이 없으면 보지 않는다.
    hub_models = [(c, model_id) for c in components if (model_id := hub_model_id(c))]
    reachable = True
    if hub_models or by_hf_id:
        reachable = hub.hf_reachable() if hub_reachable is None else hub_reachable
        if not reachable:
            n, m = len(by_hf_id), len(hub_models)
            skipped = [f"{n} dataset{'s keep' if n != 1 else ' keeps'} name and purl only"] if n else []
            skipped += [f"{m} hub model card{'s' if m != 1 else ''} not read"] if m else []
            log(f"[dataset] huggingface.co unreachable: {', '.join(skipped)}")
    if reachable and hub_models:
        _datasets_from_model_cards(merged, hub_models, by_hf_id, log, model_infos, facts)

    empty: list[str] = []
    for comp in _data_components(local_paths, log, empty):
        components.append(comp)
        new_refs.append(comp["bom-ref"])

    if new_refs:
        _link_from_root(merged, new_refs)
    unresolved: list[str] = []
    if reachable and by_hf_id:
        unresolved = _fill_from_hub(merged, by_hf_id, log, facts, revisions, given)
    elif not reachable:
        for hf_id, revision in revisions.items():                # 허브에 못 물어도 리비전은 남긴다
            if not by_hf_id[hf_id].get("version"):
                by_hf_id[hf_id]["version"] = revision
    if report is not None:
        report["hub_unreachable"] = not reachable
        report["empty_data_paths"] = empty
        report["unresolved_hub_data"] = [hub_data_arg(hf_id, given[hf_id]) for hf_id in unresolved]
    return merged


def split_data_args(values: Iterable[str]) -> tuple[list[str], dict[str, str | None]]:
    """scan --data 값들을 로컬 데이터 경로와 허브 데이터셋으로 가른다. 허브 데이터셋은 hf://datasets/<id>[@<리비전>] 이고
    id → 리비전(안 주면 None)으로 돌려준다. 같은 id 를 같은 리비전으로 두 번 주면 한 번으로 친다.
    hf:// 로 시작하는데 데이터셋 저장소 하나를 가리키지 않거나, 같은 id 를 다른 리비전으로 주면 ValueError."""
    local: list[str] = []
    given: dict[str, str | None] = {}
    for value in values:
        if not value.startswith("hf://"):
            local.append(value)
            continue
        hf_id, at, revision = value.removeprefix(HF_DATA_ARG).partition("@")
        hf_id = hf_id.rstrip("/")
        if not value.startswith(HF_DATA_ARG) or not _HF_ID.match(hf_id) or (at and not _HF_REVISION.match(revision)):
            raise ValueError(f"--data {value}: not a Hugging Face dataset, use hf://datasets/<owner>/<name>[@<revision>]")
        if hf_id in given and given[hf_id] != (revision or None):
            raise ValueError(f"--data {hf_id}: given with two revisions ({given[hf_id] or 'latest'}, {revision or 'latest'})")
        given[hf_id] = revision or None
    return local, given


def hub_data_arg(hf_id: str, revision: str | None = None) -> str:
    """허브 데이터셋 id 와 리비전을 --data 표기로."""
    return HF_DATA_ARG + hf_id + (f"@{revision}" if revision else "")


def missing_revisions(given: dict[str, str | None]) -> list[tuple[str, str]]:
    """--data 로 리비전을 준 허브 데이터셋 가운데, 저장소는 있는데 그 리비전이 없다고 허브가 답한(404) 것의 (--data 표기, 허브의 오류 문구).
    scan 이 도구를 돌리기 전에 불러 입력 실수로 멈춘다. 저장소가 없거나 비공개라 401 이거나 허브에 닿지 않으면 판단하지 않는다
    (스캔은 이름과 리비전을 남기고 경고한다)."""
    pinned = sorted((hf_id, revision) for hf_id, revision in given.items() if revision)
    if not pinned or not hub.hf_reachable():
        return []
    out: list[tuple[str, str]] = []
    for hf_id, revision in pinned:
        error = hub.fetch_revision_error(hf_id, revision)
        if error and error[0] == 404:
            out.append((hub_data_arg(hf_id, revision), error[1]))
    return out


# ── 데이터셋 판정 ─────────────────────────────────────────────────────────────

def is_dataset(comp: dict) -> bool:
    """D-BOM 으로 세는 컴포넌트. type=data 만으로는 모자라다: cdxgen 이 이미지의 apt 저장소 설정도 data[] 없는
    type=data 로 낸다. data[] 에 dataset 항목이 있거나 허브 데이터셋 id 가 있으면 데이터셋이다."""
    if comp.get("type") != DATA_TYPE:
        return False
    return any(d.get("type") == DATASET_KIND for d in comp.get("data") or []) or hf_dataset_id_of(comp) is not None


def hf_dataset_id_of(comp: dict) -> str | None:
    """type=data 컴포넌트의 Hugging Face 데이터셋 id. purl → data[].name "datasets/<id>" → group "datasets" 의 name →
    data[].contents.url 이나 externalReferences 의 허브 데이터셋 주소. cdxgen 은 모델 카드의 이름만 있는 id 를 datasets/<id> 로,
    owner/name 은 group·name 으로 나누고 purl 없이 주소에만 남긴다. 코드의 huggingface.co/datasets 링크로 만든 것은 data[] 도 없이
    externalReferences 에만 주소가 있다."""
    if comp.get("type") != DATA_TYPE:
        return None
    m = _HF_DATASET_PURL.match(comp.get("purl") or "")
    if m:
        return m["id"].strip("/")
    for d in comp.get("data") or []:
        name = d.get("name") or ""
        if name.startswith("datasets/") and _HF_ID.match(name[len("datasets/"):]):
            return name[len("datasets/"):]
    if comp.get("group") == "datasets" and comp.get("name") and _HF_ID.match(comp["name"]):
        return comp["name"]
    urls = [(d.get("contents") or {}).get("url") for d in comp.get("data") or []]
    urls += [r.get("url") for r in comp.get("externalReferences") or [] if isinstance(r, dict)]
    for url in urls:
        m = _HF_DATASET_URL.match(url) if isinstance(url, str) else None
        if m and _HF_ID.match(hf_id := m["id"].removeprefix("datasets/")):
            return hf_id
    return None


def _new_hf_component(hf_id: str) -> dict:
    group, _, name = hf_id.rpartition("/")
    comp: dict = {"type": DATA_TYPE}
    if group:
        comp["group"] = group
    comp["name"] = name
    comp["bom-ref"] = comp["purl"] = HF_DATASETS_PURL + hf_id
    comp["data"] = [{"type": "dataset", "name": hf_id, "contents": {"url": _hub_url(hf_id)}}]
    return comp


def _hub_url(hf_id: str) -> str:
    return f"https://huggingface.co/datasets/{hf_id}"


# ── 소스 코드 훑기 ────────────────────────────────────────────────────────────

def _scan_sources(root: Path, log) -> dict[str, list[tuple[str, str | None]]]:
    """대상 디렉터리의 파이썬 소스와 노트북에서 load_dataset 으로 부른 HF id 를 찾는다.
    id → [(그것을 부른 소스 파일의 상대 경로, revision= 문자열 또는 None)]."""
    hf_ids: dict[str, list[tuple[str, str | None]]] = {}
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        here = Path(dirpath)
        for filename in sorted(filenames):
            if not filename.endswith((".py", ".ipynb")):
                continue
            path = here / filename
            if not inside(path, root_resolved):
                log(f"[dataset] {relative(path, root)}: skipped, symlink points outside the target")
                continue
            loc = relative(path, root)
            for hf_id, revision in _parse_python(path, log):
                hf_ids.setdefault(hf_id, []).append((loc, revision))
    return hf_ids


def _code_revisions(code_calls: dict[str, list[tuple[str, str | None]]], log) -> dict[str, str]:
    """코드가 load_dataset(..., revision="…") 로 리비전 하나만 정해 부른 id → 그 리비전. 같은 id 를 리비전을 달리하거나 리비전 없이도
    부르면 어느 것인지 정하지 않고(최신으로 묻는다) 알린다."""
    out: dict[str, str] = {}
    for hf_id, calls in code_calls.items():
        revisions = {revision for _, revision in calls}
        if len(revisions) > 1:
            shown = ", ".join(sorted(r or "no revision" for r in revisions))
            log(f"[dataset] {hf_id}: loaded at several revisions in code ({shown}), looked up at the latest")
        elif (revision := next(iter(revisions))):
            out[hf_id] = revision
    return out


def _parse_python(path: Path, log) -> list[tuple[str, str | None]]:
    """소스 하나(.py 또는 .ipynb)에서 load_dataset 으로 부른 (HF 데이터셋 id, revision= 문자열 또는 None) 들. 파싱이 안 되면 건너뛰고 알린다.
    첫 인자가 로컬 빌더(csv, json …)이거나 경로·파일 이름이면 허브 id 가 아니라 넘긴다. revision 이 변수면 None 이다."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(notebook_code(text) if path.suffix == ".ipynb" else text)
    except (SyntaxError, ValueError, OSError, KeyError, TypeError) as e:
        log(f"[dataset] {path.name}: skipped, cannot parse ({e.__class__.__name__})")
        return []
    calls: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _callee(node.func) != "load_dataset":
            continue
        first = _string(node.args[0]) if node.args else None
        if first and first.lower() not in LOCAL_BUILDERS and _looks_like_hub_id(first):
            revision = next((_string(k.value) for k in node.keywords if k.arg == "revision"), None)
            if (first, revision) not in calls:
                calls.append((first, revision))
    return calls


# ── 허브 모델 카드 ────────────────────────────────────────────────────────────

def _datasets_from_model_cards(merged: dict, hub_models: list[tuple[dict, str]], by_hf_id: dict[str, dict], log,
                               infos: dict | None = None, facts: Facts | None = None) -> None:
    """허브 모델마다 모델 카드의 데이터셋을 데이터셋 컴포넌트로 만들어 잇는다 (_link_model_datasets). 모델 카드는 infos
    (M-BOM 보강이 받아 둔 Hub API 응답)에서 읽고, infos 가 없으면 여기서 받는다. 모델 카드를 못 읽었거나 데이터셋이 없는
    모델은 손대지 않는다."""
    for model, model_id in hub_models:
        info = infos.get(model_id) if infos is not None else hub.fetch_model_info(model_id, log)
        card = (info or {}).get("cardData")
        ids = model_card_dataset_ids(card, model_id, log)
        if ids:
            _link_model_datasets(merged, model, ids, by_hf_id, facts=facts, roles=model_card_dataset_roles(card))


def _datasets_from_local_model_cards(merged: dict, root: Path, by_hf_id: dict[str, dict], log, facts: Facts | None = None) -> None:
    """로컬 모델 폴더의 README.md YAML 헤더에서 datasets(학습)와 model-index 결과의 평가 데이터셋(dataset.type)을 읽어 허브 모델
    카드와 같게 잇는다. 읽을 README 는 cdxgen 이 모델 컴포넌트에 남긴 evidence 에서 온다. cdxgen 은 datasets: 를 데이터셋
    컴포넌트로 만들어 의존 관계는 다 잇지만 modelCard 의 datasets 에는 마지막 ref 하나만 남기고, 평가 데이터셋은 표시
    이름(dataset.name)만 이름뿐인 항목으로 적어 두므로 둘 다 ref 로 다시 적는다."""
    try:
        root_resolved = root.resolve()
    except OSError:
        return
    for model in [c for c in merged["components"] if c.get("type") == MODEL_TYPE]:
        for path in _card_files(model, root, root_resolved):
            rel = relative(path, root)
            card = read_card_header(path, rel, log)
            ids = model_card_dataset_ids(card, rel, log)
            if not ids:
                continue
            shown = {d["name"] for d in _model_index_datasets(card)
                     if isinstance(d.get("name"), str) and isinstance(d.get("type"), str) and d["type"].strip() in ids}
            _link_model_datasets(merged, model, ids, by_hf_id, shown, location=rel, facts=facts, roles=model_card_dataset_roles(card))


def _datasets_named_by_models(merged: dict, by_hf_id: dict[str, dict], facts: Facts | None = None) -> None:
    """모델카드 datasets 에 ref 없이 이름만 적힌 owner/name 꼴의 허브 id 를 데이터셋 컴포넌트로 잇는다. cdxgen 은 GGUF 헤더의
    general.datasets 를 이렇게 적는다 (contents.url 에도 id 를 그대로 둔다). 모델 파일 위치를 데이터셋의 evidence 로 더한다.
    general.datasets 는 학습 데이터셋이라 역할은 training 이다."""
    for model in [c for c in merged["components"] if c.get("type") == MODEL_TYPE]:
        entries = ((model.get("modelCard") or {}).get("modelParameters") or {}).get("datasets") or []
        ids = _unique(e["name"].strip() for e in entries if isinstance(e, dict) and not e.get("ref") and isinstance(e.get("name"), str)
                      and "/" in e["name"] and _looks_like_hub_id(e["name"].strip()))
        if ids:
            location = next((o.get("location") for o in (model.get("evidence") or {}).get("occurrences") or []
                             if isinstance(o, dict) and isinstance(o.get("location"), str)), None)
            _link_model_datasets(merged, model, ids, by_hf_id, location=location, facts=facts, roles={i: {"training"} for i in ids})


def _card_files(model: dict, root: Path, root_resolved: Path) -> list[Path]:
    """cdxgen 이 모델 컴포넌트에 남긴 evidence.occurrences 중 README.md. 대상 밖을 가리키면 버린다."""
    found: list[Path] = []
    for occurrence in (model.get("evidence") or {}).get("occurrences") or []:
        location = occurrence.get("location") if isinstance(occurrence, dict) else None
        if not isinstance(location, str) or PurePosixPath(location.replace("\\", "/")).name.lower() != CARD_NAME:
            continue
        path = _inside_file(root, root_resolved, location)
        if path is not None and path not in found:
            found.append(path)
    return found


def read_card_header(path: Path, rel: str, log=print) -> dict | None:
    """모델 카드(README.md) 맨 앞의 YAML 헤더. 헤더가 없으면 None, 읽지 못하면 알리고 None."""
    try:
        if path.stat().st_size > CARD_MAX_BYTES:
            log(f"[dataset] {rel}: model card skipped, larger than {CARD_MAX_BYTES // 1024 ** 2} MB")
            return None
        m = _FRONT_MATTER.match(path.read_text(encoding="utf-8", errors="replace"))
        card = yaml.safe_load(m.group(1)) if m else None
    except (OSError, ValueError, RecursionError, yaml.YAMLError) as e:
        log(f"[dataset] {rel}: model card header skipped, cannot parse ({e.__class__.__name__})")
        return None
    return card if isinstance(card, dict) else None


def _link_model_datasets(merged: dict, model: dict, ids: list[str], by_hf_id: dict[str, dict],
                         shown: Iterable[str] = (), location: str | None = None,
                         facts: Facts | None = None, roles: dict[str, set[str]] | None = None) -> None:
    """ids 마다 데이터셋 컴포넌트를 찾거나 만들어, 모델카드 modelParameters.datasets 에 ref 로 적고 모델이 dependsOn 한다.
    같은 데이터셋을 이름만 적은 항목(이름이 id 이거나 shown 에 든 표시 이름)은 ref 로 바뀐다. location 은 데이터셋을 적은
    파일이라 데이터셋 컴포넌트의 evidence 에 더한다. 루트는 잇지 않는다. roles 는 id → 역할(training·evaluation)이고
    facts 가 있으면 (모델, 데이터셋) 쌍의 역할로 적는다."""
    components = merged["components"]
    refs: list[str] = []
    for hf_id in ids:
        comp = by_hf_id.get(hf_id)
        if comp is None:
            comp = _new_hf_component(hf_id)
            components.append(comp)
            by_hf_id[hf_id] = comp
        if location:
            occurrences = comp.setdefault("evidence", {}).setdefault("occurrences", [])
            if location not in {o.get("location") for o in occurrences}:
                occurrences.append({"location": location})
        if comp["bom-ref"] not in refs:
            refs.append(comp["bom-ref"])
        if facts is not None:
            for role in sorted((roles or {}).get(hf_id, ())):
                facts.add_role(model["bom-ref"], comp["bom-ref"], role)
    _depend(merged, model["bom-ref"], refs)
    params = model.setdefault("modelCard", {}).setdefault("modelParameters", {})
    named = set(ids) | set(shown)
    kept = [e for e in params.get("datasets") or []
            if not (isinstance(e, dict) and not e.get("ref") and e.get("name") in named)]
    have = {e.get("ref") for e in kept if isinstance(e, dict)}
    params["datasets"] = kept + [{"ref": r} for r in refs if r not in have]


def model_card_dataset_ids(card, model_id: str, log=print) -> list[str]:
    """모델 카드 YAML 헤더(Hub API 응답의 cardData, 로컬은 README.md)의 datasets 와 model-index 결과의 dataset.type. 둘 다
    허브 데이터셋 id 를 적는 자리다. 순서는 datasets 다음 model-index, 겹치면 한 번. 허브 id 꼴이 아닌 것은 건너뛰고 알린다."""
    ids: list[str] = []
    for name, _ in _card_dataset_names(card):
        if name in ids:
            continue
        if _looks_like_hub_id(name):
            ids.append(name)
        else:
            log(f"[dataset] {model_id}: model card dataset {name!r} is not a hub id, skipped")
    return ids


def model_card_dataset_roles(card) -> dict[str, set[str]]:
    """허브 id 꼴인 데이터셋마다의 역할. datasets 는 training, model-index 결과의 dataset 은 evaluation (둘 다면 둘 다)."""
    roles: dict[str, set[str]] = {}
    for name, role in _card_dataset_names(card):
        if _looks_like_hub_id(name):
            roles.setdefault(name, set()).add(role)
    return roles


def _card_dataset_names(card) -> list[tuple[str, str]]:
    """모델 카드의 (데이터셋 이름, 역할). datasets 다음 model-index 순서, 빈 이름은 뺀다."""
    if not isinstance(card, dict):
        return []
    names = [(v, "training") for v in _as_list(card.get("datasets")) if isinstance(v, str)]
    names += [(d["type"], "evaluation") for d in _model_index_datasets(card) if isinstance(d.get("type"), str)]
    return [(n.strip(), role) for n, role in names if n.strip()]


def _model_index_datasets(card: dict) -> list[dict]:
    """model-index 결과마다의 dataset 객체 ({name, type, config, split}). 모양이 다른 항목은 넘긴다."""
    out: list[dict] = []
    for entry in _as_list(card.get("model-index")):
        for result in _as_list(entry.get("results")) if isinstance(entry, dict) else []:
            dataset = result.get("dataset") if isinstance(result, dict) else None
            if isinstance(dataset, dict):
                out.append(dataset)
    return out


def _last_segment(text: str) -> str:
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _callee(func: ast.expr) -> str | None:
    """호출 대상 이름. load_dataset(…) 과 datasets.load_dataset(…) 모두 "load_dataset"."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _string(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _looks_like_hub_id(text: str) -> bool:
    """"owner/name" 또는 확장자 없는 맨 이름. 경로(./, ../, \\)와 마지막 조각에 확장자가 붙은 것(script.py, x.xlsx)은 아니다.
    허브 id 에도 점은 올 수 있어(v0.1, Qwen2.5-Math) 숫자만이거나 영숫자가 아닌 글자가 섞인 꼬리는 확장자로 보지 않는다."""
    if not _HF_ID.match(text) or text.startswith("."):
        return False
    ext = _extension(_last_segment(text))
    return not (ext.isalnum() and not ext.isdigit())


# ── --data 경로 → 컴포넌트 ───────────────────────────────────────────────────

def _data_components(paths: Iterable[str], log, empty: list[str]) -> list[dict]:
    """--data 경로마다 컴포넌트 하나. 같은 경로는 한 번만, 폴더 이름이 겹치면 bom-ref 에 -2, -3 을 붙인다.
    한 파일은 한 컴포넌트에만 들어간다 (폴더와 그 안의 파일을 둘 다 주면 먼저 준 쪽이 가진다).
    없거나 새로 넣을 데이터 파일이 하나도 없는 경로는 empty 에 적고 건너뛴다."""
    out: list[dict] = []
    seen: set[Path] = set()
    claimed: set[Path] = set()
    used: set[str] = set()
    for raw in paths:
        given = Path(raw).expanduser()
        try:
            base = given.resolve()
        except OSError:
            base = given
        if base in seen:
            continue
        seen.add(base)
        if base.is_file():
            name = base.stem or base.name
            files = [(base, base.name)] if _extension(base.name) in DATA_EXTENSIONS else []
        elif base.is_dir():
            name = base.name or "data"
            files = _data_files(base, log)
        else:
            files = []
        files = [(path, rel) for path, rel in files if path.resolve() not in claimed]
        if not files:
            log(f"[dataset] {raw}: skipped, no data files")
            empty.append(raw)
            continue
        ref, n = name, 2
        while ref in used:
            ref, n = f"{name}-{n}", n + 1
        used.add(ref)
        claimed.update(path.resolve() for path, _ in files)
        prefix = name if base.is_dir() else None
        tables, media, metadata, annotations = _classify(files, log)
        analyses = _table_entries(tables, prefix, log) + _media_groups(media, prefix, name)
        analyses.sort(key=lambda a: a["path"])
        extra_stats = _metadata_statistics(metadata, name, log)
        extra_size = sum(path.stat().st_size for path, _ in metadata + annotations)
        if annotations:
            log(f"[dataset] {name}: {len(annotations)} annotation files not counted as data ({', '.join(sorted(ANNOTATION_DIRS))})")
        out.append(_data_component(ref, name, analyses, extra_size, extra_stats))
    return out


def _classify(files: list[tuple[Path, str]], log) -> tuple[list, list, list, list]:
    """(표·레코드 파일, 매체 파일, 주석 표, 주석 파일). 주석 표는 file_name 열이 있는 metadata.csv/jsonl, 주석 파일은
    labels/·annotations/ 폴더 아래의 파일이다. 둘 다 data[] 원소가 되지 않는다 — 데이터가 아니라 데이터에 대한 설명이다."""
    tables, media, metadata, annotations = [], [], [], []
    for path, rel in files:
        parts = PurePosixPath(rel).parts
        if any(part.lower() in ANNOTATION_DIRS for part in parts[:-1]):
            annotations.append((path, rel))
        elif path.name.lower() in METADATA_NAMES and _has_file_column(path):
            metadata.append((path, rel))
        elif _extension(path.name) in MEDIA_EXTENSIONS:
            media.append((path, rel))
        else:
            tables.append((path, rel))
    return tables, media, metadata, annotations


def _has_file_column(path: Path) -> bool:
    try:
        columns = _columns_of(path, _extension(path.name)) if path.stat().st_size <= STATISTICS_FILE_LIMIT else {}
    except _READ_ERRORS:
        return False
    return any(c.lower() in FILE_COLUMNS for c in columns)


def _table_entries(files: list[tuple[Path, str]], prefix: str | None, log) -> list[dict]:
    """표·레코드 파일은 파일마다 원소 하나. 샤드(train-00001-of-00004.parquet)는 같은 분할끼리 원소 하나로 합친다."""
    shards: dict[tuple[str, str, str], list[tuple[Path, str]]] = {}
    out: list[dict] = []
    for path, rel in files:
        stem, ext = PurePosixPath(rel).stem, _extension(path.name)
        m = _SHARD_STEM.match(stem)
        if m:
            shards.setdefault((PurePosixPath(rel).parent.as_posix(), m.group("stem") or m.group("stem2"), ext), []).append((path, rel))
            continue
        a = _analyze_file(path, f"{prefix}/{rel}" if prefix else rel, log)
        a["key"] = PurePosixPath(rel).with_suffix("").as_posix()            # 통계 이름 앞머리 (원소가 여럿일 때)
        out.append(a)
    for (folder, stem, ext), group in shards.items():
        if len(group) == 1:                                                  # 혼자면 그냥 파일이다. 통계 앞머리는 분할 이름
            path, rel = group[0]
            a = _analyze_file(path, f"{prefix}/{rel}" if prefix else rel, log)
            a["key"] = f"{folder}/{stem}" if folder != "." else stem
            out.append(a)
            continue
        out.append(_analyze_shards(sorted(group, key=lambda f: f[1]), folder, stem, ext, prefix, log))
    return out


def _analyze_shards(group: list[tuple[Path, str]], folder: str, stem: str, ext: str, prefix: str | None, log) -> dict:
    """샤드 묶음 하나. 크기는 합치고, 통계는 조각들의 열 값을 이어 붙여 낸다 (합쳐서 64 MB 까지)."""
    rel_dir = f"{folder}/" if folder != "." else ""
    display = f"{prefix}/{rel_dir}{stem}-*.{ext}" if prefix else f"{rel_dir}{stem}-*.{ext}"
    out: dict = {"path": display, "format": ext, "modality": MODALITY_BY_EXTENSION.get(ext, "other"), "group": True,
                 "count": len(group), "size": sum(p.stat().st_size for p, _ in group), "key": f"{rel_dir}{stem}"}
    if out["size"] > STATISTICS_FILE_LIMIT:
        return out
    merged: dict[str, list] = {}
    try:
        for path, rel in group:
            for col, values in _columns_of(path, ext).items():
                merged.setdefault(col, []).extend(values)
    except _READ_ERRORS as e:
        log(f"[dataset] {display}: no statistics, cannot read content ({e.__class__.__name__})")
        return out
    if merged:
        out["statistics"] = [(f"{col}:{kind}", value) for col, values in merged.items() for kind, value in _values_statistics(values)]
    return out


def _media_groups(files: list[tuple[Path, str]], prefix: str | None, name: str) -> list[dict]:
    """매체 파일을 (폴더, 모달리티) 단위로 묶는다. ImageFolder 처럼 확장자를 가리지 않고 한 폴더의 이미지 전부(오디오 전부)가
    묶음 하나이고, 묶음 하나가 data[] 원소 하나다: 파일 수와 크기 합만 적고 내용은 읽지 않는다.
    이름은 <prefix>/<폴더>/*.<형식> (형식이 섞이면 *.{jpg,png}, 폴더 바로 아래면 <prefix>/*.<형식>). 파일 하나를 지목했으면(prefix 없음) 그 파일 이름.
    한 폴더 아래 하위 폴더 둘 이상이 같은 형식의 매체만 들고 있으면 클래스 폴더(train/cat, train/dog)로 보고 그 폴더 하나로
    합치며, Hugging Face ImageFolder·AudioFolder 규약대로 파일 바로 위 폴더 이름이 라벨이 되어 label 통계(n_unique·mode·frequencies)를
    낸다. train/animals/cat 처럼 깊어도 라벨은 cat 이고, 깊이가 섞이면 합치되 라벨은 내지 않는다. train·test 같은 분할 폴더는
    클래스가 아니라 합치지 않는다."""
    groups: dict[tuple[str, str], dict] = {}
    for path, rel in files:
        fmt = _media_format(path)
        modality = MODALITY_BY_EXTENSION[fmt]
        folder = PurePosixPath(rel).parent.as_posix()
        g = groups.setdefault((folder, modality), {"folder": folder, "modality": modality, "formats": set(),
                                                   "count": 0, "size": 0, "group": True, "file": rel, "paths": []})
        g["formats"].add(fmt)
        g["count"] += 1
        g["size"] += path.stat().st_size
        g["paths"].append(path)
    # 클래스 폴더 합치기: 깊은 폴더부터 올라가며, 부모에 직접 든 매체가 없고 자식 묶음이 둘 이상이면 부모 하나로
    changed = True
    while changed:
        changed = False
        for parent in sorted({PurePosixPath(f).parent.as_posix() for f, _ in groups if f != "."}, key=lambda p: -p.count("/")):
            for modality in {m for _, m in groups}:
                children = [(f, modality) for f, m in groups if m == modality and f != "." and PurePosixPath(f).parent.as_posix() == parent]
                if len(children) < 2 or (parent, modality) in groups or any(PurePosixPath(f).name.lower() in SPLIT_NAMES for f, _ in children):
                    continue
                groups[(parent, modality)] = _merge_class_folders(parent, modality, [groups.pop(key) for key in sorted(children)])
                changed = True
    # 형제 분할 중 하나가 클래스 폴더로 합쳐졌으면(train/cat, train/dog → train), 클래스가 하나뿐인 형제(test/cat)도 같은 꼴로 합친다
    for (folder, modality), g in list(groups.items()):
        if not g.get("labels") or folder == ".":
            continue
        grand = PurePosixPath(folder).parent.as_posix()
        for (f2, m2), g2 in list(groups.items()):
            parent2 = PurePosixPath(f2).parent.as_posix()
            if m2 == modality and "labels" not in g2 and f2 != "." and parent2 != "." and PurePosixPath(parent2).parent.as_posix() == grand \
                    and parent2 != folder and (parent2, modality) not in groups:
                groups[(parent2, modality)] = _merge_class_folders(parent2, modality, [groups.pop((f2, m2))])
    out = []
    for (folder, modality), g in groups.items():
        formats = sorted(g.pop("formats"))
        glob = f"*.{formats[0]}" if len(formats) == 1 else "*.{" + ",".join(formats) + "}"
        if prefix is None:
            g["path"] = g.get("file", glob)
        elif g["count"] == 1 and "file" in g and "labels" not in g:
            g["path"] = f"{prefix}/{g['file']}"                              # 파일 하나뿐이면 그 이름 그대로
        else:
            g["path"] = f"{prefix}/{folder}/{glob}" if folder != "." else f"{prefix}/{glob}"
        g["format"] = ",".join(formats)
        g["key"] = folder if folder != "." else name                        # 통계 이름 앞머리
        stats: list[tuple[str, str]] = []
        if g.get("labels"):
            stats += [(f"label:{kind}", value) for kind, value in _label_statistics(len(g["labels"]), g["labels"])]
        stats += _media_statistics(g.pop("paths"), modality)
        if stats:
            g["statistics"] = stats
        g.pop("file", None)
        g.pop("folder", None)
        out.append(g)
    return out


def _media_format(path: Path) -> str:
    """확장자를 형식 이름으로 (jpeg → jpg)."""
    ext = _extension(path.name)
    return FORMAT_ALIASES.get(ext, ext)


def _merge_class_folders(parent: str, modality: str, children: list[dict]) -> dict:
    """하위 폴더 묶음들을 부모 폴더 하나로. 라벨은 파일 바로 위 폴더 이름이고 값은 파일 수다(ImageFolder 규약). 이미 합쳐진 자식은
    그 라벨을 그대로 올린다. 파일이 바로 든 자식과 합쳐진 자식이 섞여 있으면 깊이가 달라 라벨을 내지 않는다."""
    merged = {"folder": parent, "modality": modality, "formats": set(), "group": True, "count": 0, "size": 0,
              "labels": {}, "paths": []}
    for child in children:
        merged["count"] += child["count"]
        merged["size"] += child["size"]
        merged["paths"] += child["paths"]
        merged["formats"] |= child["formats"]
        labels = child["labels"] if "labels" in child else {PurePosixPath(child["folder"]).name: child["count"]}
        for label, n in labels.items():
            merged["labels"][label] = merged["labels"].get(label, 0) + n
    if 0 < sum("labels" in c for c in children) < len(children):
        merged["labels"] = {}
    return merged


# ── 매체 헤더 ────────────────────────────────────────────────────────────────
# 이미지는 너비·높이(px), 오디오는 길이(초)의 분포를 낸다. datasets-server 가 image 열에 width, audio 열에 duration 을 주는 것과 같고,
# 높이는 허브에 없지만 헤더에 같이 있어 더 낸다.
# 파일 내용은 읽지 않고 헤더만 본다 (PNG IHDR, JPEG SOF, WebP VP8/VP8L/VP8X, WAV fmt·data, FLAC STREAMINFO, MP3 프레임 헤더와 Xing).

MEDIA_HEADER_BYTES = 64 * 1024
MEDIA_HEADER_LIMIT = 4 * 1024 * 1024                          # JPEG 는 EXIF 뒤에 SOF 가 올 수 있어 여기까지 더 읽는다
MEASURES_BY_MODALITY = {"image": ("width", "height"), "audio": ("duration",)}   # 통계로 내는 측정값과 그 순서
_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_MP3_BITRATES = {"1": (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
                 "2": (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}
_MP3_SAMPLE_RATES = {"1": (44100, 48000, 32000), "2": (22050, 24000, 16000), "2.5": (11025, 12000, 8000)}


def _media_statistics(paths: list[Path], modality: str) -> list[tuple[str, str]]:
    """묶음 안 파일들의 너비·높이(이미지) 또는 길이(오디오) 분포. 헤더를 못 읽는 파일은 뺀다. 하나도 못 읽으면 빈 목록."""
    measures = MEASURES_BY_MODALITY.get(modality)
    if not measures:
        return []
    values: dict[str, list[float]] = {m: [] for m in measures}
    for path in paths:
        try:
            measured = _media_measure(path, _media_format(path)) or {}
        except (OSError, struct.error, IndexError, KeyError, ValueError, ZeroDivisionError):
            measured = {}
        for m in measures:
            v = measured.get(m)
            if v is not None and math.isfinite(v) and v > 0:
                values[m].append(v)
    # 허브의 열 이름 자리에 모달리티를 쓴다: train:image:width:min
    return [(f"{modality}:{m}:{kind}", value) for m in measures if values[m] for kind, value in _numeric_statistics(values[m])]


def _media_measure(path: Path, fmt: str) -> dict[str, float] | None:
    """헤더에서 읽은 측정값. 이미지는 {width, height} (px), 오디오는 {duration} (초). 못 읽으면 None."""
    with path.open("rb") as fh:
        head = fh.read(MEDIA_HEADER_BYTES)
        if fmt == "png":
            size = _png_size(head)
        elif fmt == "jpg":
            size = _jpeg_size(fh, head)
        elif fmt == "webp":
            size = _webp_size(head)
        else:
            size = None
        if size is not None:
            return {"width": float(size[0]), "height": float(size[1])}
        if fmt == "wav":
            duration = _wav_duration(head, path.stat().st_size)
        elif fmt == "flac":
            duration = _flac_duration(head)
        elif fmt == "mp3":
            duration = _mp3_duration(head, path.stat().st_size)
        else:
            duration = None
        return {"duration": duration} if duration is not None else None


def _png_size(b: bytes) -> tuple[int, int] | None:
    if b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR" or len(b) < 24:
        return None
    return struct.unpack(">II", b[16:24])


def _jpeg_size(fh, head: bytes) -> tuple[int, int] | None:
    """마커를 따라가며 SOF(프레임 헤더)의 (너비, 높이). APP 세그먼트(EXIF 등)가 길면 더 읽는다."""
    if head[:2] != b"\xff\xd8":
        return None
    data, pos = head, 2
    while True:
        while len(data) < pos + 9:
            more = fh.read(MEDIA_HEADER_BYTES)
            if not more or len(data) > MEDIA_HEADER_LIMIT:
                return None
            data += more
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:                                   # 채움 바이트
            pos += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:  # 길이 없는 마커
            pos += 2
            continue
        if marker in (0xD9, 0xDA):                           # 끝 또는 스캔 시작: SOF 를 못 찾았다
            return None
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if marker in _JPEG_SOF:
            height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
            return width, height
        pos += 2 + length


def _webp_size(b: bytes) -> tuple[int, int] | None:
    if b[:4] != b"RIFF" or b[8:12] != b"WEBP" or len(b) < 30:
        return None
    chunk = b[12:16]
    if chunk == b"VP8 " and b[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", b[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and b[20] == 0x2F:
        bits = struct.unpack("<I", b[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        return (b[24] | (b[25] << 8) | (b[26] << 16)) + 1, (b[27] | (b[28] << 8) | (b[29] << 16)) + 1
    return None


def _wav_duration(b: bytes, size: int) -> float | None:
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        return None
    pos, byte_rate, data_size = 12, None, None
    while pos + 8 <= len(b):
        chunk, length = b[pos:pos + 4], struct.unpack("<I", b[pos + 4:pos + 8])[0]
        if chunk == b"fmt " and pos + 20 <= len(b):
            byte_rate = struct.unpack("<I", b[pos + 16:pos + 20])[0]
        elif chunk == b"data":
            data_size = length if length not in (0, 0xFFFFFFFF) else max(size - pos - 8, 0)   # 스트리밍 WAV 는 길이를 안 적는다
            break
        pos += 8 + length + (length & 1)
    if not byte_rate or data_size is None:
        return None
    return data_size / byte_rate


def _flac_duration(b: bytes) -> float | None:
    if b[:4] != b"fLaC" or len(b) < 42 or b[4] & 0x7F != 0:   # 첫 메타데이터 블록은 STREAMINFO(0) 여야 한다
        return None
    v = int.from_bytes(b[18:26], "big")                       # STREAMINFO 10~17 바이트: 샘플 레이트 20비트, 채널 3, 비트 5, 총 샘플 36
    sample_rate, total = v >> 44, v & ((1 << 36) - 1)
    return total / sample_rate if sample_rate and total else None


def _mp3_duration(b: bytes, size: int) -> float | None:
    """ID3v2 태그를 건너뛰고 첫 프레임 헤더를 읽는다. Xing/Info 헤더가 있으면 프레임 수로, 없으면 고정 비트레이트로 본다."""
    pos = 0
    if b[:3] == b"ID3" and len(b) >= 10:
        pos = 10 + (((b[6] & 0x7F) << 21) | ((b[7] & 0x7F) << 14) | ((b[8] & 0x7F) << 7) | (b[9] & 0x7F)) + (10 if b[5] & 0x10 else 0)
    while pos + 4 <= len(b):
        h = b[pos:pos + 4]
        if h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:
            version_bits, layer_bits = (h[1] >> 3) & 3, (h[1] >> 1) & 3
            bitrate_index, rate_index = h[2] >> 4, (h[2] >> 2) & 3
            if version_bits != 1 and layer_bits == 1 and 0 < bitrate_index < 15 and rate_index != 3:      # Layer III 만
                version = {3: "1", 2: "2", 0: "2.5"}[version_bits]
                bitrate = _MP3_BITRATES["1" if version == "1" else "2"][bitrate_index] * 1000
                sample_rate = _MP3_SAMPLE_RATES[version][rate_index]
                mono = (h[3] >> 6) == 3
                samples = 1152 if version == "1" else 576
                side = (17 if mono else 32) if version == "1" else (9 if mono else 17)
                x = pos + 4 + side
                if b[x:x + 4] in (b"Xing", b"Info") and len(b) >= x + 12 and struct.unpack(">I", b[x + 4:x + 8])[0] & 1:
                    return struct.unpack(">I", b[x + 8:x + 12])[0] * samples / sample_rate
                return (size - pos) * 8 / bitrate
        pos += 1
    return None


def _metadata_statistics(metadata: list[tuple[Path, str]], name: str, log) -> list[tuple[str, str]]:
    """주석 표(metadata.csv/jsonl)의 열 통계. 파일을 가리키는 열은 빼고, 표가 있는 폴더 이름(맨 위면 데이터셋 이름)을 앞에 붙인다."""
    out: list[tuple[str, str]] = []
    for path, rel in sorted(metadata, key=lambda f: f[1]):
        folder = PurePosixPath(rel).parent.as_posix()
        key = folder if folder != "." else name
        try:
            columns = _columns_of(path, _extension(path.name))
        except _READ_ERRORS as e:
            log(f"[dataset] {rel}: no statistics, cannot read annotation table ({e.__class__.__name__})")
            continue
        for col, values in columns.items():
            if col.lower() in FILE_COLUMNS:
                continue
            out += [(f"{key}:{col}:{kind}", value) for kind, value in _values_statistics(values)]
    return out


def _data_files(base: Path, log) -> list[tuple[Path, str]]:
    """지목한 폴더 아래의 데이터 파일 (경로, 폴더 기준 상대 경로). 상대 경로 정렬 순이라 결정적이다."""
    found: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        here = Path(dirpath)
        for filename in sorted(filenames):
            if filename.startswith(".") or _extension(filename) not in DATA_EXTENSIONS or _NON_DATA_NAME.match(filename):
                continue
            path = here / filename
            if not inside(path, base):
                log(f"[dataset] {relative(path, base)}: skipped, symlink points outside the data path")
                continue
            if path.is_file():
                found.append((path, relative(path, base)))
    return sorted(found, key=lambda item: item[1])


def _data_component(ref: str, name: str, analyses: list[dict], extra_size: int = 0, extra_stats: list[tuple[str, str]] = ()) -> dict:
    comp: dict = {"type": DATA_TYPE, "name": name, "bom-ref": f"{LOCAL_REF_PREFIX}{ref}@"}
    comp["data"] = [_component_data(a) for a in analyses]
    facts = {                                                     # provenance·availability 는 비운다: 파일이 어디서 왔는지,
        "size": sum(a["size"] for a in analyses) + extra_size,    # 공개 데이터셋을 어떻게 받는지는 로컬 파일만 보고 알 수 없다
        "modality": _unique(a["modality"] for a in analyses),
        "statistics": _local_statistics(analyses, bool(extra_stats)) + list(extra_stats),
    }
    comp["properties"] = internal_properties(facts)
    return comp


def _component_data(a: dict) -> dict:
    """data[] 원소: 종류와 이름뿐이다. 파일 사실(크기·해시·행 수)은 정의서에 없는 키라 적지 않고, 값은 컴포넌트의 규제 필드로 모은다."""
    return {"type": "dataset", "name": a["path"]}


def _local_statistics(analyses: list[dict], force_prefix: bool = False) -> list[tuple[str, str]]:
    """원소별 열 통계를 모은다. 원소가 둘 이상이면(또는 주석 통계가 따로 있으면) 폴더 기준 경로(확장자 뺀)를 앞에 붙여
    허브의 split 자리처럼 쓴다."""
    many = len(analyses) > 1 or force_prefix
    out: list[tuple[str, str]] = []
    for a in analyses:
        key = a.get("key") or PurePosixPath(a["path"]).stem
        out += [(f"{key}:{kind}" if many else kind, value) for kind, value in a.get("statistics") or []]
    return out


def _analyze_file(path: Path, rel: str, log) -> dict:
    """표준 라이브러리로 읽는 파일 사실: 크기·형식·모달리티와, 표 형식이면 열 통계 (64 MB 까지). 내용을 못 읽으면 크기만."""
    ext = _extension(path.name)
    out: dict = {"path": rel, "size": path.stat().st_size, "format": ext, "modality": MODALITY_BY_EXTENSION.get(ext, "other")}
    if out["size"] > STATISTICS_FILE_LIMIT:
        return out
    try:
        statistics = _file_statistics(path, ext)
    except _READ_ERRORS as e:
        log(f"[dataset] {rel}: no statistics, cannot read content ({e.__class__.__name__})")
        return out
    if statistics:
        out["statistics"] = statistics
    return out


def _file_statistics(path: Path, ext: str) -> list[tuple[str, str]]:
    """표 형식 파일의 열마다 통계 (종류, 값). 열 이름이 앞에 붙는다. 모르는 형식은 빈 목록."""
    out: list[tuple[str, str]] = []
    for name, values in _columns_of(path, ext).items():
        out += [(f"{name}:{kind}", value) for kind, value in _values_statistics(values)]
    return out


def _columns_of(path: Path, ext: str) -> dict[str, list]:
    """열 이름 → 값 목록. 값은 스칼라(문자열·숫자·bool·None)만, 중첩 값이 있는 열은 뺀다."""
    if ext in ("csv", "tsv"):
        csv.field_size_limit(max(csv.field_size_limit(), CSV_FIELD_LIMIT))
        with path.open(encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t" if ext == "tsv" else ",")
            header = [h.strip() for h in (next(reader, None) or [])]
            columns: dict[str, list] = {h: [] for h in header if h}
            for row in reader:
                if not row:
                    continue
                for h, v in zip(header, row):
                    if h:
                        columns[h].append(v.strip() if isinstance(v, str) else v)
            return columns
    if ext in ("jsonl", "ndjson"):
        with path.open(encoding="utf-8", errors="replace") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        return _columns_of_records(records)
    if ext == "json":
        with path.open(encoding="utf-8", errors="replace") as fh:
            parsed = json.load(fh)
        return _columns_of_records(parsed) if isinstance(parsed, list) else {}
    if ext in ("parquet", "arrow", "feather"):
        return _columns_of_table(path, ext)
    return {}


def _columns_of_records(records: list) -> dict[str, list]:
    columns: dict[str, list] = {}
    nested: set[str] = set()
    dicts = [r for r in records if isinstance(r, dict)]
    for r in dicts:
        for k in r:
            columns.setdefault(str(k), [])
    for r in dicts:
        for k in columns:
            v = r.get(k)
            if isinstance(v, (dict, list, tuple)):
                nested.add(k)
            columns[k].append(v)
    return {k: v for k, v in columns.items() if k not in nested}


def _columns_of_table(path: Path, ext: str) -> dict[str, list]:
    try:
        import pyarrow as pa
        import pyarrow.feather as feather
        import pyarrow.parquet as pq
        import pyarrow.types as pt
    except ImportError:
        return {}
    if ext == "parquet":
        table = pq.read_table(str(path))
    else:
        try:
            with pa.memory_map(str(path)) as source:
                table = pa.ipc.open_file(source).read_all()
        except pa.ArrowInvalid:
            table = feather.read_table(str(path), memory_map=True)
    columns: dict[str, list] = {}
    for name, col in zip(table.schema.names, table.columns):
        t = col.type
        if pt.is_integer(t) or pt.is_floating(t) or pt.is_boolean(t) or pt.is_string(t) or pt.is_large_string(t) or pt.is_decimal(t):
            columns[name] = [float(v) if pt.is_decimal(t) and v is not None else v for v in col.to_pylist()]
    return columns


def _values_statistics(values: list) -> list[tuple[str, str]]:
    """열 값들 → 통계. 맨 앞은 nan_count(None 과 빈 문자열의 개수. CSV 는 빈 칸 말고는 결측을 적을 방법이 없다). 나머지는
    값이 있는 것만으로: 전부 숫자면 min·max·mean·median·std, 전부 bool 이거나 범주가 적고 반복되면 n_unique·mode·frequencies,
    그 밖의 글은 길이의 통계. datasets-server 가 열 종류별로 주는 것과 같은 규칙이다."""
    if not values:
        return []
    present = [v for v in values if v is not None and v != ""]
    return [("nan_count", str(len(values) - len(present)))] + _present_statistics(present)


def _present_statistics(present: list) -> list[tuple[str, str]]:
    if not present:
        return []
    if all(isinstance(v, bool) for v in present):
        counts = Counter(str(v).lower() for v in present)
        return _label_statistics(len(counts), dict(counts))
    numbers = _as_numbers(present)
    if numbers is not None:
        return _numeric_statistics(numbers)
    texts = [str(v) for v in present]
    counts = Counter(texts)
    if len(counts) <= FREQUENCIES_LIMIT and len(counts) < len(texts):
        return _label_statistics(len(counts), dict(counts))
    return [(f"length:{kind}", value) for kind, value in _numeric_statistics([float(len(t)) for t in texts])]


def _as_numbers(values: list) -> list[float] | None:
    """모든 값이 유한한 수로 읽히면 그 목록, 하나라도 아니면 None. bool 은 수로 치지 않는다."""
    out: list[float] = []
    for v in values:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            f = float(v)
        elif isinstance(v, str):
            try:
                f = float(v)
            except ValueError:
                return None
        else:
            return None
        if not math.isfinite(f):
            return None
        out.append(f)
    return out


def _numeric_statistics(nums: list[float]) -> list[tuple[str, str]]:
    out = [("min", _number(min(nums))), ("max", _number(max(nums))), ("mean", _number(fmean(nums))), ("median", _number(median(nums)))]
    if len(nums) > 1:
        out.append(("std", _number(stdev(nums))))
    return out


def _label_statistics(n_unique, frequencies) -> list[tuple[str, str]]:
    """라벨 열: n_unique, 그리고 범주가 FREQUENCIES_LIMIT 이하면 mode(최빈값, 동률이면 생략)와 frequencies(값=개수, 많은 순)."""
    out: list[tuple[str, str]] = []
    if isinstance(n_unique, int) and not isinstance(n_unique, bool):
        out.append(("n_unique", str(n_unique)))
    if isinstance(frequencies, dict) and frequencies and len(frequencies) <= FREQUENCIES_LIMIT:
        items = sorted(frequencies.items(), key=lambda kv: (-(_int(kv[1]) or 0), str(kv[0])))
        top = [k for k, v in items if v == items[0][1]]
        if len(top) == 1:
            out.append(("mode", str(top[0])))
        out.append(("frequencies", ",".join(f"{k}={v}" for k, v in items)))
    return out


def _number(v) -> str:
    """통계값 표기: 정수는 그대로, 실수는 소수 5자리까지 (정수값이면 정수로). datasets-server 표기와 같다."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return str(v)
        return str(int(v)) if v.is_integer() else str(round(v, 5))
    return str(v)


# ── Hugging Face 허브 ────────────────────────────────────────────────────────

def _fill_from_hub(merged: dict, by_hf_id: dict[str, dict], log, facts: Facts | None = None,
                   revisions: dict[str, str] | None = None, given: Iterable[str] = ()) -> list[str]:
    """허브 응답으로 채우고, 같은 데이터셋을 다른 id 로 부른 컴포넌트는 정식 id 의 컴포넌트 하나로 모은다.
    revisions 는 id → 물을 리비전(--data 나 코드의 revision=)이다. 리비전이 있는 것은 그 리비전으로 묻고, 그 응답이 앞선 조회보다
    우선해 정식 id 의 응답이 된다 (version 은 응답의 전체 커밋 해시). 조회가 안 되면 리비전을 version 으로 남긴다.
    datasets-server 는 최신 리비전만 보므로 리비전이 최신이 아니면 /size·/statistics 는 묻지 않는다.
    given 은 --data 로 준 id 들이고, 돌려주는 것은 그 가운데 조회가 안 된 id 들. 허브에 닿는지는 부르는 쪽(discover_datasets)이 먼저 본다."""
    revisions = revisions or {}
    given = set(given)
    info_by_canonical: dict[str, dict] = {}
    pinned: dict[str, str] = {}                    # 정식 id → 응답을 받은 리비전
    members: dict[str, list[str]] = {}             # 정식 id → 그것을 부른 id 들 (정렬 순서)
    unresolved: list[str] = []
    for hf_id in sorted(by_hf_id):
        revision = revisions.get(hf_id)
        if revision:
            info = hub.fetch_dataset_info(hf_id, log, revision=revision)
        else:
            info = info_by_canonical.get(hf_id) or hub.fetch_dataset_info(hf_id, log)   # 앞선 조회가 정식 id 로 알려 준 것은 다시 묻지 않는다
        canonical = canonical_id(hf_id, info)
        if info and revision:
            if pinned.get(canonical, revision) != revision:
                log(f"[dataset] {canonical}: asked at two revisions ({pinned[canonical]}, {revision}), {revision} used")
            info_by_canonical[canonical] = info
            pinned[canonical] = revision
        elif info:
            info_by_canonical.setdefault(canonical, info)
        else:
            if revision and not by_hf_id[hf_id].get("version"):
                by_hf_id[hf_id]["version"] = revision
            if hf_id in given:
                unresolved.append(hf_id)
        members.setdefault(canonical, []).append(hf_id)

    for canonical, ids in members.items():
        survivor_id = canonical if canonical in ids else ids[0]
        comp = by_hf_id[survivor_id]
        for other in ids:
            if other != survivor_id:
                _absorb(merged, comp, by_hf_id[other], facts)
                log(f"[dataset] {other}: merged into {canonical}, same dataset")
        if survivor_id != canonical:
            _rename(merged, comp, survivor_id, canonical, facts)
            log(f"[dataset] {survivor_id}: renamed to {canonical} (canonical id)")
        elif (m := _HF_DATASET_PURL.match(comp.get("purl") or "")) is None or m["id"].strip("/") != canonical:
            _rename(merged, comp, survivor_id, canonical, facts)   # cdxgen 이 purl 없이 만든 것도 purl·bom-ref 를 정식 id 로 맞춘다
        info = info_by_canonical.get(canonical)
        if info:
            revision = pinned.get(canonical)
            if revision and not _is_latest(canonical, info, log):
                log(f"[dataset] {canonical}: revision {revision} is not the latest, datasets-server size and statistics skipped")
                size, statistics = None, []
            else:
                size = hub.fetch_dataset_size(canonical, log)
                statistics = _fetch_statistics(canonical, info, size, log)
            apply_hub_info(comp, canonical, info, size, statistics)
            if facts is not None:
                facts.set_time(comp["bom-ref"], "releaseTime", info.get("lastModified"))
    return unresolved


def _is_latest(hf_id: str, info: dict, log) -> bool:
    """리비전을 지정해 받은 응답이 지금 기본 브랜치의 최신 커밋과 같은가. 최신을 받지 못하면 아니라고 본다."""
    latest = hub.fetch_dataset_info(hf_id, log)
    return bool(latest) and isinstance(info.get("sha"), str) and latest.get("sha") == info["sha"]


def _fetch_statistics(hf_id: str, info: dict, size: dict | None, log) -> list[tuple[str, str, dict]]:
    """(config, split) 마다 datasets-server 통계를 받는다. 상한을 넘으면 앞쪽만 받고 알린다."""
    pairs = _config_splits(info, size)
    if len(pairs) > STATISTICS_REQUEST_LIMIT:
        log(f"[dataset] {hf_id}: statistics for the first {STATISTICS_REQUEST_LIMIT} of {len(pairs)} config/split pairs only")
        pairs = pairs[:STATISTICS_REQUEST_LIMIT]
    out: list[tuple[str, str, dict]] = []
    for config, split in pairs:
        resp = hub.fetch_dataset_statistics(hf_id, config, split, log)
        if resp and isinstance(resp.get("statistics"), list):
            if resp.get("partial"):
                log(f"[dataset] {hf_id}: {config}/{split} statistics are partial")
            out.append((config, split, resp))
    return out


def _config_splits(info: dict, size: dict | None) -> list[tuple[str, str]]:
    """통계를 물을 (config, split). README 앞머리 dataset_info 에서, 없으면 /size 응답의 splits 에서. 나온 순서대로."""
    card = info.get("cardData") or {}
    pairs: list[tuple[str, str]] = []
    for i in _as_list(card.get("dataset_info")):
        if not isinstance(i, dict):
            continue
        config = str(i.get("config_name") or "default")
        for sp in i.get("splits") or []:
            if isinstance(sp, dict) and sp.get("name"):
                pairs.append((config, str(sp["name"])))
    if not pairs and size:
        for sp in ((size.get("size") or {}).get("splits") or []):
            if isinstance(sp, dict) and sp.get("config") and sp.get("split"):
                pairs.append((str(sp["config"]), str(sp["split"])))
    return list(dict.fromkeys(pairs))


def canonical_id(hf_id: str, info: dict | None) -> str:
    """허브 응답의 id. 허브는 옛 이름(imdb, bookcorpus)을 정식 owner/name 으로 돌려주므로 응답의 id 가 정식 id 다. 없으면 부른 id."""
    cid = (info or {}).get("id")
    cid = cid.strip("/") if isinstance(cid, str) else ""
    return cid if cid and _HF_ID.match(cid) else hf_id


def _absorb(merged: dict, survivor: dict, loser: dict, facts: Facts | None = None) -> None:
    """loser 를 survivor 에 합치고 문서에서 뺀다. survivor 에 없는 값만 채우고 properties·externalReferences·evidence.occurrences 는 합친다."""
    occurrences = (loser.get("evidence") or {}).get("occurrences") or []
    fill_missing(survivor, {k: v for k, v in loser.items() if k not in ("bom-ref", "purl", "evidence")})
    if occurrences:
        target = survivor.setdefault("evidence", {}).setdefault("occurrences", [])
        known = {o.get("location") for o in target}
        target.extend(o for o in occurrences if o.get("location") not in known)
        target.sort(key=lambda o: o.get("location") or "")
    merged["components"] = [c for c in merged["components"] if c is not loser]
    _repoint(merged, loser["bom-ref"], survivor["bom-ref"], facts)


def _rename(merged: dict, comp: dict, old_id: str, new_id: str, facts: Facts | None = None) -> None:
    """컴포넌트의 id 를 정식 id 로. purl·bom-ref 는 pkg:huggingface/datasets/<id>, group/name 은 owner/name,
    data[].name 은 id 로, data[].contents.url 과 externalReferences 의 허브 주소(cdxgen 이 이름만 있는 id 로 만든
    datasets/datasets/<이름> 포함)는 정식 id 의 주소로 바꾼다. data[] 에 데이터셋 항목이 없으면(코드의 링크로 cdxgen 이 만든 것) 만든다.
    다른 컴포넌트·관계가 가리키던 bom-ref 는 따라간다 (facts 의 역할·시각도)."""
    old_ref = comp["bom-ref"]
    group, _, name = new_id.rpartition("/")
    if group:
        comp["group"] = group
    else:
        comp.pop("group", None)
    comp["name"] = name
    comp["bom-ref"] = comp["purl"] = HF_DATASETS_PURL + new_id
    old_ids = {old_id, f"datasets/{old_id}", new_id}
    for d in comp.get("data") or []:
        if d.get("name") in old_ids:
            d["name"] = new_id
        url = (d.get("contents") or {}).get("url")
        if isinstance(url, str) and "/datasets/" in url:
            d["contents"]["url"] = _hub_url(new_id)
    if not any(d.get("type") == DATASET_KIND for d in comp.get("data") or []):
        comp.setdefault("data", []).insert(0, {"type": DATASET_KIND, "name": new_id, "contents": {"url": _hub_url(new_id)}})
    refs: list[dict] = []
    for r in comp.get("externalReferences") or []:
        m = _HF_DATASET_URL.match(r.get("url") or "")
        if m and m["id"] in old_ids:
            r = {**r, "url": _hub_url(new_id)}
        if (r.get("type"), r.get("url")) not in {(x.get("type"), x.get("url")) for x in refs}:
            refs.append(r)
    if refs:
        comp["externalReferences"] = refs
    _repoint(merged, old_ref, comp["bom-ref"], facts)


def _repoint(merged: dict, old: str, new: str, facts: Facts | None = None) -> None:
    """bom-ref old 를 가리키던 곳(dependencies[] 의 ref·dependsOn, modelCard.modelParameters.datasets[].ref)을 new 로 돌린다.
    그 결과 같은 ref 가 된 관계 행과 modelCard 항목은 하나로 합친다. facts 의 역할·시각도 따라간다."""
    if old == new:
        return
    if facts is not None:
        facts.repoint(old, new)
    if merged.get("dependencies"):
        rows: dict[str, dict] = {}
        for row in merged["dependencies"]:
            if row.get("ref") == old:
                row["ref"] = new
            targets = row.get("dependsOn") or []
            if old in targets:
                row["dependsOn"] = sorted({new if t == old else t for t in targets})
            ref = row.get("ref")
            if ref in rows:
                rows[ref]["dependsOn"] = sorted(set(rows[ref].get("dependsOn") or []) | set(row.get("dependsOn") or []))
            else:
                rows[ref] = row
        merged["dependencies"] = list(rows.values())
    for comp in merged.get("components") or []:
        params = (comp.get("modelCard") or {}).get("modelParameters") or {}
        entries = params.get("datasets")
        if not entries:
            continue
        seen: set[str] = set()
        kept: list = []
        for entry in entries:
            ref = entry.get("ref") if isinstance(entry, dict) else None
            if ref == old:
                entry["ref"] = ref = new
            if ref and ref in seen:
                continue
            if ref:
                seen.add(ref)
            kept.append(entry)
        params["datasets"] = kept


def apply_hub_info(comp: dict, hf_id: str, info: dict, size: dict | None = None,
                   statistics: list[tuple[str, str, dict]] = ()) -> None:
    """허브 응답으로 컴포넌트를 채운다. 이미 있는 값은 두고 없는 것만 채운다. 사실은 aibom-internal:dataset:* 로. URL 은 정식 id 로.
    size 는 datasets-server /size 응답, statistics 는 (config, split, /statistics 응답) 목록. 둘 다 없어도 된다."""
    hf_id = canonical_id(hf_id, info)
    card = info.get("cardData") or {}
    if not comp.get("version") and isinstance(info.get("sha"), str):
        comp["version"] = info["sha"]
    if not comp.get("licenses"):
        licenses = card_licenses(card)
        if licenses:
            comp["licenses"] = licenses
    if not comp.get("description"):
        text = " ".join(str(info.get("description") or "").split()) or card.get("pretty_name")
        if isinstance(text, str) and text:
            comp["description"] = text
    if not comp.get("supplier") and isinstance(info.get("author"), str) and info["author"]:
        comp["supplier"] = {"name": info["author"]}
    refs = [{"type": "distribution", "url": _hub_url(hf_id)}]
    if isinstance(info.get("paperswithcode_id"), str) and info["paperswithcode_id"]:
        refs.append({"type": "website", "url": f"https://paperswithcode.com/dataset/{info['paperswithcode_id']}"})
    existing = {(r.get("type"), r.get("url")) for r in comp.get("externalReferences") or []}
    new_refs = [r for r in refs if (r["type"], r["url"]) not in existing]
    if new_refs:
        comp["externalReferences"] = (comp.get("externalReferences") or []) + new_refs

    facts = hub_facts(hf_id, info, size, statistics)
    props = internal_properties(facts)
    if props:
        comp["properties"] = (comp.get("properties") or []) + props


def hub_facts(hf_id: str, info: dict, size: dict | None = None, statistics: list[tuple[str, str, dict]] = ()) -> dict:
    """허브 응답 → 데이터셋 사실. 값이 없는 키는 비워 둔다 (추론하지 않는다). 출처 URL 은 정식 id 로.
    크기는 README 앞머리 dataset_info 의 바이트 합, 없으면 datasets-server /size 의 원본 파일 바이트.
    모달리티는 허브가 붙인 modality:<x> 태그를 먼저 보고, 태그가 없을 때만 task_categories 로 추론한다.
    통계는 datasets-server /statistics 의 열 통계 (split 이름과 열 이름이 앞에 붙는다)."""
    hf_id = canonical_id(hf_id, info)
    card = info.get("cardData") or {}
    tag_modalities = [t[len("modality:"):].strip().lower() for t in _as_list(info.get("tags")) if isinstance(t, str) and t.startswith("modality:")]
    infos = [i for i in _as_list(card.get("dataset_info")) if isinstance(i, dict)]
    sizes = [_int(i.get("dataset_size")) if _int(i.get("dataset_size")) is not None else _int(i.get("download_size")) for i in infos]
    sizes = [s for s in sizes if s is not None]
    server_size = _int((((size or {}).get("size") or {}).get("dataset") or {}).get("num_bytes_original_files"))
    facts: dict = {
        "size": sum(sizes) if sizes else server_size,
        "modality": _unique(MODALITY_BY_TAG.get(t, "other") for t in tag_modalities if t) if tag_modalities
                    else _unique(_modality_of_task(t) for t in _as_list(card.get("task_categories")) if isinstance(t, str)),
        "availability": "registration" if info.get("gated") else "direct-download",
        "provenance": _unique([_hub_url(hf_id)] + [_hub_url(s) for s in _source_datasets(card)]),
        "intendedUse": _intended_use(card),
        "collectionProcess": _collection_process(card),
        "statistics": _hub_statistics(statistics),
    }
    return facts


def _intended_use(card: dict) -> str | None:
    """데이터셋 카드의 task_categories(용도)와 task_ids(세부 용도)를 쉼표로 잇는다. 둘 다 Hugging Face tasks 어휘다."""
    tasks = _unique(str(t).strip() for key in ("task_categories", "task_ids") for t in _as_list(card.get(key)) if isinstance(t, str) and t.strip())
    return ", ".join(tasks) or None


def _collection_process(card: dict) -> str | None:
    """데이터셋 카드의 annotations_creators(주석을 만든 방식)와 language_creators(내용을 만든 방식). 정해진 어휘다
    (crowdsourced, expert-generated, machine-generated, found, no-annotation …)."""
    parts = []
    for key, label in (("annotations_creators", "annotations"), ("language_creators", "language")):
        values = _unique(str(v).strip() for v in _as_list(card.get(key)) if isinstance(v, str) and v.strip())
        if values:
            parts.append(f"{label} {', '.join(values)}")
    return "; ".join(parts) or None


def _source_datasets(card: dict) -> list[str]:
    """source_datasets 가운데 상위 데이터셋 id. 'original' 과 'extended' 는 id 가 아니고, 'extended|<id>' 는 id 만 남긴다."""
    out = []
    for s in _as_list(card.get("source_datasets")):
        if not isinstance(s, str):
            continue
        s = s.strip()
        if s.lower().startswith("extended|"):
            s = s.split("|", 1)[1].strip()
        if s and s.lower() not in ("original", "extended") and _HF_ID.match(s):
            out.append(s)
    return out


def _modality_of_task(task: str) -> str:
    task = task.strip().lower()
    for prefix, modality in MODALITY_BY_TASK:
        if task.startswith(prefix):
            return modality
    return "other"


def _hub_statistics(entries: list[tuple[str, str, dict]]) -> list[tuple[str, str]]:
    """(config, split, /statistics 응답) → (종류, 값). 종류는 "<split>:<열>:<통계>", config 가 둘 이상이면 "<config>:" 를 앞에 더한다."""
    configs = {c for c, _, _ in entries}
    out: list[tuple[str, str]] = []
    for config, split, resp in entries:
        prefix = f"{config}:{split}" if len(configs) > 1 else split
        for col in resp.get("statistics") or []:
            if not isinstance(col, dict):
                continue
            name, ctype, cs = col.get("column_name"), col.get("column_type"), col.get("column_statistics")
            if not name or not isinstance(cs, dict):
                continue
            out += [(f"{prefix}:{name}:{kind}", value) for kind, value in _column_statistics(ctype, cs)]
    return out


def _column_statistics(column_type, cs: dict) -> list[tuple[str, str]]:
    """datasets-server 열 하나 → 통계. 맨 앞은 nan_count(서버가 센 null 값 개수). 숫자 열은 min·max·mean·median·std,
    글·목록·이미지·오디오 열은 길이·너비·길이(초)의 그 통계(종류 앞에 length·width·duration 을 붙인다), 라벨 열은 n_unique·mode·frequencies."""
    out: list[tuple[str, str]] = []
    nan_count = cs.get("nan_count")
    if isinstance(nan_count, int) and not isinstance(nan_count, bool):
        out.append(("nan_count", _number(nan_count)))
    if column_type in LABEL_COLUMN_TYPES:
        return out + _label_statistics(cs.get("n_unique"), cs.get("frequencies"))
    measure = MEASURE_BY_COLUMN_TYPE.get(column_type)
    for key in STATISTIC_KEYS:
        v = cs.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((f"{measure}:{key}" if measure else key, _number(v)))
    return out


# ── 사실 ↔ 내부 프로퍼티 ─────────────────────────────────────────────────────

def internal_properties(facts: dict) -> list[dict]:
    """사실 dict → aibom-internal:dataset:* 프로퍼티. 키 모양은 정의서의 aibom:dataset:* 와 같다 (접두어만 다르다)."""
    props: list[dict] = []
    if facts.get("size") is not None:
        props.append({"name": INTERNAL_PREFIX + "size", "value": str(facts["size"])})
    for i, m in enumerate(facts.get("modality") or []):
        props.append({"name": f"{INTERNAL_PREFIX}modality:{i}", "value": m})
    if facts.get("availability"):
        props.append({"name": INTERNAL_PREFIX + "availability", "value": facts["availability"]})
    for field in ("intendedUse", "collectionProcess"):
        if facts.get(field):
            props.append({"name": INTERNAL_PREFIX + field, "value": facts[field]})
    for i, p in enumerate(facts.get("provenance") or []):
        props.append({"name": f"{INTERNAL_PREFIX}provenance:{i}", "value": p})
    for i, (kind, value) in enumerate(facts.get("statistics") or []):
        props += [{"name": f"{INTERNAL_PREFIX}statistics:{i}:type", "value": kind},
                  {"name": f"{INTERNAL_PREFIX}statistics:{i}:value", "value": value}]
    return props


# ── 관계 ─────────────────────────────────────────────────────────────────────

def _link_from_root(merged: dict, refs: list[str]) -> None:
    """루트(metadata.component)가 새 데이터셋 컴포넌트에 의존한다. 루트가 없으면 아무것도 하지 않는다."""
    root_ref = ((merged.get("metadata") or {}).get("component") or {}).get("bom-ref")
    if root_ref:
        _depend(merged, root_ref, refs, first=True)


def _depend(merged: dict, ref: str, targets: list[str], first: bool = False) -> None:
    """ref 가 targets 에 의존한다. 행이 없으면 만든다 (루트 행은 맨 앞에, 나머지는 맨 뒤에)."""
    deps: list[dict] = merged.setdefault("dependencies", [])
    row = next((d for d in deps if d.get("ref") == ref), None)
    if row is None:
        row = {"ref": ref, "dependsOn": []}
        deps.insert(0, row) if first else deps.append(row)
    row["dependsOn"] = sorted(set(row.get("dependsOn") or []) | set(targets))


# ── 잡다한 것 ────────────────────────────────────────────────────────────────

def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None
