"""스캔 대상 안의 데이터셋을 찾아 type=data 컴포넌트로 만든다 (D-BOM). 병합 뒤, 보강·규제 정규화 앞에서 돈다.

출처 두 가지:
    1) Hugging Face 데이터셋 참조
       - cdxgen 이 모델 README 에서 만든 type=data 컴포넌트 (purl 또는 data[0].name "datasets/<id>" 에서 id 를 얻는다)
       - 파이썬 소스의 load_dataset("owner/name") — 첫 위치 인자가 허브 id 모양일 때만.
         load_dataset("csv", data_files=…) 같은 로컬 빌더는 data_files 경로를 출처 2 로 보낸다.
       네트워크가 닿으면 GET {HF_ENDPOINT}/api/datasets/<id> 로 채우고, 닿지 않으면 이름·purl 만 두고 한 번 알린다.
       datasets-server 의 /size(README 앞머리에 크기가 없을 때의 바이트 크기)와 /statistics(config·split 별 열 통계)도 본다.
       컴포넌트가 없으면 만들고(bom-ref = purl pkg:huggingface/datasets/<id>), 있으면 제자리에서 채운다.
       허브가 돌려준 id 가 정식 id 다: 옛 이름(imdb → stanfordnlp/imdb)이나 두 이름(bookcorpus, bookcorpus/bookcorpus)으로 부른
       같은 데이터셋은 정식 id 의 컴포넌트 하나로 모으고 (purl·bom-ref 를 바꾸고, 가리키던 관계·modelCard ref 도 따라간다) 한 번만 조회한다.
    2) 로컬 데이터 파일 — 확장자로 찾고 부모 디렉터리마다 컴포넌트 하나 (bom-ref "data:local/<상대 디렉터리>@"),
       data[] 에 파일마다 componentData 하나 {type: dataset, name: <상대 경로>, contents.properties: 크기·sha256·형식·행·열}.
       코드가 가리키는 경로(pd.read_csv, open, np.load, data_files=)도 데이터 확장자이고 대상 안에 실제로 있으면 넣는다
       (역슬래시 구분자는 / 로 읽고, .. 은 정리해 한 파일이 두 번 들어가지 않게 한다). 대상 밖으로 나가는 심볼릭 링크는 건너뛴다.
       json·txt 는 어디에나 있는 확장자라, 코드가 가리키거나 같은 디렉터리에 다른 데이터 파일이 있을 때만 데이터로 치고,
       requirements*.txt · README* · package.json · *config.json 같은 잘 알려진 비데이터 이름은 코드가 가리킬 때만 친다.
       분석은 표준 라이브러리만 쓴다 (parquet·arrow·feather 는 pyarrow 가 있을 때만). pickle 은 절대 읽지 않는다.
       열 통계(숫자 열은 min·max·mean·median·std, 글 열은 길이의 그 통계, 라벨 열은 n_unique·mode·frequencies)는
       csv·tsv·jsonl·json·parquet·arrow 에서 64 MB 까지만 낸다. 허브 datasets-server 가 주는 것과 같은 종류다.

데이터셋 사실(size, modality, availability, provenance, statistics)은 aibom-internal:dataset:* 프로퍼티로 컴포넌트에 두고,
regulation 이 --form 에 맞는 자리로 옮기며 지운다 — 출력에는 남지 않는다.

관계: 로컬 데이터셋과 코드에서 찾은 HF 데이터셋은 metadata.component(루트)가 dependsOn 한다. README 에서 온 것은
cdxgen 이 준 모델 → 데이터셋 엣지를 그대로 둔다.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import os
import re
import zipfile
from collections import Counter
from io import BufferedIOBase
from statistics import fmean, median, stdev
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .enrich import hf_reachable
from .merge import fill_missing
from .regulation import INTERNAL_PREFIX
from .validate import SCHEMA_DIR

DATA_TYPE = "data"
FILE_PREFIX = "aibom-cli:file:"                 # componentData.contents.properties 의 파일 사실
LOCAL_REF_PREFIX = "data:local/"

HF_DATASETS_PURL = "pkg:huggingface/datasets/"
_HF_DATASET_PURL = re.compile(r"^pkg:huggingface/datasets/(?P<id>[^@?#]+)")
_HF_ID = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?$")

SKIP_DIRS = frozenset({"node_modules", ".git", "venv", ".venv", "site-packages", "__pycache__"})

# 확장자 → 모달리티. 강한 확장자는 어디 있든 데이터, 약한 확장자(json, txt)는 근거가 더 있어야 데이터.
MODALITY_BY_EXTENSION: dict[str, str] = {
    "csv": "structured", "tsv": "structured", "parquet": "structured", "arrow": "structured", "feather": "structured",
    "npy": "structured", "npz": "structured",
    "jsonl": "text", "ndjson": "text", "json": "text", "txt": "text",
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image",
    "wav": "audio", "mp3": "audio", "flac": "audio",
}
WEAK_EXTENSIONS = frozenset({"json", "txt"})
DATA_EXTENSIONS = frozenset(MODALITY_BY_EXTENSION)
# 약한 확장자인데 이름만 봐도 데이터가 아닌 것 — 이웃에 데이터 파일이 있어도 승격하지 않는다 (코드가 직접 읽으면 데이터다)
_NON_DATA_NAME = re.compile(r"^(requirements[\w.-]*\.txt|readme.*|license.*|notice.*|changelog.*|package(-lock)?\.json"
                            r"|tsconfig\.json|.*config\.json|manifest\.json|composer\.json)$", re.IGNORECASE)
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")

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

# load_dataset 의 첫 인자가 이것이면 허브 id 가 아니라 로컬 빌더다 — data_files 가 데이터다
LOCAL_BUILDERS = frozenset({"csv", "json", "jsonl", "parquet", "text", "arrow", "pandas", "imagefolder", "audiofolder",
                            "videofolder", "webdataset", "xml", "sql", "generator", "spark", "polars"})
PANDAS_READERS = frozenset({"read_csv", "read_table", "read_json", "read_parquet", "read_feather", "read_fwf"})

HASH_LIMIT = 2 * 1024 ** 3                      # 이보다 큰 파일은 크기만 적는다
JSON_PARSE_LIMIT = 64 * 1024 ** 2               # json 배열 길이를 세려고 통째로 읽는 상한
CSV_FIELD_LIMIT = 2 ** 31 - 1                   # csv 모듈 기본값 131072 는 문서 하나가 한 칸인 NLP 표에 모자란다
NPY_HEADER_LIMIT = 1024 ** 2                    # 이보다 긴 npy 헤더는 믿지 않는다
# 파일 하나를 읽다 나는 예외 — 크기·해시만 적고 계속 간다
_READ_ERRORS = (OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile, csv.Error, SyntaxError, TypeError, AttributeError)
FETCH_TIMEOUT = 15.0

DATASETS_SERVER = "https://datasets-server.huggingface.co"
STATISTIC_KEYS = ("min", "max", "mean", "median", "std")      # datasets-server 가 숫자형 열에 주는 통계. v0.6 의 예시(mean, median, range …)와 같은 계열
MEASURE_BY_COLUMN_TYPE = {"string_text": "length", "list": "length", "image": "width", "audio": "duration"}   # 숫자가 아닌 열은 무엇의 통계인지
LABEL_COLUMN_TYPES = frozenset({"class_label", "string_label", "bool"})
FREQUENCIES_LIMIT = 10                                        # 범주가 이보다 많으면 frequencies·mode 는 적지 않는다 (n_unique 만)
STATISTICS_REQUEST_LIMIT = 12                                 # 데이터셋 하나에 config×split 통계 조회 상한
STATISTICS_FILE_LIMIT = JSON_PARSE_LIMIT                      # 로컬 파일 열 통계는 이 크기까지만 (값을 메모리에 올린다)


# ── 진입점 ──────────────────────────────────────────────────────────────────

def discover(merged: dict, target: str, log=print) -> dict:
    """병합 문서에 데이터셋 컴포넌트를 더한다. 찾은 것이 없으면 문서는 바이트 단위로 그대로다."""
    components: list[dict] = merged.setdefault("components", [])
    by_hf_id: dict[str, dict] = {}
    for comp in components:
        hf_id = hf_dataset_id_of(comp)
        if hf_id and hf_id not in by_hf_id:
            by_hf_id[hf_id] = comp

    root = Path(target)
    code_hf_ids: dict[str, list[str]] = {}         # id → 그것을 부른 소스 파일 (상대 경로)
    local_files: set[Path] = set()
    if root.is_dir():
        code_hf_ids, local_files = _scan_directory(root, log)

    new_refs: list[str] = []
    for hf_id in sorted(code_hf_ids):
        comp = by_hf_id.get(hf_id)
        if comp is None:
            comp = _new_hf_component(hf_id)
            components.append(comp)
            by_hf_id[hf_id] = comp
            new_refs.append(comp["bom-ref"])
        occurrences = comp.setdefault("evidence", {}).setdefault("occurrences", [])
        known = {o.get("location") for o in occurrences}
        occurrences.extend({"location": loc} for loc in code_hf_ids[hf_id] if loc not in known)

    for comp in _local_components(root, local_files, log):
        components.append(comp)
        new_refs.append(comp["bom-ref"])

    if new_refs:
        _link_from_root(merged, new_refs)
    if by_hf_id:
        _fill_from_hub(merged, by_hf_id, log)
    return merged


# ── HF id 읽기 ───────────────────────────────────────────────────────────────

def hf_dataset_id_of(comp: dict) -> str | None:
    """type=data 컴포넌트의 Hugging Face 데이터셋 id. purl → data[].name "datasets/<id>" → group "datasets" 의 name."""
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

def _scan_directory(root: Path, log) -> tuple[dict[str, list[str]], set[Path]]:
    """대상 디렉터리를 한 번 걷는다. 파이썬 소스에서 HF id 와 코드가 가리키는 로컬 경로를, 확장자로 데이터 파일을 찾는다."""
    hf_ids: dict[str, list[str]] = {}
    referenced: set[Path] = set()
    by_dir: dict[Path, list[Path]] = {}
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        here = Path(dirpath)
        for filename in sorted(filenames):
            path = here / filename
            if not _inside(path, root_resolved):
                log(f"[dataset] {_relative(path, root)}: 대상 밖을 가리키는 링크라 건너뛴다")
                continue
            if filename.endswith(".py"):
                ids, paths = _parse_python(path, log)
                loc = _relative(path, root)
                for hf_id in ids:
                    hf_ids.setdefault(hf_id, []).append(loc)
                referenced.update(_resolve_paths(paths, path.parent, root))
            elif _extension(filename) in DATA_EXTENSIONS and path.is_file():
                by_dir.setdefault(here, []).append(path)

    files: set[Path] = set(referenced)
    for paths in by_dir.values():
        strong = any(_is_strong(p) for p in paths)
        files.update(p for p in paths if _is_strong(p) or (strong and not _NON_DATA_NAME.match(p.name)))
    return hf_ids, files


def _is_strong(path: Path) -> bool:
    return _extension(path.name) not in WEAK_EXTENSIONS


def _inside(path: Path, root_resolved: Path) -> bool:
    """심볼릭 링크를 따라간 실제 위치가 대상 안인가."""
    try:
        return path.resolve().is_relative_to(root_resolved)
    except OSError:
        return False


def _parse_python(path: Path, log) -> tuple[list[str], list[str]]:
    """소스 하나에서 (HF 데이터셋 id 들, 코드가 읽는 로컬 경로 문자열들). 파싱이 안 되면 건너뛰고 알린다."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError) as e:
        log(f"[dataset] {path.name}: 파싱하지 못해 건너뛴다 ({e.__class__.__name__})")
        return [], []
    ids: list[str] = []
    paths: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = _callee(node.func)
        first = _string(node.args[0]) if node.args else None
        if func == "load_dataset":
            for kw in node.keywords:
                if kw.arg == "data_files":
                    paths += [s] if (s := _string(kw.value)) else _strings(kw.value)
            if first and first.lower() not in LOCAL_BUILDERS:
                if _looks_like_hub_id(first):
                    if first not in ids:
                        ids.append(first)
                else:
                    paths.append(first)                              # 스크립트·파일 경로는 출처 2 로
        elif func in PANDAS_READERS or func == ("np", "load") or func == ("numpy", "load"):
            if first:
                paths.append(first)
        elif func == "open" and first:
            paths.append(first)
    return ids, [p for p in paths if _keep_code_path(p, path.name, log)]


