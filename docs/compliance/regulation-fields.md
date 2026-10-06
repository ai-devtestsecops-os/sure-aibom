# properties 키

규제 값을 넣는 두 방식 가운데 `--spec 1.7` (기본) 이 고르는 쪽이다. 새 필드를 만들지 않고 기존 `properties` 배열에 `aibom:` 으로
시작하는 키로 값을 적어, 공식 CycloneDX 1.7 스키마를 그대로 통과한다. 다른 방식인 `--spec v0.6` 은 같은 값을 전용 필드에 적는다.
그쪽 구조는 [AI-BOM v0.6 필드](aibom-v0.6.md)에 있다.

아래는 AI-BOM v0.6 이 규제 대응으로 더한 필드 하나하나에 대응하는 키와 설명, 허용값이다. aibom-cli 는 `--spec 1.7` 로 낼 때 이 키 그대로 properties 에 적는다.

규제가 요구하는 값 가운데 CycloneDX 1.7 · SPDX 3.0.1 어느 쪽에도 담을 자리가 없는 것을
두 표준이 각자 마련해 둔 **확장 지점**에 같은 이름·값으로 싣기 위한 규격이다.

---

## 1. 자리

| | CycloneDX 1.7 | SPDX 3.0.1 |
|---|---|---|
| 모델 | `component.modelCard.properties` | `ai_AIPackage.extension` |
| 데이터셋 | `component.properties  (type=data)` | `dataset_DatasetPackage.extension` |

CycloneDX 의 `componentData` 에는 properties 슬롯이 없어 **데이터셋 값만 한 계층 위**로
올라간다.

## 2. Key 규칙

값은 **전부 문자열이다.**

여러 값을 담는 키는 **끝에 몇 번째인지를 붙여** 하나씩 적는다. 항목이 여러 칸으로 이루어진
키는 그 뒤에 칸 이름을 붙인다. 아래 표의 `<i>` 가 그 자리다. syft 의 `syft:location:0:path`
와 같은 관례다.

```jsonc
{ "name": "aibom:model:designChoices:0",        "value": "임베딩과 출력 투영의 가중치를 분리" }
{ "name": "aibom:model:designChoices:1",        "value": "어텐션 QKV 층에 bias 추가" }
{ "name": "aibom:model:hyperparameters:0:name",  "value": "num_hidden_layers" }
{ "name": "aibom:model:hyperparameters:0:value", "value": "32" }
```

**허용값이 적힌 키는 그 목록 중 하나만 쓴다.**

## 3. 모델

| Key | 설명 | 허용값 |
|---|---|---|
| `aibom:model:task` | 입력 및/또는 출력에 직접 영향을 준다. 예: 분류, 회귀, 군집화 등. |  |
| `aibom:model:architectureFamily` | 트랜스포머 네트워크, 합성곱신경망(CNN), 잔차신경망(ResNet), LSTM 신경망 등 모델 아키텍처 계열. |  |
| `aibom:model:modelArchitecture` | GPT-1, ResNet-50, YOLOv3 등 모델의 구체적 아키텍처. |  |
| `aibom:model:inputs:<i>:format` | 이 입력의 데이터 양식. |  |
| `aibom:model:inputs:<i>:maxSize` | 이 입력의 최대 크기(예: 컨텍스트 윈도우 길이). |  |
| `aibom:model:outputs:<i>:format` | 이 출력의 데이터 양식. |  |
| `aibom:model:outputs:<i>:maxSize` | 이 출력의 최대 크기(예: 컨텍스트 윈도우 길이). |  |
| `aibom:model:hyperparameters:<i>:name` | 모델을 구축하는 데 사용한 하이퍼파라미터(예: 학습률, 배치 크기, 층 수). |  |
| `aibom:model:hyperparameters:<i>:value` | 하이퍼파라미터의 값. |  |
| `aibom:model:parameterCount` | 모델이 가진 파라미터의 개수. |  |
| `aibom:model:trainingTechniques:<i>` | 이 모델을 만드는 데 사용한 학습 기법. 전이학습, 파인튜닝, 능동학습, 지속학습, 인스트럭션 튜닝, 사람 피드백 기반 강화학습(RLHF) 등. |  |
| `aibom:model:designChoices:<i>` | 이 모델에 대해 내린 주요 설계 결정과 그 근거·가정. |  |
| `aibom:model:optimizationTarget` | 이 모델이 최적화하도록 설계된 대상. |  |
| `aibom:model:trainingCompute` | 이 모델을 훈련하는 데 쓴 연산자원(예: 부동소수점 연산 횟수). |  |
| `aibom:model:trainingTime` | 이 모델을 훈련하는 데 걸린 시간. |  |
| `aibom:model:performanceMetrics:<i>:slice` | 이 지표가 계산된 슬라이스(slice)의 이름. 기본적으로 이 지표는 슬라이스되지 않은 것으로 가정한다. |  |
| `aibom:model:performanceMetrics:<i>:decisionThreshold` | 이 지표를 계산하는 데 쓴 임계값. |  |
| `aibom:model:users:<i>` | 모델의 의도된 사용자는 누구인가? |  |
| `aibom:model:useCases:<i>` | 모델의 의도된 유스케이스는 무엇인가? |  |
| `aibom:model:ethicalConsiderations:<i>:name` | 이 모델의 적용에 수반되는 윤리적 위험은 무엇인가? |  |
| `aibom:model:ethicalConsiderations:<i>:mitigationStrategy` | 이 위험을 다루기 위해 사용된 전략. |  |
| `aibom:model:fairnessAssessments:<i>:groupAtRisk` | 모델에 의해 체계적으로 불이익을 받을 위험이 있는 집단 또는 개인. |  |
| `aibom:model:fairnessAssessments:<i>:benefits` | 식별된 집단에 대한 기대 이익. |  |
| `aibom:model:fairnessAssessments:<i>:harms` | 식별된 집단에 대한 기대 피해. |  |
| `aibom:model:limitationIdentificationMethods:<i>` | 이 모델의 한계를 식별하는 데 사용한 방법. |  |
| `aibom:model:explainabilityMethods:<i>` | 모델의 결과를 설명하는 데 쓸 수 있는 방법. |  |
| `aibom:model:sensitivePersonalInformation` | 민감 개인정보가 모델 학습에 쓰이거나 추론에 쓰일 수 있는지. | yes, no, unknown |
| `aibom:model:safetyRiskAssessment` | AI 시스템의 일반 안전 위험 평가 결과. | serious, high, medium, low |
| `aibom:model:technicalRequirements:<i>` | 이 모델을 소프트웨어 안에서 돌리는 데 필요한 것(하드웨어, 연산 자원, 라이브러리, 운영체제)과, 모델 밖의 하드웨어·소프트웨어(다른 인공지능시스템을 포함한다)와 맞물리는 방식. |  |

