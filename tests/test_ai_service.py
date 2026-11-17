"""ai_service — cdxgen 서비스 가운데 코드가 SDK 로 부르는 것만 남기고, 없는 것은 import 를 읽어 만든다. 네트워크는 쓰지 않는다."""
import copy
import json
from pathlib import Path

import pytest

import sure_aibom.engine.ai_service as sv

HUB_BERT = {"bom-ref": "pkg:huggingface/acme/acme-bert", "type": "machine-learning-model", "group": "acme", "name": "acme-bert",
            "purl": "pkg:huggingface/acme/acme-bert", "evidence": {"occurrences": [{"location": "app.py#L4"}]}}
API_MODEL = {"bom-ref": "pkg:generic/openai/gpt-4o-mini", "type": "machine-learning-model", "group": "openai", "name": "gpt-4o-mini",
             "purl": "pkg:generic/openai/gpt-4o-mini", "evidence": {"occurrences": [{"location": "app.py#L6"}]}}
LOCAL_MODEL = {"bom-ref": "pkg:huggingface/acme/acme-local", "type": "machine-learning-model", "group": "acme", "name": "acme-local",
               "purl": "pkg:huggingface/acme/acme-local", "evidence": {"occurrences": [{"location": "models/acme-local/README.md"}]}}
ROOT = "application:/project@"


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cdxgen_service(provider: str, name: str, ref_name: str | None = None, tags=("ai",)) -> dict:
    """cdxgen 이 만드는 서비스 모양. SDK import 로 만들면 bom-ref 가 서비스 이름이고 tags 에 제공사가 든다."""
    return {"bom-ref": f"urn:service:ai:{provider}:{ref_name or provider + '-service'}", "group": provider, "name": name,
            "provider": {"name": provider}, "version": "observed", "endpoints": [], "tags": list(tags)}


def doc_of(services: list[dict], dependencies: list[dict] = (), components: list[dict] = ()) -> dict:
    return {"metadata": {"component": {"type": "application", "name": "project", "bom-ref": ROOT}},
            "components": copy.deepcopy(list(components)), "services": services, "dependencies": copy.deepcopy(list(dependencies))}


NOTEBOOK = json.dumps({"cells": [{"cell_type": "markdown", "source": ["import openai\n"]},
                                 {"cell_type": "code", "source": ["!pip install groq\n", "import groq\n"]}]})


@pytest.mark.parametrize("name, text, expected", [
    ("app.py", "import openai\nfrom transformers import AutoModel\n", {"openai"}),                 # cdxgen 이 놓치는 import X 줄
    ("app.py", "import openai as oa\nfrom openai.types import ChatModel\n", {"openai"}),           # 하위 모듈도 그 SDK 다
    ("app.py", "from google import genai\nimport google.generativeai as legacy\n", {"google"}),
    ("app.py", "from langchain_openai import ChatOpenAI\nfrom langchain_anthropic import ChatAnthropic\n", {"openai", "anthropic"}),
    ("app.py", "def ask():\n    import anthropic\n    return anthropic.Anthropic()\n", {"anthropic"}),
    ("app.py", "from transformers import pipeline\nimport langchain\nfrom vllm import LLM\nimport openai_helper\n"
               "from fireworks import Firework\nfrom . import openai\n", set()),                         # 로컬 실행·프레임워크·이름만 비슷한 것·상대 import
    ("eval.ipynb", NOTEBOOK, {"groq"}),                                                               # 코드 셀만 (마크다운 셀은 아니다)
    ("app.ts", 'import OpenAI from "openai";\nimport type { Message } from "@anthropic-ai/sdk/resources";\n', {"openai", "anthropic"}),
    ("app.js", 'const { ChatGroq } = require("@langchain/groq");\nconst m = await import("@langchain/mistralai");\n', {"groq", "mistral"}),
    ("app.mjs", 'import {\n  pipeline,\n} from "@huggingface/transformers";\n// import OpenAI from "openai";\nexport * from "./local";\n', set()),
    ("App.vue", '<script setup>\nimport { HfInference } from "@huggingface/inference";\n</script>\n', {"huggingface"}),
    ("index.js", 'export { CohereClient } from "cohere-ai";\n', {"cohere"}),
])
def test_sdk_imports_are_read_from_python_notebooks_and_js(tmp_path, name, text, expected):
    write(tmp_path, f"src/{name}", text)
    assert sv._sdk_imports(tmp_path, log=lambda m: None) == {p: [f"src/{name}"] for p in expected}


def test_skipped_folders_and_unparsable_files(tmp_path):
    write(tmp_path, "node_modules/x/index.js", 'import OpenAI from "openai";\n')
    write(tmp_path, "venv/lib/python3.11/site-packages/a.py", "import anthropic\n")
    write(tmp_path, ".hidden/a.py", "import groq\n")
    write(tmp_path, "src/broken.py", "import (\n")
    write(tmp_path, "src/ok.py", "import replicate\n")
    logs: list[str] = []
    assert sv._sdk_imports(tmp_path, logs.append) == {"replicate": ["src/ok.py"]}
    assert logs == ["[service] src/broken.py: skipped, cannot parse (SyntaxError)"]


