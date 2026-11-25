# macOS arm64 SDK

Apple Silicon에서 Xcode와 macOS SDK, Python 3.12, Git, curl, Ninja, CMake 3.25 이상이 필요합니다. CI는 macOS 26 러너를 사용합니다. 저장소 루트에서 실행하세요.

```sh
linkage=shared  # 정적 SDK는 static
python3 base/scripts/build_posix_sdk.py --linkage "$linkage"
python3 base/scripts/package_sdk.py macos-arm64 --linkage "$linkage"
```

각 빌드 유형은 새 작업 디렉터리에서 실행하세요. 동적 빌드는 `out/shared-sdk/lib/`에 `libbase.dylib`와 필요한 공유 라이브러리를 함께 설치합니다. 정적 빌드의 출력은 `out/static-sdk/`입니다. 패키징 명령은 ZIP을 다른 경로에 풀어 CMake 샘플을 빌드·실행하고, 동적 빌드에서는 샘플이 `libbase.dylib`에 연결됐는지도 확인합니다. 검증된 ZIP은 `out/release/`에 저장됩니다.

소비 프로젝트에서는 SDK 경로를 `CMAKE_PREFIX_PATH`로, SDK 빌드에 사용한 Chromium `clang++`를 `CMAKE_CXX_COMPILER`로 지정하고 `ChromiumBase::base`에 연결합니다.

[릴리스 워크플로](../../../.github/workflows/static-sdk.yml) · [CMake 샘플](../../samples/hello_base/CMakeLists.txt)