def _keep_code_path(text: str, source: str, log) -> bool:
    """코드가 읽는 경로 중 데이터 확장자인 것만 남긴다. 나머지(.dat, .bin, .xlsx, 확장자 없음)는 알리고 버린다."""
    if _extension(_last_segment(text)) in DATA_EXTENSIONS:
        return True
    log(f"[dataset] {source}: {text!r} 은 아는 데이터 형식이 아니라 건너뛴다")
    return False


def _last_segment(text: str) -> str:
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _callee(func: ast.expr):
    """호출 대상 이름. pd.read_csv → "read_csv", np.load → ("np", "load"), open → "open"."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        if func.attr == "load" and isinstance(func.value, ast.Name):
            return (func.value.id, "load")
        return func.attr
    return None


def _string(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _strings(node: ast.expr | None) -> list[str]:
    """data_files 의 목록·사전 값 안의 문자열들."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return [s for e in node.elts if (s := _string(e))]
    if isinstance(node, ast.Dict):
        out: list[str] = []
        for v in node.values:
            out += [s] if (s := _string(v)) else _strings(v)
        return out
    return []


def _looks_like_hub_id(text: str) -> bool:
    """"owner/name" 또는 확장자 없는 맨 이름. 경로(./, ../, \\)와 마지막 조각에 확장자가 붙은 것(script.py, x.xlsx)은 아니다.
    허브 id 에도 점은 올 수 있어(v0.1, Qwen2.5-Math) 숫자만이거나 영숫자가 아닌 글자가 섞인 꼬리는 확장자로 보지 않는다."""
    if not _HF_ID.match(text) or text.startswith("."):
        return False
    ext = _extension(_last_segment(text))
    return not (ext.isalnum() and not ext.isdigit())