def test_services_are_kept_only_with_an_sdk_import(tmp_path):
    """SDK import 가 근거다. 모델 이름으로 짐작한 서비스(vLLM 으로 로컬에서 돌리는 Mistral), 허브 모델 조직의 서비스, Modelfile 의
    서비스, 로컬 실행 라이브러리(@huggingface/transformers)에 cdxgen 이 붙인 서비스는 빼고, 그 서비스가 든 관계도 뺀다."""
    write(tmp_path, "app.py", "import anthropic\nfrom openai import OpenAI\nfrom vllm import LLM\n")
    write(tmp_path, "web.js", 'import { pipeline } from "@huggingface/transformers";\n')
    services = [cdxgen_service("openai", "OpenAI API", "OpenAI-API", ("ai", "openai")),
                cdxgen_service("anthropic", "Anthropic API"),                                             # 모델 이름으로 짐작 (import 를 놓쳤다)
                cdxgen_service("mistral", "Mistral API"),
                cdxgen_service("acme", "acme-service"),
                cdxgen_service("ollama", "ollama-service"),
                cdxgen_service("huggingface", "Hugging Face Inference API", "Hugging-Face-Inference-API", ("ai", "huggingface"))]
    deps = [{"ref": ROOT, "dependsOn": [API_MODEL["bom-ref"]]},
            {"ref": "urn:file:ai:notebooks/eval.ipynb", "dependsOn": ["urn:service:ai:acme:acme-service", "urn:service:ai:openai:OpenAI-API"]},
            {"ref": "urn:service:ai:openai:OpenAI-API", "dependsOn": [API_MODEL["bom-ref"]]},
            {"ref": "urn:service:ai:mistral:mistral-service", "dependsOn": ["pkg:generic/mistral/mistral-7b-instruct"]},
            {"ref": "urn:service:ai:acme:acme-service", "dependsOn": [HUB_BERT["bom-ref"]]}]
    logs: list[str] = []
    out = sv.discover_services(doc_of(copy.deepcopy(services), deps, [API_MODEL, HUB_BERT]), str(tmp_path), logs.append)
    assert out["services"] == [{k: v for k, v in s.items() if k != "version"} for s in services[:2]]
    assert out["dependencies"] == [deps[0], {"ref": "urn:file:ai:notebooks/eval.ipynb", "dependsOn": ["urn:service:ai:openai:OpenAI-API"]}, deps[2]]
    assert logs == [f"[service] {name}: dropped, no SDK import for {provider}"
                    for provider, name in (("mistral", "Mistral API"), ("acme", "acme-service"), ("ollama", "ollama-service"),
                                           ("huggingface", "Hugging Face Inference API"))]


def test_an_sdk_import_without_a_cdxgen_service_makes_one(tmp_path):
    """모델 이름 없이 부르면 cdxgen 은 서비스를 만들지 않는다. 같은 제공사의 cdxgen 서비스가 있으면 새로 만들지 않는다."""
    write(tmp_path, "agent.py", "import os\nfrom langchain_groq import ChatGroq\nimport anthropic\n\nllm = ChatGroq(model=os.environ['M'])\n")
    logs: list[str] = []
    out = sv.discover_services(doc_of([cdxgen_service("anthropic", "Anthropic API")]), str(tmp_path), logs.append)
    assert out["services"] == [{k: v for k, v in cdxgen_service("anthropic", "Anthropic API").items() if k != "version"},
                               {"bom-ref": "urn:service:ai:groq:Groq-API", "group": "groq", "name": "Groq API",
                                "provider": {"name": "groq"}, "tags": ["ai", "groq"]}]
    assert logs == ["[service] Groq API: added, SDK imported in agent.py"]


def test_kept_services_lose_their_hub_model_relations(tmp_path):
    """cdxgen 은 한 파일의 모델을 모두 그 파일의 SDK 서비스에 붙인다. 허브 모델(코드가 이름으로 부르는 것)은 내려받아 로컬에서
    돌리므로 그 관계만 뺀다. API 모델과 로컬 모델 파일에서 찾은 모델은 그대로 둔다."""
    write(tmp_path, "app.py", "from openai import OpenAI\n")
    deps = [{"ref": "urn:service:ai:openai:OpenAI-API", "dependsOn": [HUB_BERT["bom-ref"], API_MODEL["bom-ref"], LOCAL_MODEL["bom-ref"]]}]
    logs: list[str] = []
    out = sv.discover_services(doc_of([cdxgen_service("openai", "OpenAI API", "OpenAI-API", ("ai", "openai"))], deps, [HUB_BERT, API_MODEL, LOCAL_MODEL]),
                      str(tmp_path), logs.append)
    assert out["dependencies"] == [{"ref": "urn:service:ai:openai:OpenAI-API", "dependsOn": [API_MODEL["bom-ref"], LOCAL_MODEL["bom-ref"]]}]
    assert logs == ["[service] OpenAI API: dependency on hub model acme/acme-bert dropped, hub models run locally"]


def test_without_services_or_sdk_imports_the_document_is_byte_identical(tmp_path):
    write(tmp_path, "train.py", "from transformers import AutoModel\nmodel = AutoModel.from_pretrained('acme/acme-bert')\n")
    doc = doc_of([], [{"ref": ROOT, "dependsOn": [HUB_BERT["bom-ref"]]}], [HUB_BERT])
    before = json.dumps(doc, sort_keys=True)
    assert json.dumps(sv.discover_services(doc, str(tmp_path), log=lambda m: None), sort_keys=True) == before
    assert json.dumps(sv.discover_services(doc, "alpine:3.20", log=lambda m: None), sort_keys=True) == before      # 풀지 못한 이미지 (디렉터리가 아니다)


def test_running_twice_changes_nothing(tmp_path):
    write(tmp_path, "app.py", "import anthropic\nfrom langchain_groq import ChatGroq\n")
    deps = [{"ref": "urn:service:ai:anthropic:anthropic-service", "dependsOn": [HUB_BERT["bom-ref"]]}]
    once = sv.discover_services(doc_of([cdxgen_service("anthropic", "Anthropic API"), cdxgen_service("acme", "acme-service")], deps, [HUB_BERT]),
                       str(tmp_path), log=lambda m: None)
    assert sv.discover_services(copy.deepcopy(once), str(tmp_path), log=lambda m: None) == once
