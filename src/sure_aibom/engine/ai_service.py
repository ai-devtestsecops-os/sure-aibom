"""코드가 부르는 AI 서비스(services[])를 정한다. 병합 뒤, 로컬 모델 읽기 앞에서 돈다.

cdxgen 은 서비스를 네 가지에서 만든다 (aiCollector.js): 제공사 SDK import, 모델 이름에서 짐작한 제공사(gpt → openai,
llama → meta …), 코드가 부르는 허브 모델의 조직(<조직>-service), Modelfile(ollama-service). 서비스는 코드가 네트워크로 부르는
API 라서 근거는 SDK import 하나로 본다. 나머지는 짐작이라 틀린다: vLLM 으로 로컬에서 돌리는 Mistral 모델에도 Mistral API 가
생기고, from_pretrained 로 내려받아 돌리는 모델에도 그 조직의 서비스가 생긴다.

import 는 sure-aibom 이 직접 읽는다. cdxgen 은 파이썬의 `import X` 줄을 다음 줄까지 이어 읽어 이름을 놓치고(`from X import` 는
읽는다), `from X.sub import` 처럼 하위 모듈에서 가져오면 알아보지 못하며, 로컬에서 도는 JS 의 @huggingface/transformers 에도
Hugging Face Inference API 를 붙인다. 읽는 곳은 대상 디렉터리의 파이썬(.py, .pyw)·노트북(.ipynb) import 문(문법 트리)과
JS·TS(.js, .jsx, .cjs, .mjs, .ts, .tsx, .mts, .cts, .vue, .svelte)의 import·export·require 다. 데이터셋 찾기와 같은 폴더
(SKIP_DIRS, 숨은 폴더)는 건너뛴다.

SDK 는 아래 SDKS 다. 제공사와 서비스 이름은 cdxgen 과 같고, 파이썬은 각 SDK 의 실제 모듈 이름으로 맞췄다. LangChain 의
제공사 패키지(langchain_openai, @langchain/openai …)도 그 제공사의 API 를 부르므로 SDK 로 친다.

    남김    제공사(group)의 SDK 를 대상 어디선가 import 하는 cdxgen 서비스. version "observed" 는 고정값이라 뺀다
    만듦    SDK 를 import 하는데 그 제공사의 cdxgen 서비스가 없을 때 (모델 이름 없이 부르면 cdxgen 은 서비스를 만들지 않는다)
    뺌      나머지 서비스와 그 서비스가 든 관계
    관계    남긴 서비스가 허브 모델(model.hub_model_id)에 의존하는 관계는 뺀다. cdxgen 은 한 파일의 모델을 모두 그 파일의
            제공사 서비스에 붙이는데, 허브 모델은 내려받아 로컬에서 돌리므로 그 API 가 서비스하는 모델이 아니다
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from ..log import detail
from ..utils.files import SKIP_DIRS, inside, notebook_code, relative
from .model import hub_model_id

# (제공사, 서비스 이름, 파이썬 모듈, JS 패키지). 모듈은 그 이름이거나 그 아래 하위 모듈이면 맞는다 (openai.types)
SDKS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("openai", "OpenAI API", ("openai", "langchain_openai"),
     ("openai", "@openai/agents", "@openai/agents-core", "@langchain/openai")),
    ("anthropic", "Anthropic API", ("anthropic", "langchain_anthropic"), ("@anthropic-ai/sdk", "@langchain/anthropic")),
    ("google", "Google Generative AI API", ("google.genai", "google.generativeai", "langchain_google_genai"),
     ("@google/genai", "@google/generative-ai", "@google-ai/generativelanguage", "@langchain/google-genai")),
    ("azure-openai", "Azure OpenAI API", (), ("@azure/openai",)),
    ("huggingface", "Hugging Face Inference API", (), ("@huggingface/inference",)),
    ("groq", "Groq API", ("groq", "langchain_groq"), ("groq-sdk", "@langchain/groq")),
    ("cohere", "Cohere API", ("cohere", "langchain_cohere"), ("cohere-ai", "@langchain/cohere")),
    ("mistral", "Mistral API", ("mistralai", "langchain_mistralai"), ("@mistralai/mistralai", "@langchain/mistralai")),
    ("deepseek", "DeepSeek API", ("langchain_deepseek",), ("@deepseek/openai", "@langchain/deepseek")),
    ("together", "Together API", ("together", "langchain_together"), ("together-ai",)),
    ("fireworks", "Fireworks AI API", ("fireworks.client", "langchain_fireworks"), ("fireworks-ai",)),   # fireworks 만으로는 FireWorks(워크플로) 와 겹친다
    ("replicate", "Replicate API", ("replicate",), ("replicate",)),
    ("perplexity", "Perplexity API", ("perplexity", "perplexityai"), ()),
    ("ollama", "ollama-service", ("ollama", "langchain_ollama"), ("ollama", "@langchain/ollama")),
)
SERVICE_NAME = {provider: name for provider, name, _, _ in SDKS}
_PY_PROVIDER = {module: provider for provider, _, modules, _ in SDKS for module in modules}
_JS_PROVIDER = {package: provider for provider, _, _, packages in SDKS for package in packages}

PYTHON_SUFFIXES = frozenset({".py", ".pyw", ".ipynb"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".cjs", ".mjs", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte"})
# 줄 맨 앞의 import … from "x" · import "x" · export … from "x", 그리고 어디서든 require("x") · import("x")
_JS_IMPORTS = (
    re.compile(r"""^[ \t]*import\s+(?:[\w$*{},\s]+?\s+from\s+)?['"]([^'"\n]+)['"]""", re.MULTILINE),
    re.compile(r"""^[ \t]*export\s+(?:type\s+)?(?:\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s+from\s+['"]([^'"\n]+)['"]""", re.MULTILINE),
    re.compile(r"""\b(?:require|import)\s*\(\s*['"]([^'"\n]+)['"]\s*\)"""),
)


def discover_services(merged: dict, target: str) -> dict:
    """머리 설명대로 services[] 와 그 관계를 고친다. 서비스도 SDK import 도 없으면 문서는 그대로다."""
    services = merged.get("services") or []
    root = Path(target)
    imported = _sdk_imports(root) if root.is_dir() else {}
    if not services and not imported:
        return merged
    kept, dropped = [], set()
    for service in services:
        provider = service.get("group") or (service.get("provider") or {}).get("name")
        if provider in imported:
            kept.append({k: v for k, v in service.items() if not (k == "version" and v == "observed")})
        else:
            dropped.add(service.get("bom-ref"))
            detail(f"[service] {service.get('name')}: dropped, no SDK import for {provider}")
    have = {s.get("group") or (s.get("provider") or {}).get("name") for s in kept}
    for provider, _, _, _ in SDKS:
        if provider in imported and provider not in have:
            kept.append(_new_service(provider))
            detail(f"[service] {SERVICE_NAME[provider]}: added, SDK imported in {', '.join(imported[provider])}")
    merged["services"] = kept
    _fix_relations(merged, dropped, {s.get("bom-ref"): s.get("name") for s in kept})
    return merged


def _sdk_imports(root: Path) -> dict[str, list[str]]:
    """대상 디렉터리의 소스가 import 하는 SDK. 제공사 → 그 import 가 있는 파일들 (대상 기준 상대 경로)."""
    found: dict[str, list[str]] = {}
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        here = Path(dirpath)
        for filename in sorted(filenames):
            suffix = Path(filename).suffix.lower()
            if suffix not in PYTHON_SUFFIXES and suffix not in JS_SUFFIXES:
                continue
            path = here / filename
            if not inside(path, root_resolved):
                continue
            rel = relative(path, root)
            providers = _python_providers(path, rel) if suffix in PYTHON_SUFFIXES else _js_providers(path)
            for provider in providers:
                found.setdefault(provider, []).append(rel)
    return found


def _python_providers(path: Path, rel: str) -> set[str]:
    """파이썬 소스나 노트북 하나가 import 하는 SDK 의 제공사. 파싱이 안 되면 건너뛰고 알린다."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(notebook_code(text) if path.suffix.lower() == ".ipynb" else text)
    except (SyntaxError, ValueError, OSError, KeyError, TypeError) as e:
        detail(f"[service] {rel}: skipped, cannot parse ({e.__class__.__name__})")
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")   # from google import genai
    providers = set()
    for module in modules:
        parts = module.split(".")
        for i in range(1, len(parts) + 1):
            provider = _PY_PROVIDER.get(".".join(parts[:i]))
            if provider:
                providers.add(provider)
    return providers


def _js_providers(path: Path) -> set[str]:
    """JS·TS 소스 하나가 import 하는 SDK 의 제공사. 패키지 이름은 @scope/name 이나 name 까지만 본다 (openai/resources → openai)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    providers = set()
    for pattern in _JS_IMPORTS:
        for match in pattern.finditer(text):
            parts = match.group(1).split("/")
            package = "/".join(parts[:2]) if parts[0].startswith("@") else parts[0]
            if package in _JS_PROVIDER:
                providers.add(_JS_PROVIDER[package])
    return providers


def _new_service(provider: str) -> dict:
    """cdxgen 이 SDK import 로 만드는 서비스와 같은 모양 (bom-ref 규칙도 같다)."""
    name = SERVICE_NAME[provider]
    return {"bom-ref": f"urn:service:ai:{provider}:{re.sub(r'[^a-zA-Z0-9._:-]+', '-', name)}", "group": provider, "name": name,
            "provider": {"name": provider}, "tags": ["ai", provider]}


def _fix_relations(merged: dict, dropped: set[str], kept: dict[str, str]) -> None:
    """뺀 서비스의 행과 그 서비스로 가는 관계를 지우고, 남긴 서비스에서 허브 모델로 가는 관계를 지운다."""
    hub = {c.get("bom-ref"): model_id for c in _walk(merged.get("components") or []) if (model_id := hub_model_id(c))}
    rows = []
    for row in merged.get("dependencies") or []:
        ref = row.get("ref")
        if ref in dropped:
            continue
        targets = [t for t in row.get("dependsOn") or [] if t not in dropped]
        if ref in kept:
            for t in targets:
                if t in hub:
                    detail(f"[service] {kept[ref]}: dependency on hub model {hub[t]} dropped, hub models run locally")
            targets = [t for t in targets if t not in hub]
        rows.append({**row, "dependsOn": targets} if "dependsOn" in row else row)
    if "dependencies" in merged:
        merged["dependencies"] = rows


def _walk(components):
    for c in components:
        yield c
        yield from _walk(c.get("components") or [])