## 4. 데이터셋

| Key | 설명 | 허용값 |
|---|---|---|
| `aibom:dataset:availability` | 이 데이터셋의 가용성. | clickthrough, direct-download, query, registration, scraping-script |
| `aibom:dataset:collectionProcess` | 이 데이터셋을 수집한 과정(예: 긁어 온 소스, 사용한 인터뷰 프로토콜). |  |
| `aibom:dataset:preprocessing:<i>` | 이 데이터가 지금 형태가 되기까지 적용한 전처리 단계(예: 표준화, 정규화, 중복 제거, 토큰화). |  |
| `aibom:dataset:originalCollectionPurpose` | 개인데이터의 경우, 그 수집의 원래 목적. |  |
| `aibom:dataset:designChoices:<i>` | 이 데이터셋을 구성하면서 내린 설계 결정. |  |
| `aibom:dataset:representationAssumptions:<i>` | 이 데이터가 측정·표상하도록 되어 있는 정보에 관한 가정. |  |
| `aibom:dataset:knownBias:<i>:name` | 이 데이터셋이 포함하는 것으로 알려진 편향. |  |
| `aibom:dataset:knownBias:<i>:detectionMethod` | 이 편향을 찾아낸 방법. |  |
| `aibom:dataset:knownBias:<i>:mitigationStrategy` | 이 편향을 예방·완화하기 위해 한 조치. |  |
| `aibom:dataset:knownGaps:<i>:name` | 이 데이터셋에 있는 것으로 알려진 데이터 공백이나 결함. |  |
| `aibom:dataset:knownGaps:<i>:mitigationStrategy` | 그 공백이나 결함을 해결할 수 있는 방법. |  |
| `aibom:dataset:noise` | 이 데이터셋에서 노이즈가 있을 수 있는 요소. |  |
| `aibom:dataset:anonymizationMethods:<i>` | 데이터셋 또는 그 안의 필드를 익명화하는 데 사용한 방법. |  |
| `aibom:dataset:statistics:<i>:type` | 통계량의 종류. 평균, 분산, 중앙값, 최빈값, 범위, 왜도 등. |  |
| `aibom:dataset:statistics:<i>:value` | 통계량의 값. |  |
| `aibom:dataset:size` | 바이트로 잰 데이터셋의 크기. |  |
| `aibom:dataset:modality:<i>` | 데이터셋에 담긴 데이터의 모달리티. | image, text, audio, video, sensor, timeseries, timestamp, structured, categorical, graph, syntactic, numeric, other |
| `aibom:dataset:updateMechanism` | 이 데이터셋을 갱신하는 방식. |  |
| `aibom:dataset:intendedUse` | 이 데이터셋의 의도된 용도. |  |
| `aibom:dataset:provenance:<i>` | 이 데이터셋의 출처. |  |
