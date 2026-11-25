# Chromium C++ SDK

고정한 Chromium 커밋에서 C++ 라이브러리와 외부 CMake 프로젝트용 SDK를 빌드합니다.

| 프로젝트 | 빌드 대상 | 플랫폼 |
|---|---|---|
| [base](base/README.md) | `//base:base`, 정적·동적 SDK | Windows x64, Linux x64, macOS arm64 |
| [net](net/README.md) | `//net:net`, 동적 SDK | Windows x64 |

`source.lock.json`과 `tools.lock.json`은 두 프로젝트가 공유합니다. `net/source-extra.json`은 같은 Chromium 커밋에서 네트워크 스택에 필요한 소스를 추가로 선택합니다. 빌드 명령은 저장소 루트에서 실행합니다.
