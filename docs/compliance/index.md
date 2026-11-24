# 규제 준수

EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하지만 CycloneDX 1.7 과 SPDX 3.0.1 에 담을 자리가 없는 값을 BOM 에 어떻게 담는지 설명한다.
값을 적는 방식은 둘이고 `--spec` 으로 고른다. 같은 값을 다른 자리에 적는 것이라 필드마다 v0.6 필드 이름과 확장 필드 키가 짝으로 있다.
출력 형식(`--format`)이 CycloneDX 든 SPDX 든 같다.

- **[AI-BOM v0.6 필드](aibom-v0.6.md)**: `--spec v0.6` 방식. 규제 요구 필드를 CycloneDX 1.7 과 SPDX 3.0.1 에 더한 스키마와 그 구조,
  sure-aibom 이 채우는 필드를 설명한다.
- **[확장 필드](regulation-fields.md)**: `--spec 1.7`(CycloneDX)과 `--spec 3.0.1`(SPDX) 방식. 같은 값을 CycloneDX 의 `properties` 배열이나 SPDX 의 `CdxPropertiesExtension` 에 적을 때 쓰는 키와 설명, 허용값을 정리한다.
