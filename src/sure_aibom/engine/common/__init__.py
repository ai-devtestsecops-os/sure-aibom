"""engine 바로 아래 파일들(syft.py, model.py 등)이 가져다 쓰는 것을 모은다. 그 파일들은 서로 가져다 쓰지 않고, 같이 쓰는 것은 여기에 둔다.

    proc.py              다른 프로그램 실행
    hub.py               Hugging Face 허브 요청
    aibom_generator.py   OWASP aibom-generator 실행
    component.py         컴포넌트를 알아보고 합치는 상수와 짧은 함수
    files.py             스캔 대상의 파일을 훑거나 찾는 함수
    host.py              이 머신의 CPU 종류
    licenses.py          라이선스 값을 CycloneDX licenses[] 항목으로
"""
