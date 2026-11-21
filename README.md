# chromium_base

[![Chromium 버전 159.0.8128.0](https://img.shields.io/badge/Chromium-159.0.8128.0-4285F4)](https://github.com/chromium/chromium/blob/1633b610f5957ddd13a26fe87628c0768067e740/chrome/VERSION)
[![Chromium 커밋 1633b610f595](https://img.shields.io/badge/commit-1633b610f595-555555)](https://github.com/chromium/chromium/commit/1633b610f5957ddd13a26fe87628c0768067e740)

Chromium의 C++ 라이브러리 `base`와 필요한 의존성만 추출해 정적·동적 라이브러리로 빌드합니다. 외부 LLVM과 Chromium 제공 LLVM은 같은 소스를 사용합니다.

## 플랫폼별 빌드

| 플랫폼 | 지원 범위 |
|---|---|
| [Windows x64](docs/build/windows.md) | Release 정적·동적 빌드, SDK 내보내기, CMake 샘플 실행 검증 |
| [Linux](docs/build/linux.md) | Ubuntu 24.04 x64 정적 SDK 및 CMake 샘플 실행 검증 |
| [macOS](docs/build/macos.md) | arm64 정적 SDK 워크플로 구성, 네이티브 실행 검증 대기 |

[Static SDK release](.github/workflows/static-sdk.yml)를 수동 실행하면 플랫폼별 ZIP을 Actions에서 받을 수 있습니다. `v*` 태그를 푸시하면 세 플랫폼 모두 샘플 검증을 통과한 뒤 ZIP과 `SHA256SUMS`를 GitHub Release에 게시합니다.

SDK를 CMake 프로젝트에 연결하는 예제는 [hello_base 샘플](samples/README.md)을 참고하세요. 소스 추출 방식과 도구 구성은 [설계 문서](docs/toolchain-design.md)에 있습니다.

## 라이선스

자체 도구에는 [프로젝트 라이선스](LICENSE)가 적용됩니다. Chromium과 제3자 코드는 각각의 원본 라이선스를 따릅니다.
