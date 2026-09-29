"""project 픽스처의 모델 파일을 HuggingFace 에서 받는다. 받은 파일은 저장소에 그대로 커밋되어 있으므로,
갱신하거나 바이트가 맞는지 확인하고 싶을 때만 돌린다.

    python tests/data/fetch_model_files.py            # 없는 것만 받는다
    python tests/data/fetch_model_files.py --force    # 다시 받아 덮어쓴다

전부 실제 파일이다. 손으로 지어낸 바이트가 아니라 허브에 올라간 것을 그대로 쓴다. 개정판(sha)을 박아 두었으므로
저장소가 갱신되어도 같은 바이트를 받는다. 셋 다 도구들이 시험용으로 쓰는 아주 작은 모델이다 (합쳐서 1.6 MB).

    tiny-random-gpt2   가중치가 난수인 GPT-2. config.json 과 model.safetensors 가 진짜 HuggingFace 형식이다.
    stories260K.gguf   TinyStories 로 학습한 26만 파라미터 Llama. llama.cpp 가 테스트에 쓴다.
    tiny-gpt2-lora     위 tiny-random-gpt2 에 붙는 PEFT LoRA 어댑터.

models/tiny-random-gpt2/README.md 는 받은 것이 아니라 픽스처로 쓴 모델 카드다 (그 저장소에는 카드가 없다).
앞머리의 license·base_model·datasets 는 cdxgen 이 모델 카드에서 무엇을 읽는지 보려고 적은 값이다.

이 스크립트는 project/ 밖에 둔다 (안에 두면 스캔 대상이 된다).
"""
import sys
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).parent / "project"
BASE = "https://huggingface.co"

# (저장소, 개정판 sha, 저장소 안 경로, project 안 저장 경로)
FILES: tuple[tuple[str, str, str, str], ...] = (
    ("hf-internal-testing/tiny-random-gpt2", "71034c5d8bde858ff824298bdedc65515b97d2b9",
     "config.json", "models/tiny-random-gpt2/config.json"),
    ("hf-internal-testing/tiny-random-gpt2", "71034c5d8bde858ff824298bdedc65515b97d2b9",
     "model.safetensors", "models/tiny-random-gpt2/model.safetensors"),
    ("ggml-org/models", "499bc8821c6b12b4e53c5bffcb21ec206f212d81",
     "tinyllamas/stories260K.gguf", "models/stories260K.gguf"),
    ("peft-internal-testing/tiny_GPT2ForTokenClassification-lora", "c32ca358e1deddf2d3e755faef6d22610d7b49ae",
     "adapter_config.json", "models/tiny-gpt2-lora/adapter_config.json"),
    ("peft-internal-testing/tiny_GPT2ForTokenClassification-lora", "c32ca358e1deddf2d3e755faef6d22610d7b49ae",
     "adapter_model.bin", "models/tiny-gpt2-lora/adapter_model.bin"),
)


def main(force: bool) -> None:
    for repo, sha, remote, local in FILES:
        target = PROJECT / local
        if target.exists() and not force:
            print(f"{local}  이미 있음 ({target.stat().st_size / 1024:.1f} KB)")
            continue
        url = f"{BASE}/{repo}/resolve/{sha}/{remote}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        target.write_bytes(data)
        print(f"{local}  {len(data) / 1024:.1f} KB  ← {repo}@{sha[:8]}/{remote}")


if __name__ == "__main__":
    main("--force" in sys.argv[1:])