def _resolve_paths(raw: Iterable[str], source_dir: Path, root: Path) -> set[Path]:
    """코드의 경로 문자열 → 대상 안에 실제로 있는 파일. 대상 루트 기준, 다음에 소스 파일 기준으로 본다. 밖을 가리키면 버린다.
    역슬래시는 / 로 읽고, 찾은 경로는 .. 을 정리한 루트 기준 경로로 둔다 (걷기로 찾은 같은 파일과 하나로 모이게)."""
    found: set[Path] = set()
    root_resolved = root.resolve()
    for text in raw:
        text = text.replace("\\", "/")
        if not text or "://" in text or "*" in text or text.startswith("/") or _DRIVE_PATH.match(text):
            continue
        for base in (root, source_dir):
            candidate = base / text
            if candidate.is_file() and _inside(candidate, root_resolved):
                found.add(root / candidate.resolve().relative_to(root_resolved))
                break
    return found


# ── 로컬 파일 → 컴포넌트 ─────────────────────────────────────────────────────

def _local_components(root: Path, files: set[Path], log) -> list[dict]:
    """부모 디렉터리마다 컴포넌트 하나. 디렉터리·파일 순서는 상대 경로 정렬로 결정적이다."""
    by_dir: dict[str, list[Path]] = {}
    for path in files:
        by_dir.setdefault(_relative(path.parent, root), []).append(path)
    out: list[dict] = []
    for rel_dir in sorted(by_dir):
        analyses = [_analyze_file(p, _relative(p, root), log) for p in sorted(by_dir[rel_dir], key=lambda p: _relative(p, root))]
        out.append(_local_component(root, rel_dir, analyses))
    return out


