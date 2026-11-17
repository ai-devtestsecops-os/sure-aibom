"""sure-aibom 이 직접 만든 예외. external, engine, service 가 같이 쓴다. service 는 둘 다 단계 실패로 받아 단계 줄에 찍는다."""


class RunnerError(RuntimeError):
    """외부 프로그램 실패. 프로그램이 없거나, 시간을 넘기거나, 0 이 아닌 코드로 끝나거나, 출력이 없으면 external 이 던진다."""


class ImageExtractionError(RuntimeError):
    """이미지 tar 를 풀지 못함. 이미지 tar 가 아니거나, 목차나 레이어가 빠졌거나, zstd 레이어처럼 지원하지 않으면 engine/extract_image.py 가 던진다."""
