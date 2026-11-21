# macOS arm64 정적 SDK

Apple Silicon에서 Xcode와 macOS SDK, Python 3.12, Git, curl, Ninja, CMake 3.25 이상이 필요합니다. CI는 macOS 26 러너를 사용합니다. 저장소 루트에서 실행하세요.

```sh
python3 scripts/build_posix_sdk.py
python3 scripts/package_static_sdk.py macos-arm64
```

첫 명령은 고정된 Chromium 소스와 해당 버전의 Clang·Rust를 받아 Release로 빌드하고 헤더와 정적 라이브러리를 `out/static-sdk`에 설치합니다. 새 작업 디렉터리에서 실행하세요. 두 번째 명령은 SDK를 다른 경로에 풀고 CMake로 `hello_base`를 빌드·실행한 뒤 검증된 ZIP을 `out/release/`에 저장합니다.

소비 프로젝트에서는 SDK 경로를 `CMAKE_PREFIX_PATH`로, SDK 빌드에 사용한 Chromium `clang++`를 `CMAKE_CXX_COMPILER`로 지정하고 `ChromiumBase::base`에 연결합니다.

[릴리스 워크플로](../../.github/workflows/static-sdk.yml) · [CMake 샘플](../../samples/hello_base/CMakeLists.txt)