def _local_component(root: Path, rel_dir: str, analyses: list[dict]) -> dict:
    name = PurePosixPath(rel_dir).name if rel_dir != "." else (root.resolve().name or ".")
    comp: dict = {"type": DATA_TYPE, "name": name, "bom-ref": f"{LOCAL_REF_PREFIX}{rel_dir}@"}
    comp["data"] = [_component_data(a) for a in analyses]
    facts = {
        "size": sum(a["size"] for a in analyses),
        "modality": _unique(a["modality"] for a in analyses),
        "availability": "direct-download",
        "provenance": [rel_dir],
        "statistics": _local_statistics(analyses),
    }
    comp["properties"] = internal_properties(facts)
    return comp


def _component_data(a: dict) -> dict:
    props = [{"name": FILE_PREFIX + "size", "value": str(a["size"])}, {"name": FILE_PREFIX + "format", "value": a["format"]}]
    if a.get("sha256"):
        props.append({"name": FILE_PREFIX + "sha256", "value": a["sha256"]})
    if a.get("rows") is not None:
        props.append({"name": FILE_PREFIX + "rows", "value": str(a["rows"])})
    if a.get("columns"):
        props.append({"name": FILE_PREFIX + "columns", "value": ",".join(a["columns"])})
    return {"type": "dataset", "name": a["path"], "contents": {"properties": props}}


