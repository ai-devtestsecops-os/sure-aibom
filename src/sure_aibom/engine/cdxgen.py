"""cdxgen — 모델·데이터셋 생산자.

-t ai 로 소프트웨어 분기를 끄고 AI 인벤토리만 훑는다.
    cdxgen <target 절대경로> -t ai --spec-version 1.7 --no-install-deps -o <out>

대상은 절대경로로 넘긴다. cdxgen 은 owner/name 모양의 상대 경로(acme/project)를 로컬 폴더가 아니라 허브 id 로 읽어 원격 조회한다.
--include-formulation 은 쓰지 않는다. 모델·데이터셋 컴포넌트에는 영향이 없고, cdxgen 실행 환경
(git 트리 전체, CONDA_PREFIX 같은 환경변수)을 formulation[] 에 실어 스캔 머신 정보가 새기 때문이다.

출력은 다음만 고친다 (cdxgen 값의 정리라 출처는 cdxgen 그대로다).
    purl            공백이 든 이름(GGUF general.name)의 % 를 두 번 인코딩한 것(%2520)을 한 번으로
    pedigree        베이스 모델 항목의 bom-ref 를 뺀다 (그 모델이 스캔 대상에도 있으면 최상위 컴포넌트와 겹친다)
    Modelfile 모델   FROM 이 로컬 경로(ollama 에 GGUF 를 들이는 표준 모양)면 cdxgen 은 그 경로를 허브 id 로 읽어 가짜 pkg:huggingface
                    모델을 만든다. 그 경로의 GGUF 로 cdxgen 이 만든 모델이 있으면 거기에 합치고(Modelfile 위치와 런타임 ollama 를
                    더하고 관계를 옮긴다), 없으면 pkg:generic/<파일 이름> 으로 바꾼다.
                    LICENSE 본문이 따옴표(\"\"\") 다음 줄에서 시작하면 cdxgen 은 라이선스 이름을 \"\"\" 로 적는다 — 본문의 첫 줄로 바꾼다
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from ..utils.exceptions import RunnerError
from .common.component import MODEL_TYPE
from .common.licenses import license_entry
from .common.proc import load_json_file, run

SPEC_VERSION = "1.7"
MODELFILE_FORMAT = "modelfile"
MODELFILE_LIMIT = 1024 ** 2                       # 이보다 큰 Modelfile 은 읽지 않는다
_DOUBLE_ENCODED = re.compile(r"%25(?=[0-9A-Fa-f]{2})")
_DIRECTIVE = re.compile(r"^(FROM|LICENSE)\s+(.*)$", re.IGNORECASE)


def run_cdxgen(target: str, workdir: Path, install_deps: bool = False) -> dict:
    out = workdir / "cdxgen.cdx.json"
    root = Path(target).resolve()
    cmd = [
        "cdxgen",
        str(root),
        "-t", "ai",
        "--spec-version", SPEC_VERSION,
        "-o", str(out),
    ]
    if not install_deps:
        cmd.append("--no-install-deps")
    proc = run(cmd)
    if proc.returncode != 0:
        raise RunnerError(f"cdxgen exited with {proc.returncode}\n{proc.stderr[-2000:]}")
    return _tidy(load_json_file(out, "cdxgen"), root)


def _tidy(doc: dict, root: Path) -> dict:
    """머리 설명의 표대로 제자리에서 고치고 돌려준다. root 는 cdxgen 에 넘긴 디렉터리 (evidence 경로의 기준)."""
    for comp in _walk(doc.get("components") or []):
        _fix_purl(comp)
        _drop_pedigree_refs(comp)
    _modelfile_models(doc, root)
    return doc


def _walk(components):
    for c in components:
        yield c
        yield from _walk(c.get("components") or [])


# ── purl ─────────────────────────────────────────────────────────────────────

def _fix_purl(comp: dict) -> None:
    """namespace·name 조각에서 %25XX 를 %XX 로. 고친 조각을 풀었을 때 컴포넌트의 group·name 과 같을 때만 고친다."""
    purl = comp.get("purl")
    if not isinstance(purl, str) or "%25" not in purl or not purl.startswith("pkg:"):
        return
    head, _, rest = purl.partition("/")
    cut = min((i for i in (rest.find("@"), rest.find("?"), rest.find("#")) if i >= 0), default=len(rest))
    path, tail = rest[:cut], rest[cut:]
    segments = path.split("/")
    expected = [comp.get("group") or "", comp.get("name") or ""]
    fixed = []
    for i, seg in enumerate(segments):
        want = expected[1] if i == len(segments) - 1 else expected[0] if i == len(segments) - 2 else None
        candidate = _DOUBLE_ENCODED.sub("%", seg)
        fixed.append(candidate if candidate != seg and want is not None and unquote(candidate) == want else seg)
    comp["purl"] = f"{head}/{'/'.join(fixed)}{tail}"


def _drop_pedigree_refs(comp: dict) -> None:
    """pedigree 안의 모델(베이스 모델 등)에서 bom-ref 를 뺀다. cdxgen 은 그 purl 을 bom-ref 로 적어, 같은 모델이 스캔 대상에도 있으면
    (로컬 어댑터의 베이스 모델 폴더) 최상위 컴포넌트와 bom-ref 가 겹친다 (CycloneDX 는 bom-ref 가 문서 안에서 하나여야 한다)."""
    for key in ("ancestors", "descendants", "variants"):
        for entry in (comp.get("pedigree") or {}).get(key) or []:
            if isinstance(entry, dict):
                entry.pop("bom-ref", None)


# ── Modelfile 모델 ─────────────────────────────────────────────────────────────

def _modelfile_models(doc: dict, root: Path) -> None:
    for model in [c for c in doc.get("components") or [] if c.get("type") == MODEL_TYPE and _prop(c, "cdx:ai:artifactFormat") == MODELFILE_FORMAT]:
        location = next((o.get("location") for o in (model.get("evidence") or {}).get("occurrences") or []
                         if isinstance(o, dict) and isinstance(o.get("location"), str)), None)
        path = _find_path(root, location) if location else None
        if path is None:
            continue
        try:
            if path.stat().st_size > MODELFILE_LIMIT:
                continue
            source, license_line = _parse_modelfile(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        _fix_quote_license(model, license_line)
        local = _local_source(root, location, source)
        if local is None:
            continue
        target = next((c for c in doc.get("components") or [] if c is not model and c.get("type") == MODEL_TYPE
                       and local in {o.get("location") for o in (c.get("evidence") or {}).get("occurrences") or [] if isinstance(o, dict)}), None)
        if target is None:
            name = PurePosixPath(local).name
            model.pop("group", None)
            model["name"] = name
            model["purl"] = f"pkg:generic/{quote(name, safe='')}"
        else:
            _absorb(doc, target, model)


def _parse_modelfile(text: str) -> tuple[str | None, str | None]:
    """(FROM 값, LICENSE 의 첫 줄). 둘 다 마지막 지시문을 쓴다 (cdxgen 과 같다). \"\"\" 로 감싼 LICENSE 는 그 안의 첫 비지 않은 줄."""
    source = license_line = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _DIRECTIVE.match(lines[i].strip())
        i += 1
        if not m:
            continue
        directive, value = m[1].upper(), m[2].strip()
        if directive == "FROM":
            source = value or source
            continue
        if not value.startswith('"""'):
            license_line = value or license_line
            continue
        block = [value[3:]]
        while '"""' not in block[-1] and i < len(lines):
            block.append(lines[i])
            i += 1
        block[-1] = block[-1].split('"""', 1)[0]
        license_line = next((line.strip() for line in block if line.strip()), license_line)
    return source, license_line


