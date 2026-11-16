"""sure-aibom 이 내보내는 형식과 spec. 인자 선택지(cli.py), 기본값과 문구(controller), 규제 필드 형태(service)가 같이 쓴다."""

# scan --format 과 --spec. 형식마다 spec 둘이고 첫 값이 기본이다. v0.6 은 두 형식에 다 있다 (AI-BOM v0.6 은 CycloneDX 판과 SPDX 판이 있다)
FORMATS = ("cyclonedx", "spdx")
SPEC_BY_FORMAT = {"cyclonedx": ("1.7", "v0.6"), "spdx": ("3.0.1", "v0.6")}
SPECS = ("1.7", "v0.6", "3.0.1")                           # --spec 의 선택지 (scan · validate)
# 규제 필드를 넣는 형태. 1.7 은 표준 properties 라 1.7·v0.6 스키마 모두에 맞고, v0.6 은 v0.6 스키마에만 맞는다.
# SPDX 는 v0.6 형(typed)으로 만든 뒤 바꾼다 — 3.0.1 이면 변환기가 v0.6 이 더한 값을 확장에 넣는다
FORM_BY_SPEC = {"1.7": "properties", "v0.6": "typed", "3.0.1": "typed"}
FORMAT_NAME = {("cyclonedx", "1.7"): "CycloneDX 1.7", ("cyclonedx", "v0.6"): "AI-BOM v0.6 (CycloneDX)",
               ("spdx", "3.0.1"): "SPDX 3.0.1", ("spdx", "v0.6"): "AI-BOM v0.6 (SPDX)"}