def _local_statistics(analyses: list[dict]) -> list[tuple[str, str]]:
    """파일별 열 통계를 모은다. 파일이 둘 이상이면 파일 이름(확장자 뺀)을 앞에 붙여 허브의 split 자리처럼 쓴다."""
    many = len(analyses) > 1
    out: list[tuple[str, str]] = []
    for a in analyses:
        stem = PurePosixPath(a["path"]).stem
        out += [(f"{stem}:{kind}" if many else kind, value) for kind, value in a.get("statistics") or []]
    return out


def _analyze_file(path: Path, rel: str, log) -> dict:
    """표준 라이브러리로 읽는 파일 사실. 2 GB 를 넘으면 크기만."""
    ext = _extension(path.name)
    out: dict = {"path": rel, "size": path.stat().st_size, "format": ext, "modality": MODALITY_BY_EXTENSION.get(ext, "other")}
    if out["size"] > HASH_LIMIT:
        log(f"[dataset] {rel}: 2 GB 를 넘어 크기만 적는다")
        return out
    try:
        out["sha256"] = _sha256(path)
    except OSError as e:
        log(f"[dataset] {rel}: 읽을 수 없어 크기만 적는다 ({e.__class__.__name__})")
        return out
    try:
        out.update(_shape(path, ext))
        if out["size"] <= STATISTICS_FILE_LIMIT:
            out["statistics"] = _file_statistics(path, ext)
    except _READ_ERRORS as e:
        log(f"[dataset] {rel}: 내용을 읽지 못해 크기·해시만 적는다 ({e.__class__.__name__})")
    return out


def _shape(path: Path, ext: str) -> dict:
    """형식별 행·열. 모르는 형식은 빈 dict."""
    if ext in ("csv", "tsv"):
        return _csv_shape(path, "\t" if ext == "tsv" else ",")
    if ext in ("jsonl", "ndjson", "txt"):
        with path.open(encoding="utf-8", errors="replace") as fh:
            return {"rows": sum(1 for line in fh if line.strip())}
    if ext == "json":
        if path.stat().st_size > JSON_PARSE_LIMIT:
            return {}
        with path.open(encoding="utf-8", errors="replace") as fh:
            parsed = json.load(fh)
        return {"rows": len(parsed)} if isinstance(parsed, list) else {}
    if ext == "npy":
        with path.open("rb") as fh:
            return _npy_shape(fh)
    if ext == "npz":
        return _npz_shape(path)
    if ext == "parquet":
        return _parquet_shape(path)
    if ext in ("arrow", "feather"):
        return _arrow_shape(path)
    return {}


def _csv_shape(path: Path, delimiter: str) -> dict:
    csv.field_size_limit(max(csv.field_size_limit(), CSV_FIELD_LIMIT))
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            return {"rows": 0}
        return {"rows": sum(1 for row in reader if row), "columns": [h.strip() for h in header]}