def _fix_quote_license(model: dict, license_line: str | None) -> None:
    licenses = []
    for entry in model.get("licenses") or []:
        name = ((entry or {}).get("license") or {}).get("name")
        if isinstance(name, str) and name.strip() and not name.strip().strip("\"'"):
            if license_line:
                licenses.append(license_entry(license_line))
            continue
        licenses.append(entry)
    if "licenses" in model:
        if licenses:
            model["licenses"] = licenses
        else:
            del model["licenses"]


def _local_source(root: Path, modelfile: str, source: str | None) -> str | None:
    """FROM 이 대상 안의 파일·폴더를 가리키면 그 상대 경로 (evidence 와 같은 모양). 모델 이름(llama3.2:1b)이면 None.
    ./ ../ / ~ 로 시작하지 않아도 Modelfile 옆에 그 이름의 파일이 있으면 경로로 친다 (ollama 와 같다)."""
    if not source:
        return None
    base = PurePosixPath(modelfile.replace("\\", "/")).parent
    if source.startswith("/"):
        rel = PurePosixPath(source.lstrip("/"))
    elif source.startswith("~"):
        return None
    else:
        rel = base / source
    parts: list[str] = []
    for part in rel.parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    if not parts:
        return None
    candidate = "/".join(parts)
    explicit = source.startswith(("./", "../", "/"))
    return candidate if explicit or _find_path(root, candidate) is not None else None


def _absorb(doc: dict, target: dict, model: dict) -> None:
    """Modelfile 모델을 같은 GGUF 의 모델에 합친다: Modelfile 위치와 런타임을 더하고, 비어 있으면 라이선스를 넘기고, 관계를 옮긴다."""
    occurrences = target.setdefault("evidence", {}).setdefault("occurrences", [])
    known = {o.get("location") for o in occurrences}
    for o in (model.get("evidence") or {}).get("occurrences") or []:
        if o.get("location") not in known:
            occurrences.append(o)
            known.add(o.get("location"))
    runtime = _prop(model, "cdx:ai:runtime")
    if runtime and {"name": "cdx:ai:runtime", "value": runtime} not in (target.get("properties") or []):
        target["properties"] = (target.get("properties") or []) + [{"name": "cdx:ai:runtime", "value": runtime}]
    if not target.get("licenses") and model.get("licenses"):
        target["licenses"] = model["licenses"]
    doc["components"] = [c for c in doc["components"] if c is not model]
    _repoint(doc, model.get("bom-ref"), target.get("bom-ref"))


def _prop(comp: dict, name: str) -> str | None:
    return next((p.get("value") for p in comp.get("properties") or [] if isinstance(p, dict) and p.get("name") == name), None)


def _repoint(doc: dict, old: str | None, new: str | None) -> None:
    if not old or not new or old == new:
        return
    rows: dict[str, dict] = {}
    for row in doc.get("dependencies") or []:
        ref = new if row.get("ref") == old else row.get("ref")
        targets = sorted({new if t == old else t for t in row.get("dependsOn") or []} - {ref})
        if ref in rows:
            rows[ref]["dependsOn"] = sorted(set(rows[ref]["dependsOn"]) | set(targets))
        else:
            rows[ref] = {**row, "ref": ref, "dependsOn": targets}
    if "dependencies" in doc:
        doc["dependencies"] = list(rows.values())


def _find_path(root: Path, location: str) -> Path | None:
    """root 기준 상대 경로 location 의 실제 파일. root 밖(심볼릭 링크 포함)이거나 없으면 None."""
    try:
        path = (root / location.split("#", 1)[0]).resolve()
        return path if path.is_relative_to(root.resolve()) and path.exists() else None
    except (OSError, ValueError):
        return None
