"""fields 픽스처를 만든다: syft·cdxgen·OWASP aibom-generator·aibom-cli 가 낼 수 있는 필드를 모두 끌어내도록 꾸민 허구의 프로젝트.

    python tests/data/fields/make_fields.py      # 이 폴더의 project/ · rootfs/ · hf_api/ · owasp/ 를 다시 쓴다

값은 지어낸 것이다 (acme 조직, example 주소). 모양만 실제 형식(Hugging Face 모델 카드, GGUF, safetensors, Modelfile,
dist-info, package-lock.json, pom.xml, jar, dpkg status …)을 따르고, 공개 패키지 몇 개(requests, rack …)는 실제 이름을 쓴다.
tests/test_fields.py 가 이 픽스처를 실제 syft·cdxgen 으로 스캔해 값마다 출처를 따라가고, 그 결과가
docs/mapping-viewer/data/aibom_cli_sources.json (필드 탐색기의 도구 배지)이다.

    project/   디렉터리 스캔 대상. 이미지에서는 /app
               models/ · Modelfile · deploy/Modelfile · src/ · notebooks/   cdxgen 이 찾는 모델·데이터셋 참조
               data/                                                     scan --data 로 주는 로컬 데이터
               requirements.txt · package-lock.json · pom.xml · lib/*.jar · go.mod · Cargo.lock · Gemfile.lock ·
               *.gemspec · composer.lock · conda-meta/                   syft 의 디렉터리 카탈로거
               node_modules/left-pad/package.json                         syft 가 이미지에서만 읽는다
    rootfs/    이미지의 바닥 레이어 (OS 와 설치된 패키지). syft 가 이미지에서 읽는 것: os-release, dpkg, busybox,
               site-packages 의 dist-info, 설치된 gemspec
    hf_api/    허브 응답 (GET /api/models|datasets/<id>, datasets-server /size·/statistics). tests/data/hf_api 의 실제 녹화본과 키 구성이 같다
    owasp/     OWASP aibom-generator 출력. 실제 출력(tests/data/owasp, 조사 때 실제 9건 실행)과 같은 모양이다

이미지는 테스트가 rootfs/ 와 project/ 로 docker save 모양의 tar 를 만들어 스캔한다 (OCI 라벨 IMAGE_LABELS 포함).
"""
from __future__ import annotations

import io
import json
import shutil
import struct
import sys
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).parent
IMAGE_TAG = "acme-app:1.4.0"
IMAGE_LABELS = {
    "org.opencontainers.image.title": "acme-app",
    "org.opencontainers.image.description": "Acme review assistant",
    "org.opencontainers.image.version": "1.4.0",
    "org.opencontainers.image.revision": "0123456789abcdef0123456789abcdef01234567",
    "org.opencontainers.image.source": "https://github.com/acme/acme-app",
    "org.opencontainers.image.url": "https://acme.example/app",
    "org.opencontainers.image.documentation": "https://acme.example/app/docs",
    "org.opencontainers.image.licenses": "Apache-2.0",
    "org.opencontainers.image.vendor": "Acme Corp",
    "org.opencontainers.image.authors": "Acme ML Team <ml@acme.example>",
    "org.opencontainers.image.created": "2026-10-01T00:00:00Z",
    "org.opencontainers.image.base.name": "docker.io/library/debian:12-slim",
    "org.opencontainers.image.base.digest": "sha256:" + "d1" * 32,
    "maintainer": "ml@acme.example",
}