def _npy_shape(fh: BufferedIOBase) -> dict:
    """npy 헤더 (형식 문서 그대로): magic, 버전, 헤더 길이, 파이썬 dict 리터럴. 첫 축이 행이다.
    길이 필드만큼 정확히 읽는다 (구조체 dtype 헤더는 512 바이트를 쉽게 넘는다). 헤더가 이상하면 빈 dict."""
    head = fh.read(12)
    if not head.startswith(b"\x93NUMPY") or len(head) < 10:
        return {}
    if head[6] == 1:
        length, tail = int.from_bytes(head[8:10], "little"), head[10:12]
    else:
        length, tail = int.from_bytes(head[8:12], "little"), b""
    if length > NPY_HEADER_LIMIT:
        return {}
    text = (tail + fh.read(length - len(tail))).decode("latin-1").strip()
    try:
        header = ast.literal_eval(text)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return {}
    if not isinstance(header, dict):
        return {}
    shape = header.get("shape")
    return {"rows": int(shape[0])} if isinstance(shape, tuple) and shape else {}


def _npz_shape(path: Path) -> dict:
    """npz 는 npy 들의 zip — 배열이 하나일 때만 그 행 수."""
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.namelist() if m.endswith(".npy")]
        if len(members) != 1:
            return {}
        with zf.open(members[0]) as fh:
            return _npy_shape(fh)


def _parquet_shape(path: Path) -> dict:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return {}
    meta = pq.ParquetFile(str(path))
    return {"rows": meta.metadata.num_rows, "columns": list(meta.schema_arrow.names)}


def _arrow_shape(path: Path) -> dict:
    try:
        import pyarrow as pa
        import pyarrow.feather as feather
    except ImportError:
        return {}
    try:
        with pa.memory_map(str(path)) as source:
            reader = pa.ipc.open_file(source)
            rows = sum(reader.get_batch(i).num_rows for i in range(reader.num_record_batches))
            return {"rows": rows, "columns": list(reader.schema.names)}
    except pa.ArrowInvalid:                                       # feather v1 은 IPC 파일이 아니다
        table = feather.read_table(str(path), memory_map=True)
        return {"rows": table.num_rows, "columns": list(table.schema.names)}


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
    """열 값들 → 통계. 전부 숫자면 min·max·mean·median·std, 전부 bool 이거나 범주가 적고 반복되면 n_unique·mode·frequencies,
    그 밖의 글은 길이의 통계. datasets-server 가 열 종류별로 주는 것과 같은 규칙이다."""
    present = [v for v in values if v is not None and v != ""]
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Hugging Face 허브 ────────────────────────────────────────────────────────

