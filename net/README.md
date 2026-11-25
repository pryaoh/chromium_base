# Chromium net SDK

Windows x64 Release용 Chromium 네트워크 스택을 빌드하고 CMake 패키지 `ChromiumNet::net`으로 내보냅니다. 소스 버전, LLVM, Rust와 Windows SDK 요구 사항은 [base Windows 빌드 문서](../base/docs/build/windows.md)를 따릅니다.

## 빌드

저장소 루트의 PowerShell에서 실행합니다.

```powershell
python base/scripts/sync_tools.py gn ninja rust-toolchain chromium-llvm
python net/sync_source.py
python net/build.py configure
python net/build.py build --jobs 6
python net/export_sdk.py --destination out/net-sdk
```

소스는 `vendor/chromium-net`, 빌드 출력은 그 아래 `out/sh`입니다. 이 소스에는 `//base:base`와 `//net:net`이 함께 들어 있습니다. 같은 구성에서 먼저 base만 빌드하려면 configure 후 다음 명령을 실행합니다. 이후 net 빌드가 이 출력 디렉터리를 그대로 사용합니다.

```powershell
python base/scripts/chromium_base.py build --source vendor/chromium-net --output-dir vendor/chromium-net/out/sh --toolchain chromium --linkage shared
```

기본 내보내기는 같은 빌드에서 만든 ChromiumBase와 ChromiumNet을 한 SDK에 담습니다. 이미 배포한 Windows 공유 base SDK와 함께 쓰려면 내보낼 때 `--base-sdk <base SDK 폴더>`를 지정합니다. 이 모드에서는 링크 입력과 런타임의 호환성을 확인하며, 소비자의 `CMAKE_PREFIX_PATH`에 두 SDK 위치가 모두 필요합니다.

`ChromiumNet::net`은 URL 처리 전에 `base::i18n::InitializeICU()`를 호출할 수 있도록 `//base:i18n`도 연결합니다. `chromium_net_deploy_runtime`이 ICU 데이터 파일 `icudtl.dat`와 필요한 DLL을 실행 파일 옆에 복사합니다.

## 이미 빌드한 base 출력 재사용

기존 `vendor/chromium/out/sh`에 Chromium LLVM으로 빌드한 base가 있으면, 위의 소스 동기화 직후 다음 순서로 진행할 수 있습니다. 두 트리를 사용하는 빌드를 종료하고, 아직 빌드하지 않은 `vendor/chromium-net`을 지정합니다.

```powershell
python net/enable_in_base.py
python net/build.py configure --source vendor/chromium
python net/build.py build --source vendor/chromium --jobs 6
python net/export_sdk.py --source vendor/chromium --destination out/net-sdk
```

전환 도구가 커밋·파일 해시·툴체인을 대조하고 기존 빌드 출력의 위치와 공통 소스의 수정 시각을 보존합니다. Ninja가 이 정보를 사용해 재컴파일 대상을 결정합니다. 기존 소스는 `vendor/chromium.base-backup`에 보관합니다. 같은 base 소스로 만든 정적·공유 빌드는 기존 툴체인으로 다시 configure할 수 있으며, 전환이 중단되면 `python net/enable_in_base.py --recover`로 소스와 빌드별 매니페스트를 복구할 수 있습니다.

## 외부 CMake 프로젝트에서 SSE 스트리밍 확인

```powershell
$sdkPath = (Resolve-Path out/net-sdk).Path
cmake -S net/samples/sse_client -B out/net-sample -G Ninja "-DCMAKE_PREFIX_PATH=$sdkPath" "-DCMAKE_TOOLCHAIN_FILE=$sdkPath/lib/cmake/ChromiumBase/chromium-base-toolchain.cmake" "-DCHROMIUM_BASE_LLVM_ROOT=$PWD/.tools/chromium-llvm" -DCMAKE_BUILD_TYPE=Release
cmake --build out/net-sample
python net/tests/verify_stream.py out/net-sample/sse_client.exe
```

Windows 샘플 빌드는 Visual Studio x64 Developer PowerShell에서 실행합니다. 샘플은 `net::URLRequest`로 응답을 읽고 SSE 이벤트의 `data`를 출력합니다. 검증 서버는 첫 이벤트가 표준 출력에 도착한 뒤 두 번째 이벤트를 전송해, 연결이 열린 동안 데이터가 처리되는지 확인합니다.
