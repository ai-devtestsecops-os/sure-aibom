"""engine 의 단계 파일들이 가져다 쓰는 것을 모은다. 단계 파일(syft.py, model.py 등)은 서로 가져다 쓰지 않고 여기 것만 쓴다.

    proc.py              다른 프로그램 실행
    hub.py               Hugging Face 허브 요청
    aibom_generator.py   OWASP aibom-generator 실행
    facts.py             CycloneDX 에 자리가 없어 메모리로만 들고 가는 값
    component.py         컴포넌트를 알아보고 합치는 상수와 짧은 함수
"""