def hf_endpoint() -> str:
    return (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")


def datasets_server() -> str:
    return (os.environ.get("HF_DATASETS_SERVER") or DATASETS_SERVER).rstrip("/")


def _get_json(url: str, hf_id: str, what: str, log) -> dict | None:
    req = Request(url, headers={"User-Agent": "aibom-cli", "Accept": "application/json"})
    if os.environ.get("HF_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['HF_TOKEN']}")
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            info = json.load(resp)
    except HTTPError as e:
        log(f"[dataset] {hf_id}: {what} 응답 {e.code}")
        return None
    except (URLError, OSError, ValueError) as e:
        log(f"[dataset] {hf_id}: {what} 조회 실패 ({e.__class__.__name__})")
        return None
    return info if isinstance(info, dict) else None


def fetch_dataset_info(hf_id: str, log=print) -> dict | None:
    """GET {HF_ENDPOINT}/api/datasets/<id>. 실패하면 None 을 돌려주고 알린다. 테스트는 이 함수를 바꿔 끼운다."""
    return _get_json(f"{hf_endpoint()}/api/datasets/{quote(hf_id, safe='/')}", hf_id, "허브", log)


def fetch_dataset_size(hf_id: str, log=print) -> dict | None:
    """GET datasets-server /size?dataset=<id>. 바이트 크기와 config·split 목록."""
    return _get_json(f"{datasets_server()}/size?dataset={quote(hf_id, safe='/')}", hf_id, "datasets-server /size", log)


def fetch_dataset_statistics(hf_id: str, config: str, split: str, log=print) -> dict | None:
    """GET datasets-server /statistics?dataset=<id>&config=&split=. 열마다 통계."""
    url = f"{datasets_server()}/statistics?dataset={quote(hf_id, safe='/')}&config={quote(config, safe='')}&split={quote(split, safe='')}"
    return _get_json(url, hf_id, f"datasets-server /statistics {config}/{split}", log)


def _fill_from_hub(merged: dict, by_hf_id: dict[str, dict], log) -> None:
    """허브 응답으로 채우고, 같은 데이터셋을 다른 id 로 부른 컴포넌트는 정식 id 의 컴포넌트 하나로 모은다."""
    if not hf_reachable():
        log(f"[dataset] huggingface.co 에 닿지 않음, 데이터셋 {len(by_hf_id)}개는 이름·purl 만 둔다")
        return
    info_by_canonical: dict[str, dict] = {}
    members: dict[str, list[str]] = {}             # 정식 id → 그것을 부른 id 들 (정렬 순서)
    for hf_id in sorted(by_hf_id):
        info = info_by_canonical.get(hf_id) or fetch_dataset_info(hf_id, log)   # 앞선 조회가 정식 id 로 알려 준 것은 다시 묻지 않는다
        canonical = canonical_id(hf_id, info)
        if info:
            info_by_canonical.setdefault(canonical, info)
        members.setdefault(canonical, []).append(hf_id)

    for canonical, ids in members.items():
        survivor_id = canonical if canonical in ids else ids[0]
        comp = by_hf_id[survivor_id]
        for other in ids:
            if other != survivor_id:
                _absorb(merged, comp, by_hf_id[other])
                log(f"[dataset] {other} 은 {canonical} 과 같은 데이터셋, 하나로 합쳤다")
        if survivor_id != canonical:
            _rename(merged, comp, survivor_id, canonical)
            log(f"[dataset] {survivor_id} → {canonical} (허브 정식 id)")
        info = info_by_canonical.get(canonical)
        if info:
            size = fetch_dataset_size(canonical, log)
            statistics = _fetch_statistics(canonical, info, size, log)
            apply_hub_info(comp, canonical, info, size, statistics)
            log(f"[dataset] {canonical}: 허브 정보로 채웠다")


def _fetch_statistics(hf_id: str, info: dict, size: dict | None, log) -> list[tuple[str, str, dict]]:
    """(config, split) 마다 datasets-server 통계를 받는다. 상한을 넘으면 앞쪽만 받고 알린다."""
    pairs = _config_splits(info, size)
    if len(pairs) > STATISTICS_REQUEST_LIMIT:
        log(f"[dataset] {hf_id}: config·split {len(pairs)}개 중 앞 {STATISTICS_REQUEST_LIMIT}개만 통계를 조회한다")
        pairs = pairs[:STATISTICS_REQUEST_LIMIT]
    out: list[tuple[str, str, dict]] = []
    for config, split in pairs:
        resp = fetch_dataset_statistics(hf_id, config, split, log)
        if resp and isinstance(resp.get("statistics"), list):
            if resp.get("partial"):
                log(f"[dataset] {hf_id}: {config}/{split} 통계는 일부 데이터 기준이다 (partial)")
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


def _absorb(merged: dict, survivor: dict, loser: dict) -> None:
    """loser 를 survivor 에 합치고 문서에서 뺀다. survivor 에 없는 값만 채우고 properties·externalReferences·evidence.occurrences 는 합친다."""
    occurrences = (loser.get("evidence") or {}).get("occurrences") or []
    fill_missing(survivor, {k: v for k, v in loser.items() if k not in ("bom-ref", "purl", "evidence")})
    if occurrences:
        target = survivor.setdefault("evidence", {}).setdefault("occurrences", [])
        known = {o.get("location") for o in target}
        target.extend(o for o in occurrences if o.get("location") not in known)
        target.sort(key=lambda o: o.get("location") or "")
    merged["components"] = [c for c in merged["components"] if c is not loser]
    _repoint(merged, loser["bom-ref"], survivor["bom-ref"])


def _rename(merged: dict, comp: dict, old_id: str, new_id: str) -> None:
    """컴포넌트의 id 를 정식 id 로. purl·bom-ref 는 pkg:huggingface/datasets/<id>, group/name 은 owner/name,
    data[].name 과 contents.url 에 든 옛 id 도 바꾼다. 다른 컴포넌트·관계가 가리키던 bom-ref 는 따라간다."""
    old_ref = comp["bom-ref"]
    group, _, name = new_id.rpartition("/")
    if group:
        comp["group"] = group
    else:
        comp.pop("group", None)
    comp["name"] = name
    comp["bom-ref"] = comp["purl"] = HF_DATASETS_PURL + new_id
    for d in comp.get("data") or []:
        if d.get("name") in (old_id, f"datasets/{old_id}"):
            d["name"] = d["name"][: -len(old_id)] + new_id
        url = (d.get("contents") or {}).get("url")
        if isinstance(url, str) and "/datasets/" in url:
            d["contents"]["url"] = _hub_url(new_id)
    _repoint(merged, old_ref, comp["bom-ref"])


def _repoint(merged: dict, old: str, new: str) -> None:
    """bom-ref old 를 가리키던 곳(dependencies[] 의 ref·dependsOn, modelCard.modelParameters.datasets[].ref)을 new 로 돌린다.
    그 결과 같은 ref 가 된 관계 행과 modelCard 항목은 하나로 합친다."""
    if old == new:
        return
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
        licenses = [_license(v) for v in _as_list(card.get("license")) if isinstance(v, str) and v.strip()]
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
        "provenance": [_hub_url(hf_id)],
        "statistics": _hub_statistics(statistics),
    }
    return facts


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
    """datasets-server 열 하나 → 통계. 숫자 열은 min·max·mean·median·std, 글·목록·이미지·오디오 열은 길이·너비·길이(초)의 그 통계
    (종류 앞에 length·width·duration 을 붙인다), 라벨 열은 n_unique·mode·frequencies."""
    if column_type in LABEL_COLUMN_TYPES:
        return _label_statistics(cs.get("n_unique"), cs.get("frequencies"))
    measure = MEASURE_BY_COLUMN_TYPE.get(column_type)
    out: list[tuple[str, str]] = []
    for key in STATISTIC_KEYS:
        v = cs.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((f"{measure}:{key}" if measure else key, _number(v)))
    return out


