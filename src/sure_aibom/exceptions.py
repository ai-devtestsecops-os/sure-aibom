"""sure-aibom 이 직접 만든 예외. external, engine, service 가 같이 쓴다."""


class RunnerError(RuntimeError):
    """단계 실패. 외부 도구가 실패하거나(external) 이미지 tar 를 풀지 못하면(engine) 던지고, service 가 받아 단계 줄에 찍는다."""
