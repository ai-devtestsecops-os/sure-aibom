# 규제 준수

EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 값 가운데 CycloneDX 1.7 과 SPDX 3.0.1 에 담을 자리가 없는 것이 있다.
aibom-cli 는 이 값을 두 방식 중 하나로 BOM 에 적는다. `--spec` 이 방식을 고른다.

| `--spec` | 방식 | 어디에 적나 | 검증 스키마 | 고르는 기준 |
|---|---|---|---|---|
| `v0.6` | [AI-BOM v0.6 필드](aibom-v0.6.md) | AI-BOM v0.6 이 기존 객체 안에 더한 전용 필드 | AI-BOM v0.6 (CycloneDX) | 값의 타입과 허용값을 스키마로 묶고 싶을 때 |
| `1.7` (기본) | [properties 키](regulation-fields.md) | 기존 `properties` 배열에 `aibom:` 키로 | 공식 CycloneDX 1.7 | 기존 도구가 그대로 읽어야 할 때 |

두 방식은 같은 값을 다른 자리에 적는 것이라, 필드 하나마다 v0.6 필드 이름과 properties 키가 짝으로 있다.
어느 필드가 어디에 붙고 다른 표준의 어느 필드와 대응하는지는 [필드 탐색기](field-mapping.md)에서 한 화면으로 본다.

| 문서 | 내용 |
|---|---|
| [AI-BOM v0.6 필드](aibom-v0.6.md) | `--spec v0.6`: 규제 요구 필드를 더한 스키마와 그 구조 |
| [properties 키](regulation-fields.md) | `--spec 1.7`: properties 로 낼 때 쓰는 키와 설명, 허용값 |
| [필드 탐색기](field-mapping.md) | 필드가 BOM 의 어디에 들어가는지, CycloneDX · SPDX 대응, 규제 조항과 필드를 트리로 찾아본다 |
