# Chromium Base SDK

[![Chromium 버전 159.0.8128.0](https://img.shields.io/badge/Chromium-159.0.8128.0-4285F4)](https://github.com/chromium/chromium/blob/1633b610f5957ddd13a26fe87628c0768067e740/chrome/VERSION)
[![Chromium 커밋 1633b610f595](https://img.shields.io/badge/commit-1633b610f595-555555)](https://github.com/chromium/chromium/commit/1633b610f5957ddd13a26fe87628c0768067e740)

Chromium의 C++ 라이브러리 `base`와 필요한 의존성만 추출해 정적·동적 라이브러리로 빌드합니다. 외부 LLVM과 Chromium 제공 LLVM은 같은 소스를 사용합니다.

## 플랫폼별 빌드

| 플랫폼 | 지원 범위 |
|---|---|
| [Windows x64](docs/build/windows.md) | Release 정적·동적 빌드, SDK 내보내기, CMake 샘플 실행 검증 |
| [Linux x64](docs/build/linux.md) | Ubuntu 24.04 정적 SDK 및 동적 SDK (`libbase.so`) |
| [macOS arm64](docs/build/macos.md) | Apple Silicon 정적 SDK 및 동적 SDK (`libbase.dylib`) |

릴리스 태그는 빌드한 Chromium의 `chrome/VERSION`을 따릅니다. 예를 들어 `159.0.8128.0`의 SDK 태그는 `v159.0.8128.0`입니다.
[Chromium Base SDK release](../.github/workflows/static-sdk.yml)는 세 플랫폼에서 정적·동적 SDK를 각각 빌드합니다. 동적 SDK ZIP에는 플랫폼별 공유 라이브러리와 그 의존성, 헤더, CMake 설정이 포함됩니다. Windows ZIP에는 DLL 연결용 import library도 포함됩니다.

수동 실행 시 **Chromium 버전에 맞춰 정식 SDK 릴리스 게시**를 선택하면 여섯 SDK의 샘플 검증을 통과한 뒤 ZIP 6개와 `SHA256SUMS`를 게시합니다. 기본 수동 실행은 Actions 아티팩트만 생성합니다. 버전과 일치하는 태그를 직접 푸시해도 릴리스가 게시됩니다.
정식 SDK를 게시할 때마다 해당 릴리스가 [최신 SDK 다운로드](https://github.com/pryaoh/chromium_sdk/releases/latest)로 지정됩니다.

SDK를 CMake 프로젝트에 연결하는 예제는 [hello_base 샘플](samples/README.md)을 참고하세요. 소스 추출 방식과 도구 구성은 [설계 문서](docs/toolchain-design.md)에 있습니다.

## 라이선스

자체 도구에는 [프로젝트 라이선스](../LICENSE)가 적용됩니다. Chromium과 제3자 코드는 각각의 원본 라이선스를 따릅니다.