def _license(value: str) -> dict:
    """SPDX id 이면 licenses[].license.id (스키마의 표기로), 아니면 .name."""
    canonical = _spdx_ids().get(value.strip().lower())
    return {"license": {"id": canonical}} if canonical else {"license": {"name": value.strip()}}


_SPDX_IDS: dict[str, str] | None = None


def _spdx_ids() -> dict[str, str]:
    global _SPDX_IDS
    if _SPDX_IDS is None:
        with (SCHEMA_DIR / "spdx.schema.json").open(encoding="utf-8") as fh:
            _SPDX_IDS = {i.lower(): i for i in json.load(fh).get("enum") or []}
    return _SPDX_IDS


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
    if not root_ref:
        return
    deps: list[dict] = merged.setdefault("dependencies", [])
    row = next((d for d in deps if d.get("ref") == root_ref), None)
    if row is None:
        row = {"ref": root_ref, "dependsOn": []}
        deps.insert(0, row)
    row["dependsOn"] = sorted(set(row.get("dependsOn") or []) | set(refs))


# ── 잡다한 것 ────────────────────────────────────────────────────────────────

def _relative(path: Path, root: Path) -> str:
    """대상 루트 기준 상대 경로. 링크를 따라가지 않으므로 대상 안의 이름이 그대로 나오고, 머신 경로는 나오지 않는다."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path.resolve().relative_to(root.resolve())
    return rel.as_posix() or "."


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