def write(root: Path, rel: str, data: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ── 바이너리 형식 (tests/test_model.py 의 작성 도우미와 같은 형식) ──────────────────────────
def _text(v: str) -> bytes:
    b = v.encode()
    return struct.pack("<Q", len(b)) + b


def gstr(key, value):
    return (key, 8, _text(value))


def gu32(key, value):
    return (key, 4, struct.pack("<I", value))


def gu64(key, value):
    return (key, 10, struct.pack("<Q", value))


def gstrs(key, values):
    return (key, 9, struct.pack("<I", 8) + struct.pack("<Q", len(values)) + b"".join(_text(v) for v in values))


def gfloats(key, values):
    return (key, 9, struct.pack("<I", 6) + struct.pack("<Q", len(values)) + b"".join(struct.pack("<f", v) for v in values))


def gints(key, values):
    return (key, 9, struct.pack("<I", 5) + struct.pack("<Q", len(values)) + b"".join(struct.pack("<i", v) for v in values))


def gguf(kv, tensors) -> bytes:
    body = b"".join(_text(k) + struct.pack("<I", kind) + payload for k, kind, payload in kv)
    info = b"".join(_text(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims)
                    + struct.pack("<I", 0) + struct.pack("<Q", 0) for name, dims in tensors)
    return b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", len(tensors)) + struct.pack("<Q", len(kv)) + body + info


def safetensors(shapes: dict[str, list[int]]) -> bytes:
    header = {name: {"dtype": "F32", "shape": shape, "data_offsets": [0, 4]} for name, shape in shapes.items()}
    raw = json.dumps(header).encode()
    return struct.pack("<Q", len(raw)) + raw + b"\0" * 8


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + b"\0\0\0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def wav(seconds: float, rate: int = 8000) -> bytes:
    data = b"\0\0" * int(seconds * rate)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def jar(entries: dict[str, str | bytes]) -> bytes:
    """날짜를 고정한 zip (바이트가 늘 같아야 syft 가 낸 SHA-1 이 같다)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


# ── 모델 (cdxgen 의 네 경로: 로컬 Hugging Face 폴더 · GGUF · Modelfile · 코드) ─────────────────────
MODEL_CARD = """---
license: apache-2.0
language:
  - en
  - ko
library_name: transformers
pipeline_tag: text-classification
tags:
  - sentiment
  - text-classification
base_model: acme/acme-base
base_model_relation: finetune
datasets:
  - acme/reviews
  - acmecorpus
model_description: Acme sentiment classifier fine-tuned from acme-base on product reviews.
mask_token: "[MASK]"
widget:
  - text: I love this product
extra_gated_prompt: You agree to use this model only for research.
extra_gated_fields:
  Company: text
  Country: country
co2_eq_emissions:
  emissions: 1250
  source: CodeCarbon
  training_type: fine-tuning
  geographical_location: Seoul, South Korea
  hardware_used: 1 x A100
model-index:
  - name: acme-local
    results:
      - task:
          type: text-classification
          name: Text Classification
        dataset:
          name: Acme Sentiment Eval
          type: acme/sentiment-eval
          split: test
        metrics:
          - type: accuracy
            value: 0.912
            name: Accuracy
          - type: f1
            value: 0.887
---
# acme-local

Acme sentiment classifier for product reviews.
"""

CONFIG = {
    "_name_or_path": "acme/acme-local", "model_type": "bert", "architectures": ["BertForSequenceClassification"],
    "hidden_size": 64, "num_hidden_layers": 2, "num_attention_heads": 2, "num_key_value_heads": 2, "intermediate_size": 128,
    "max_position_embeddings": 512, "vocab_size": 1000,
    "quantization_config": {"quant_method": "bitsandbytes", "load_in_8bit": True},
}

ADAPTER = {"base_model_name_or_path": "acme/acme-local", "peft_type": "LORA", "task_type": "SEQ_CLS", "r": 8, "lora_alpha": 16,
           "target_modules": ["query", "value"]}

TRAIN_PY = '''from datasets import load_dataset
from transformers import AutoModel, pipeline

bert = AutoModel.from_pretrained("acme/acme-bert")
chat = pipeline("text-generation", model="acme/acme-chat-GGUF")
private = AutoModel.from_pretrained("acme/acme-private")
reviews = load_dataset("acme/reviews")
EVAL_SET = "https://huggingface.co/datasets/acme/eval-set"
DEMO = "https://huggingface.co/spaces/acme/acme-demo"
'''

APP_JS = '''import OpenAI from "openai";

const client = new OpenAI();
const model = "gpt-4o-mini";
export async function ask(q) {
  return client.chat.completions.create({ model, messages: [{ role: "user", content: q }] });
}
'''

NOTEBOOK = {"cells": [
    {"cell_type": "markdown", "metadata": {}, "source": ["# Evaluation\n"]},
    {"cell_type": "code", "metadata": {}, "execution_count": 1, "outputs": [],
     "source": ["from datasets import load_dataset\n", "notes = load_dataset(\"acme/notebook-set\")\n"]},
], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}

# ollama 에 로컬 GGUF 를 들이는 표준 모양. LICENSE 본문이 따옴표 바로 뒤에서 시작한다
MODELFILE = '''FROM ./models/acme-tiny-chat-Q4_K_M.gguf
PARAMETER num_ctx 4096
PARAMETER temperature 0.7
SYSTEM You are Acme, a helpful assistant.
LICENSE """MIT License

Copyright (c) 2026 Acme
"""
'''

# ollama 라이브러리 모델. LICENSE 본문이 따옴표 다음 줄에서 시작한다
DEPLOY_MODELFILE = '''FROM llama3.2:1b
PARAMETER num_ctx 8192
LICENSE """
LLAMA 3.2 COMMUNITY LICENSE AGREEMENT
Llama 3.2 Version Release Date: September 25, 2024
"""
'''


def tiny_chat_gguf() -> bytes:
    vocab = ["<unk>", "<s>", "</s>", "<pad>", "a", "b", "c", "ab"]
    kv = [
        gstr("general.architecture", "llama"), gstr("general.type", "model"),
        gstr("general.name", "Acme Tiny Chat"), gstr("general.basename", "acme-tiny-chat"), gstr("general.finetune", "chat"),
        gstr("general.version", "v1.0"), gstr("general.size_label", "15M"),
        gstr("general.description", "Acme tiny chat model."),
        gstr("general.organization", "Acme"), gstr("general.license", "mit"),
        gstr("general.license.link", "https://acme.example/licenses/mit"),
        gstr("general.url", "https://acme.example/models/acme-tiny-chat"), gstr("general.repo_url", "https://github.com/acme/acme-tiny-chat"),
        gstr("general.source.url", "https://acme.example/models/acme-tiny"), gstr("general.source.repo_url", "https://huggingface.co/acme/acme-tiny"),
        gstr("general.doi", "10.5555/acme.2026.1"), gstr("general.source.doi", "10.5555/acme.2025.9"),
        gu32("general.base_model.count", 1), gstr("general.base_model.0.name", "Acme Tiny"),
        gstr("general.base_model.0.organization", "Acme"), gstr("general.base_model.0.repo_url", "https://huggingface.co/acme/acme-tiny"),
        gstrs("general.datasets", ["acme/chat-sft"]), gstrs("general.tags", ["text-generation", "chat"]), gstrs("general.languages", ["en"]),
        gu32("general.file_type", 15), gu32("general.quantization_version", 2), gstr("general.quantized_by", "acme"),
        gu64("general.parameter_count", 15000000),
        gu32("llama.context_length", 2048), gu32("llama.embedding_length", 256), gu32("llama.block_count", 4),
        gu32("llama.feed_forward_length", 768), gu32("llama.attention.head_count", 4), gu32("llama.attention.head_count_kv", 2),
        gu32("llama.rope.dimension_count", 64), gu32("llama.vocab_size", len(vocab)),
        gstr("tokenizer.ggml.model", "llama"), gstrs("tokenizer.ggml.tokens", vocab), gfloats("tokenizer.ggml.scores", [0.0] * len(vocab)),
        gints("tokenizer.ggml.token_type", [2, 3, 3, 3, 1, 1, 1, 1]), gstrs("tokenizer.ggml.merges", ["a b"]),
        gu32("tokenizer.ggml.bos_token_id", 1), gu32("tokenizer.ggml.eos_token_id", 2), gu32("tokenizer.ggml.unknown_token_id", 0),
        gu32("tokenizer.ggml.padding_token_id", 3), gu32("tokenizer.ggml.seperator_token_id", 2),
        gstr("tokenizer.chat_template", "{% for m in messages %}{{ m['content'] }}{% endfor %}"),
    ]
    tensors = [("token_embd.weight", [256, len(vocab)]), ("blk.0.attn_q.weight", [256, 256]), ("output.weight", [256, len(vocab)])]
    return gguf(kv, tensors)


def build_models(root: Path) -> None:
    write(root, "models/acme-local/README.md", MODEL_CARD)
    write(root, "models/acme-local/config.json", dump(CONFIG))
    write(root, "models/acme-local/model.safetensors", safetensors({"embeddings.weight": [1000, 64], "classifier.weight": [2, 64]}))
    write(root, "models/acme-lora/adapter_config.json", dump(ADAPTER))
    write(root, "models/acme-tiny-chat-Q4_K_M.gguf", tiny_chat_gguf())
    write(root, "Modelfile", MODELFILE)
    write(root, "deploy/Modelfile", DEPLOY_MODELFILE)
    write(root, "src/train.py", TRAIN_PY)
    write(root, "src/app.js", APP_JS)
    write(root, "notebooks/eval.ipynb", json.dumps(NOTEBOOK, ensure_ascii=False, indent=1) + "\n")


# ── 로컬 데이터 (scan --data project/data) ───────────────────────────────────────────────
def build_data(root: Path) -> None:
    write(root, "data/train.csv", "id,text,label,score\n1,good movie,pos,0.9\n2,bad movie,neg,0.1\n3,fine,pos,0.6\n4,meh,neg,0.4\n")
    write(root, "data/notes.jsonl", '{"text": "first note", "len": 10}\n{"text": "second", "len": 6}\n')
    for i, (cls, w, h) in enumerate([("cat", 4, 3), ("cat", 6, 3), ("dog", 5, 5)]):
        write(root, f"data/images/train/{cls}/{i}.png", png(w, h))
    write(root, "data/audio/hello.wav", wav(0.5))


# ── 소프트웨어: syft 디렉터리 카탈로거가 읽는 것 (project/) ─────────────────────────────────────
REQUIREMENTS = """requests==2.31.0 --hash=sha256:58cd2187c01e70e6e26505bca751777aa9f2ee0b7f4300988b709f44e013003f
transformers==4.44.2
datasets==2.21.0
Flask[async]==2.3.2 ; python_version > "3.7"
numpy>=1.24
"""

PACKAGE_JSON = {
    "name": "acme-web", "version": "1.0.0", "description": "Acme review assistant web client", "license": "ISC",
    "dependencies": {"@acme/ui": "^2.0.0", "left-pad": "1.3.0", "openai": "^4.52.0"},
    "devDependencies": {"eslint-plugin-acme": "0.0.1"},
}

PACKAGE_LOCK = {
    "name": "acme-web", "version": "1.0.0", "lockfileVersion": 3, "requires": True,
    "packages": {
        "": {"name": "acme-web", "version": "1.0.0", "license": "ISC",
             "dependencies": {"@acme/ui": "^2.0.0", "left-pad": "1.3.0", "openai": "^4.52.0"},
             "devDependencies": {"eslint-plugin-acme": "0.0.1"}},
        "node_modules/@acme/ui": {
            "version": "2.1.0", "resolved": "https://registry.npmjs.org/@acme/ui/-/ui-2.1.0.tgz",
            "integrity": "sha512-" + "A" * 86 + "==", "license": "(MIT OR Apache-2.0)", "dependencies": {"left-pad": "^1.0.0"}},
        "node_modules/left-pad": {
            "version": "1.3.0", "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz",
            "integrity": "sha512-XI5MPzVNApjAyhQzphX8BkmKsKUxD4LdyK24iZeQEhkU4jYMNo9BTBSDY1qT2tT1Z0q9Nrbwx3ZZ8M0O9C6Q==", "license": "WTFPL"},
        "node_modules/openai": {
            "version": "4.52.0", "resolved": "https://registry.npmjs.org/openai/-/openai-4.52.0.tgz",
            "integrity": "sha512-" + "B" * 86 + "==", "license": "Apache-2.0"},
        "node_modules/eslint-plugin-acme": {
            "version": "0.0.1", "resolved": "https://registry.npmjs.org/eslint-plugin-acme/-/eslint-plugin-acme-0.0.1.tgz",
            "integrity": "sha512-" + "C" * 86 + "==", "dev": True, "license": "MIT"},
    },
}

# 이미지 스캔에서만 읽힌다 (javascript-package-cataloger 는 이미지 전용)
LEFT_PAD_PACKAGE = {
    "name": "left-pad", "version": "1.3.0", "description": "String left pad",
    "author": {"name": "azer", "email": "azer@example.com", "url": "http://azer.example"},
    "homepage": "https://github.com/stevemao/left-pad#readme",
    "repository": {"type": "git", "url": "git+https://github.com/stevemao/left-pad.git"},
    "license": "WTFPL", "main": "index.js",
}

POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId>
  <artifactId>acme-service</artifactId>
  <version>1.0.0</version>
  <name>Acme Service</name>
  <licenses>
    <license><name>Apache License, Version 2.0</name><url>https://www.apache.org/licenses/LICENSE-2.0.txt</url></license>
    <license><name></name><url>https://opensource.org/licenses/MIT</url></license>
  </licenses>
  <dependencies>
    <dependency>
      <groupId>org.apache.commons</groupId>
      <artifactId>commons-lang3</artifactId>
      <version>3.14.0</version>
    </dependency>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>4.13.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
"""

JAR_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme.util</groupId>
  <artifactId>acme-util</artifactId>
  <version>2.0.0</version>
  <licenses><license><name>Apache-2.0</name><url>https://www.apache.org/licenses/LICENSE-2.0.txt</url></license></licenses>
</project>
"""

GO_MOD = """module acme.example/tools

go 1.22

require (
\tgithub.com/google/uuid v1.6.0
\tgolang.org/x/text v0.14.0 // indirect
)
"""

GO_SUM = """github.com/google/uuid v1.6.0 h1:NIvaJDMOsjHA8n1jAhLSgzrAzy1Hgr+hNrb57e+94F0=
github.com/google/uuid v1.6.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
golang.org/x/text v0.14.0 h1:ScX5w1eTa3QqT8oi6+ziP7dTV1S2+ALU0bI+0zXKWiQ=
golang.org/x/text v0.14.0/go.mod h1:18ZOQIKpY8NJVqYksKHtTdi31H5itFRjB5/qKTNYzSU=
"""

CARGO_LOCK = """# This file is automatically @generated by Cargo.
version = 3

[[package]]
name = "acme-cli"
version = "0.1.0"
dependencies = [
 "serde",
]

[[package]]
name = "serde"
version = "1.0.197"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "3fb1c873e1b9b056a4dc4c0c198b24c3ffa059243875552b2bd0933b1aee4ce2"
"""

GEMFILE_LOCK = """GEM
  remote: https://rubygems.org/
  specs:
    loofah (2.22.0)
    rack (3.0.8)
    rails-html-sanitizer (1.6.0)
      loofah (~> 2.21)

PLATFORMS
  ruby

DEPENDENCIES
  rack
  rails-html-sanitizer

BUNDLED WITH
   2.4.10
"""

GEMSPEC = """# -*- encoding: utf-8 -*-
Gem::Specification.new do |s|
  s.name = "acme_tools"
  s.version = "0.4.2"
  s.authors = ["Alice Acme", "Bob Acme"]
  s.email = ["alice@acme.example"]
  s.homepage = "https://acme.example/acme_tools"
  s.licenses = ["MIT", "Ruby"]
  s.summary = "Acme command line tools"
  s.files = ["lib/acme_tools.rb"]
end
"""

COMPOSER_LOCK = {
    "_readme": ["This file locks the dependencies of your project to a known state"],
    "content-hash": "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    "packages": [
        {"name": "acme/dual-licensed", "version": "1.0.0", "type": "library", "license": ["MIT", "(Apache-2.0 OR BSD-3-Clause)"]},
        {"name": "acme/internal-sdk", "version": "1.0.0", "type": "library", "license": ["proprietary"]},
        {"name": "monolog/monolog", "version": "3.5.0",
         "source": {"type": "git", "url": "https://github.com/Seldaek/monolog.git", "reference": "c915e2634718dbc8a4a15c61b0e62e7a44e14448"},
         "require": {"php": ">=8.1", "psr/log": "^2.0 || ^3.0"}, "type": "library", "license": ["MIT"],
         "description": "Sends your logs to files, sockets, inboxes, databases and various web services"},
        {"name": "psr/log", "version": "3.0.0", "type": "library", "license": ["MIT"], "description": "Common interface for logging libraries"},
    ],
    "packages-dev": [],
}

CONDA_META = {
    "name": "jupyterlab", "version": "4.4.3", "build": "pyhd8ed1ab_0", "build_number": 0,
    "depends": ["jinja2 >=3.0.3", "python >=3.9", "tornado >=6.2.0"],
    "license": "BSD-3-Clause", "license_family": "BSD", "noarch": "python", "subdir": "noarch",
    "fn": "jupyterlab-4.4.3-pyhd8ed1ab_0.conda",
    "url": "https://conda.anaconda.org/conda-forge/noarch/jupyterlab-4.4.3-pyhd8ed1ab_0.conda",
    "channel": "https://conda.anaconda.org/conda-forge/",
    "md5": "4861a0c2a5a5d0481a450a9dfaf9febe",
    "sha256": "fc0235a71d852734fe92183a78cb91827367573450eba82465ae522c64230736",
    "files": [],
}


def build_software(root: Path) -> None:
    write(root, "requirements.txt", REQUIREMENTS)
    write(root, "package.json", dump(PACKAGE_JSON))
    write(root, "package-lock.json", dump(PACKAGE_LOCK))
    write(root, "node_modules/left-pad/package.json", dump(LEFT_PAD_PACKAGE))
    write(root, "pom.xml", POM)
    write(root, "lib/acme-util-2.0.0.jar", jar({
        "META-INF/MANIFEST.MF": ("Manifest-Version: 1.0\r\nImplementation-Title: acme-util\r\nImplementation-Version: 2.0.0\r\n"
                                 "Implementation-Vendor: Acme Corp\r\nBundle-SymbolicName: com.acme.util.acme-util\r\n\r\n"),
        "META-INF/maven/com.acme.util/acme-util/pom.properties": "groupId=com.acme.util\nartifactId=acme-util\nversion=2.0.0\n",
        "META-INF/maven/com.acme.util/acme-util/pom.xml": JAR_POM,
        "com/acme/util/Util.class": b"\xca\xfe\xba\xbe\0\0\0\x34",
    }))
    write(root, "go.mod", GO_MOD)
    write(root, "go.sum", GO_SUM)
    write(root, "Cargo.lock", CARGO_LOCK)
    write(root, "Gemfile.lock", GEMFILE_LOCK)
    write(root, "acme_tools.gemspec", GEMSPEC)
    write(root, "composer.lock", dump(COMPOSER_LOCK))
    write(root, "conda-meta/jupyterlab-4.4.3-pyhd8ed1ab_0.json", dump(CONDA_META))


# ── 이미지 바닥 레이어 (rootfs/): OS 와 설치된 패키지 ─────────────────────────────────────────
OS_RELEASE = """PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
NAME="Debian GNU/Linux"
VERSION_ID="12"
VERSION="12 (bookworm)"
VERSION_CODENAME=bookworm
ID=debian
HOME_URL="https://www.debian.org/"
SUPPORT_URL="https://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
PRIVACY_POLICY_URL="https://www.debian.org/legal/privacy"
CPE_NAME="cpe:/o:debian:debian_linux:12"
"""

DPKG_STATUS = """Package: libfoo1
Status: install ok installed
Priority: optional
Section: libs
Installed-Size: 120
Maintainer: Debian Foo Maintainers <foo@debian.org>
Architecture: amd64
Multi-Arch: same
Source: foo (1.2-3)
Version: 1.2-3+b1
Depends: libc6 (>= 2.14)
Description: foo shared library
 Longer description line for libfoo1.
Homepage: https://foo.example.org

Package: libc6
Status: install ok installed
Priority: optional
Section: libs
Installed-Size: 12000
Maintainer: GNU Libc Maintainers <debian-glibc@lists.debian.org>
Architecture: amd64
Source: glibc
Version: 2.36-9
Description: GNU C Library: Shared libraries
Homepage: https://www.gnu.org/software/libc/libc.html

"""

LIBFOO_COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: foo

Files: *
Copyright: 2026 Foo Authors
License: MIT

License: MIT
 Permission is hereby granted, free of charge...
"""

# DEP-5 형식이 아닌 copyright: syft 는 라이선스를 알아보지 못하고 본문의 sha256 을 이름으로 낸다
LIBC_COPYRIGHT = """This is the Debian prepackaged version of the GNU C Library.

It was put together by the GNU Libc Maintainers from the upstream sources.
Copyright (C) 1991-2023 Free Software Foundation, Inc.
"""

BUSYBOX = b"\x7fELF-not-really\nBusyBox v1.36.1 (2023-11-07 18:53:09 UTC) multi-call binary.\n"

ACME_SDK_METADATA = """Metadata-Version: 2.1
Name: acme-sdk
Version: 1.2.3
Summary: Acme model serving SDK
Home-page: https://acme.example/acme-sdk
Author: Jane Doe
Author-email: jane@acme.example
License: MIT
Project-URL: Source, https://github.com/acme/acme-sdk
Requires-Python: >=3.8
Requires-Dist: helper-lib (>=0.5)
License-File: LICENSE
Description-Content-Type: text/markdown

# acme-sdk
"""

HELPER_METADATA = """Metadata-Version: 2.4
Name: helper-lib
Version: 0.6.0
Summary: Helper library
Author-email: Helper Team <team@helper.example>
License-Expression: Apache-2.0 OR MIT
Requires-Python: >=3.9
"""

LOCALPROJ_METADATA = """Metadata-Version: 2.1
Name: localproj
Version: 0.0.1
Summary: Editable install of a local checkout
Author: Dev Acme
License: Custom Proprietary License v2
"""

RACK_GEMSPEC = """# -*- encoding: utf-8 -*-
Gem::Specification.new do |s|
  s.name = "rack".freeze
  s.version = "3.0.8"
  s.authors = ["Leah Neukirchen".freeze]
  s.homepage = "https://github.com/rack/rack".freeze
  s.licenses = ["MIT".freeze]
  s.summary = "A modular Ruby webserver interface".freeze
end
"""

SITE = "usr/local/lib/python3.11/site-packages"


def build_rootfs(root: Path) -> None:
    write(root, "etc/os-release", OS_RELEASE)
    write(root, "var/lib/dpkg/status", DPKG_STATUS)
    write(root, "var/lib/dpkg/info/libfoo1:amd64.md5sums", "2d827332e71369fb585f95e922e6fd8c  usr/lib/x86_64-linux-gnu/libfoo.so.1\n")
    write(root, "usr/lib/x86_64-linux-gnu/libfoo.so.1", b"\x7fELF-libfoo\n")
    write(root, "usr/share/doc/libfoo1/copyright", LIBFOO_COPYRIGHT)
    write(root, "usr/share/doc/libc6/copyright", LIBC_COPYRIGHT)
    write(root, "bin/busybox", BUSYBOX)
    write(root, f"{SITE}/acme_sdk/__init__.py", '__version__ = "1.2.3"\n')
    write(root, f"{SITE}/acme_sdk-1.2.3.dist-info/METADATA", ACME_SDK_METADATA)
    write(root, f"{SITE}/acme_sdk-1.2.3.dist-info/RECORD",
          "acme_sdk/__init__.py,,\nacme_sdk-1.2.3.dist-info/METADATA,,\nacme_sdk-1.2.3.dist-info/RECORD,,\n"
          "acme_sdk-1.2.3.dist-info/direct_url.json,,\n")
    write(root, f"{SITE}/acme_sdk-1.2.3.dist-info/direct_url.json",
          json.dumps({"url": "https://github.com/acme/acme-sdk.git",
                      "vcs_info": {"vcs": "git", "commit_id": "89abcdef0123456789abcdef0123456789abcdef", "requested_revision": "v1.2.3"}}) + "\n")
    write(root, f"{SITE}/acme_sdk-1.2.3.dist-info/licenses/LICENSE", "MIT License\n\nCopyright (c) 2026 Acme\n")
    write(root, f"{SITE}/helper_lib/__init__.py", "x = 1\n")
    write(root, f"{SITE}/helper_lib-0.6.0.dist-info/METADATA", HELPER_METADATA)
    write(root, f"{SITE}/helper_lib-0.6.0.dist-info/RECORD",
          "helper_lib/__init__.py,,\nhelper_lib-0.6.0.dist-info/METADATA,,\nhelper_lib-0.6.0.dist-info/RECORD,,\n")
    # pip install -e 로 들인 로컬 사본: direct_url 이 file:// 주소다
    write(root, f"{SITE}/localproj-0.0.1.dist-info/METADATA", LOCALPROJ_METADATA)
    write(root, f"{SITE}/localproj-0.0.1.dist-info/direct_url.json",
          json.dumps({"url": "file:///home/dev/src/localproj", "dir_info": {"editable": True}}) + "\n")
    write(root, "usr/local/lib/ruby/gems/3.2.0/specifications/rack-3.0.8.gemspec", RACK_GEMSPEC)


# ── 허구의 허브 응답 ─────────────────────────────────────────────────────────────────────
# 이름: hf_<종류>_<owner>_<name>[_<config>_<split>].json. 허브가 옛 이름 acmecorpus 를 acme/acmecorpus 로 돌려주는 것은 테스트가 흉내 낸다.
# acme/acme-private 는 비공개 저장소라 응답이 없다 (허브가 401 을 준 것과 같다)
SHA = {"acme/acme-bert": "a1" * 20, "acme/acme-chat-GGUF": "b2" * 20, "acme/reviews": "c3" * 20, "acme/acmecorpus": "d4" * 20,
       "acme/sentiment-eval": "e5" * 20, "acme/eval-set": "f6" * 20, "acme/notebook-set": "a7" * 20, "acme/chat-sft": "b8" * 20}


def _model_index(name, dataset, metrics):
    return [{"name": name, "results": [{"task": {"type": "fill-mask", "name": "Fill Mask"}, "dataset": dataset,
                                        "metrics": [{"type": t, "value": v, "name": t.title()} for t, v in metrics]}]}]


def hub_models() -> dict[str, dict]:
    bert_index = _model_index("acme-bert", {"name": "Acme Eval", "type": "acme/eval-set", "split": "test"}, [("accuracy", 0.81), ("f1", 0.79)])
    bert = {
        "_id": "6650aa00acme0000000bert1", "id": "acme/acme-bert", "modelId": "acme/acme-bert", "author": "acme", "sha": SHA["acme/acme-bert"],
        "lastModified": "2026-05-01T00:00:00.000Z", "createdAt": "2026-04-01T00:00:00.000Z", "private": False, "disabled": False, "gated": False,
        "downloads": 120, "likes": 3, "library_name": "transformers", "pipeline_tag": "fill-mask", "mask_token": "[MASK]",
        "tags": ["transformers", "safetensors", "bert", "fill-mask", "en", "dataset:acme/reviews", "arxiv:2601.00001",
                 "base_model:acme/acme-base", "base_model:finetune:acme/acme-base", "license:apache-2.0", "region:us"],
        "cardData": {"license": "apache-2.0", "language": ["en"], "datasets": ["acme/reviews"], "base_model": "acme/acme-base",
                     "base_model_relation": "finetune", "tags": ["exbert", "classification"],
                     "co2_eq_emissions": {"emissions": 830, "source": "CodeCarbon", "training_type": "fine-tuning",
                                          "geographical_location": "Busan, South Korea", "hardware_used": "1 x A100"},
                     "model-index": bert_index},
        "model-index": bert_index,
        "config": {"architectures": ["BertForMaskedLM"], "model_type": "bert", "tokenizer_config": {}},
        "safetensors": {"parameters": {"F32": 4400000}, "total": 4400000},
        "siblings": [{"rfilename": n} for n in (".gitattributes", "README.md", "config.json", "model.safetensors", "tokenizer.json", "vocab.txt")],
        "spaces": [], "usedStorage": 17600000, "widgetData": [{"text": "Paris is the [MASK] of France."}],
        "transformersInfo": {"auto_model": "AutoModelForMaskedLM", "pipeline_tag": "fill-mask", "processor": "AutoTokenizer"},
        "inference": "warm",
    }
    gguf_repo = {
        "_id": "6650aa00acme000000gguf01", "id": "acme/acme-chat-GGUF", "modelId": "acme/acme-chat-GGUF", "author": "acme",
        "sha": SHA["acme/acme-chat-GGUF"], "lastModified": "2026-06-01T00:00:00.000Z", "createdAt": "2026-05-15T00:00:00.000Z",
        "private": False, "disabled": False, "gated": False, "downloads": 40, "likes": 1, "pipeline_tag": "text-generation",
        "tags": ["gguf", "text-generation", "chat", "en", "base_model:acme/acme-tiny", "base_model:quantized:acme/acme-tiny",
                 "license:mit", "endpoints_compatible", "region:us", "conversational"],
        "cardData": {"license": "mit", "language": ["en"], "base_model": "acme/acme-tiny", "base_model_relation": "quantized",
                     "pipeline_tag": "text-generation", "tags": ["chat"], "model_description": "GGUF quantizations of Acme Tiny Chat."},
        "gguf": {"total": 15000000, "architecture": "llama", "context_length": 2048,
                 "chat_template": "{% for m in messages %}{{ m['content'] }}{% endfor %}", "bos_token": "<s>", "eos_token": "</s>"},
        "siblings": [{"rfilename": n} for n in (".gitattributes", "README.md", "acme-chat-Q4_K_M.gguf", "acme-chat-f16.gguf")],
        "spaces": [], "usedStorage": 52000000, "widgetData": [{"text": "Hi, what can you do?"}],
    }
    return {"acme/acme-bert": bert, "acme/acme-chat-GGUF": gguf_repo}


def _dataset(hf_id, card, *, gated=False, description="", paperswithcode_id=None, tags=()):
    out = {"_id": "6650aa00acme" + hf_id.replace("/", "")[-12:].rjust(12, "0"), "id": hf_id, "author": hf_id.split("/")[0], "sha": SHA[hf_id],
           "lastModified": "2026-03-01T00:00:00.000Z", "createdAt": "2026-02-01T00:00:00.000Z", "private": False, "disabled": False,
           "gated": gated, "downloads": 10, "likes": 0, "tags": list(tags), "description": description, "cardData": card, "usedStorage": 1000}
    if paperswithcode_id:
        out["paperswithcode_id"] = paperswithcode_id
    return out


def hub_datasets() -> dict[str, dict]:
    reviews_card = {
        "annotations_creators": ["crowdsourced"], "language_creators": ["found"], "language": ["en", "ko"], "license": ["cc-by-4.0"],
        "multilinguality": ["multilingual"], "size_categories": ["1K<n<10K"], "source_datasets": ["acme/raw-reviews"],
        "task_categories": ["text-classification"], "task_ids": ["sentiment-classification"], "paperswithcode_id": "acme-reviews",
        "pretty_name": "Acme Reviews",
        "dataset_info": {"config_name": "default",
                         "features": [{"name": "text", "dtype": "string"}, {"name": "label", "dtype": {"class_label": {"names": {"0": "neg", "1": "pos"}}}}],
                         "splits": [{"name": "train", "num_bytes": 600000, "num_examples": 4000}, {"name": "test", "num_bytes": 150000, "num_examples": 1000}],
                         "download_size": 500000, "dataset_size": 750000},
        "configs": [{"config_name": "default", "data_files": [{"split": "train", "path": "data/train-*"}, {"split": "test", "path": "data/test-*"}]}],
    }
    return {
        "acme/reviews": _dataset("acme/reviews", reviews_card, gated="auto", description="Acme Reviews: product reviews labelled for sentiment.",
                                 paperswithcode_id="acme-reviews", tags=["task_categories:text-classification", "language:en", "language:ko",
                                 "license:cc-by-4.0", "size_categories:1K<n<10K", "modality:text", "format:parquet"]),
        "acme/acmecorpus": _dataset("acme/acmecorpus", {"license": "mit", "pretty_name": "Acme Corpus", "task_categories": ["fill-mask"],
                                    "language": ["en"], "dataset_info": {"dataset_size": 2000000, "download_size": 1200000}},
                                    tags=["task_categories:fill-mask", "language:en", "license:mit", "modality:text"]),
        "acme/sentiment-eval": _dataset("acme/sentiment-eval", {"license": "other", "license_name": "acme-eval-license",
                                        "license_link": "https://acme.example/licenses/eval", "task_categories": ["text-classification"],
                                        "annotations_creators": ["expert-generated"]}, tags=["modality:text"]),
        "acme/eval-set": _dataset("acme/eval-set", {"license": "apache-2.0", "pretty_name": "Acme Eval Set", "task_categories": ["fill-mask"]},
                                  tags=["modality:text"]),
        "acme/notebook-set": _dataset("acme/notebook-set", {"license": "cc0-1.0", "task_categories": ["image-classification"]},
                                      tags=["modality:image"]),
        "acme/chat-sft": _dataset("acme/chat-sft", {"license": "cc-by-sa-4.0", "pretty_name": "Acme Chat SFT", "task_categories": ["text-generation"],
                                  "language_creators": ["machine-generated"]}, tags=["modality:text"]),
    }


def hub_size() -> dict:
    return {"size": {"dataset": {"dataset": "acme/reviews", "num_bytes_original_files": 500000, "num_bytes_parquet_files": 500000,
                                 "num_bytes_memory": 750000, "num_rows": 5000},
                     "configs": [{"dataset": "acme/reviews", "config": "default", "num_bytes_original_files": 500000, "num_rows": 5000}],
                     "splits": [{"dataset": "acme/reviews", "config": "default", "split": s, "num_rows": n} for s, n in (("train", 4000), ("test", 1000))]},
            "pending": [], "failed": [], "partial": False}


def hub_statistics(n: int) -> dict:
    return {"num_examples": n, "partial": False, "statistics": [
        {"column_name": "label", "column_type": "class_label",
         "column_statistics": {"nan_count": 0, "nan_proportion": 0.0, "no_label_count": 0, "no_label_proportion": 0.0, "n_unique": 2,
                               "frequencies": {"neg": n // 2 - 100, "pos": n // 2 + 100}}},
        {"column_name": "text", "column_type": "string_text",
         "column_statistics": {"nan_count": 0, "nan_proportion": 0.0, "min": 3, "max": 512, "mean": 140.5, "median": 120.0, "std": 60.25,
                               "histogram": {"hist": [n], "bin_edges": [3, 512]}}}]}


def build_hub(root: Path) -> None:
    for hf_id, info in hub_models().items():
        write(root, f"hf_model_{hf_id.replace('/', '_')}.json", dump(info))
    for hf_id, info in hub_datasets().items():
        write(root, f"hf_dataset_{hf_id.replace('/', '_')}.json", dump(info))
    write(root, "hf_size_acme_reviews.json", dump(hub_size()))
    for split, n in (("train", 4000), ("test", 1000)):
        write(root, f"hf_statistics_acme_reviews_default_{split}.json", dump(hub_statistics(n)))


# ── 허구의 OWASP aibom-generator 출력 ────────────────────────────────────────────────────
def _owasp_doc(hf_id, sha, component_extra, card, job):
    owner, name = hf_id.split("/")
    version = sha[:8] if sha else "1.0"
    purl = f"pkg:huggingface/{owner}/{name}@{version}"
    root_ref = f"pkg:generic/OWASP-AIBOM-Generator/{job}@1780000000"
    comp = {"bom-ref": purl, "type": "machine-learning-model", "group": owner, "name": name, "version": version, "purl": purl,
            "description": "No description available", "supplier": {"name": owner},
            "manufacturer": {"name": owner, "url": [f"https://huggingface.co/{owner}"]}, "authors": [{"name": owner}],
            "externalReferences": [{"comment": "Model files", "type": "distribution", "url": f"https://huggingface.co/{hf_id}/tree/main"},
                                   {"comment": "Model repository", "type": "website", "url": f"https://huggingface.co/{hf_id}"}],
            **component_extra, "modelCard": card}
    if sha:
        comp["externalReferences"].insert(1, {"comment": "Specific commit", "type": "vcs", "url": f"https://huggingface.co/{hf_id}/commit/{sha}"})
    return {"$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json", "bomFormat": "CycloneDX", "specVersion": "1.6",
            "serialNumber": "urn:uuid:00000000-0000-4000-8000-0000000000aa", "version": 1,
            "metadata": {"timestamp": "2026-10-13T00:00:00+00:00",
                         "tools": {"components": [{"type": "application", "name": "owasp-aibom-generator", "version": "1.0.2",
                                                   "manufacturer": {"name": "OWASP GenAI Security Project"}}]},
                         "component": {"bom-ref": root_ref, "type": "application", "name": job, "version": "1780000000", "purl": root_ref,
                                       "description": f"Generating SBOM for {hf_id}", "manufacturer": {"name": "OWASP AIBOM Generator"},
                                       "supplier": {"name": "OWASP AIBOM Generator"}}},
            "components": [comp],
            "dependencies": [{"ref": root_ref, "dependsOn": [purl]}, {"ref": purl}]}


def owasp_outputs() -> dict[str, dict]:
    bert_card = {
        "modelParameters": {"task": "fill-mask", "modelArchitecture": "bert",
                            "datasets": [{"type": "dataset", "name": "acme/reviews", "contents": {"url": "https://huggingface.co/datasets/acme/reviews"}}]},
        "considerations": {"technicalLimitations": ["and Biases](#bias-risks-limitations) - [Training](#training)"]},
        "properties": [
            {"name": "genai:aibom:modelcard:hyperparameter", "value": json.dumps({"context_length": 512, "embedding_length": 64, "block_count": 2,
                                                                                  "attention_head_count": 2, "feed_forward_length": 128})},
            {"name": "genai:aibom:modelcard:vocabSize", "value": "1000"},
            {"name": "genai:aibom:modelcard:tokenizerClass", "value": "BertTokenizer"},
            {"name": "genai:aibom:modelcard:contextLength", "value": "512"},
            {"name": "genai:aibom:trainingDataAvailable", "value": "true"},
            {"name": "genai:aibom:trainingDataStatus", "value": "Training datasets verified: Dataset(s) exist and are accessible on Hugging Face Hub."},
            {"name": "owasp:aibom:distribution:modelFileSize", "value": "17600000"},
            {"name": "owasp:aibom:distribution:runtimeRequirement", "value": "python"},
            {"name": "serialNumber", "value": "urn:uuid:acme-acme-bert"},
            {"name": "safetyRiskAssessment", "value": "Even if the training data is neutral, this model can have biased predictions: ```python"},
            {"name": "energyConsumption", "value": "830"},
            {"name": "safetensors_total_parameters", "value": "4400000"},
        ],
    }
    bert = _owasp_doc("acme/acme-bert", SHA["acme/acme-bert"],
                      {"licenses": [{"license": {"id": "Apache-2.0"}}], "properties": [{"name": "model_type", "value": "bert"}]},
                      bert_card, "job-2026-10-13-00:00:01")
    bert["components"][0]["externalReferences"][2:2] = [
        {"comment": "ArXiv Paper", "type": "documentation", "url": "https://arxiv.org/abs/2601.00001"},
        {"comment": "Training dataset: acme/reviews", "type": "distribution", "url": "https://huggingface.co/datasets/acme/reviews"}]
    # GGUF 저장소: OWASP 가 첫 GGUF 파일의 헤더를 못 읽은 경우다. 헤더에서 오는 값(하이퍼파라미터 묶음, vocabSize, tokenizerClass,
    # contextLength, 양자화, model_type)이 모두 없고 modelArchitecture 는 기본값이다. 파일 목록에서 오는 runtimeRequirement·modelFileSize
    # 는 남는다. 그래서 inputs maxSize 는 aibom-cli 가 Hub API 의 gguf.context_length 로 채운다 (parameterCount 는 gguf.total).
    gguf_card = {
        "modelParameters": {"task": "text-generation", "modelArchitecture": "transformer", "inputs": [{"format": "string"}], "outputs": [{"format": "string"}]},
        "properties": [
            {"name": "genai:aibom:trainingDataAvailable", "value": "false"},
            {"name": "genai:aibom:trainingDataWarning", "value": "Training data information is missing or not documented. This limits transparency and auditability of the model."},
            {"name": "owasp:aibom:distribution:modelFileSize", "value": "52000000"},
            {"name": "owasp:aibom:distribution:runtimeRequirement", "value": "llm-stack"},
            {"name": "serialNumber", "value": "urn:uuid:acme-acme-chat-GGUF"},
        ],
    }
    gguf_repo = _owasp_doc("acme/acme-chat-GGUF", SHA["acme/acme-chat-GGUF"],
                           {"licenses": [{"license": {"id": "MIT"}}]}, gguf_card, "job-2026-10-13-00:00:02")
    # 비공개 저장소: 실제 OWASP 는 실패하지 않고 기본값으로 채운 BOM 을 낸다 (task text-generation, modelArchitecture transformer …)
    private = _owasp_doc("acme/acme-private", None, {}, {
        "modelParameters": {"task": "text-generation", "modelArchitecture": "transformer", "inputs": [{"format": "string"}], "outputs": [{"format": "string"}]},
        "properties": [{"name": "genai:aibom:trainingDataAvailable", "value": "false"},
                       {"name": "genai:aibom:trainingDataWarning", "value": "Training data information is missing or not documented. This limits transparency and auditability of the model."},
                       {"name": "serialNumber", "value": "urn:uuid:acme-acme-private"}],
    }, "job-2026-10-13-00:00:03")
    return {"acme-bert": bert, "acme-chat-GGUF": gguf_repo, "acme-private": private}


def build_owasp(root: Path) -> None:
    for name, doc in owasp_outputs().items():
        write(root, f"{name}.cdx.json", dump(doc))


def build(base: Path = HERE) -> None:
    """base 아래 네 폴더를 지우고 다시 만든다."""
    for name in ("project", "rootfs", "hf_api", "owasp"):
        shutil.rmtree(base / name, ignore_errors=True)
    project = base / "project"
    build_models(project)
    build_data(project)
    build_software(project)
    build_rootfs(base / "rootfs")
    build_hub(base / "hf_api")
    build_owasp(base / "owasp")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE)
