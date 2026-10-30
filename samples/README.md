# Chromium base samples

각 샘플은 별도 디렉터리와 실행 파일을 갖는 CMake 프로젝트입니다.
내보낸 SDK의 `ChromiumBase::base`만 연결하며 Chromium 소스를 직접 참조하지 않습니다.

| 샘플 | 내용 |
|---|---|
| [hello_base](hello_base/main.cc) | 명령행 인자, 문자열 조합·ASCII 대문자 변환, JSON 출력 |

## 전체 샘플 빌드

현재 검증 범위는 **Windows x64 / static·shared Release / Chromium LLVM** 및
**외부 LLVM 24 개발 빌드 / shared Release**입니다. 외부 LLVM 정적 구성은 검증 중입니다.
SDK를 빌드했던 것과 동일한 LLVM, Visual Studio C++ 도구, Windows SDK 및 CMake 3.25 이상이 필요합니다.
**x64 Visual Studio Developer PowerShell**에서 저장소 루트를 기준으로 실행하세요.
`cmake`는 PATH에 있어야 하며 SDK를 다른 위치에 두었다면 `$sdk`를 변경합니다.

```powershell
$sdk = (Resolve-Path 'out/sdk/relocated sdk/windows-x64-chromium-static-release').Path
$llvm = (Resolve-Path '.tools/chromium-llvm').Path
$ninja = (Resolve-Path '.tools/ninja/ninja.exe').Path

cmake -S samples -B out/samples -G Ninja `
  "-DCMAKE_MAKE_PROGRAM=$ninja" `
  "-DCMAKE_PREFIX_PATH=$sdk" `
  "-DCMAKE_TOOLCHAIN_FILE=$sdk/lib/cmake/ChromiumBase/chromium-base-toolchain.cmake" `
  "-DCHROMIUM_BASE_LLVM_ROOT=$llvm" `
  -DCMAKE_BUILD_TYPE=Release
cmake --build out/samples

& ./out/samples/bin/hello_base.exe
& ./out/samples/bin/hello_base.exe --name=Chromium
& ./out/samples/bin/hello_base.exe '--name=Hello World'
& ./out/samples/bin/hello_base.exe --help
```

기본 실행 결과(JSON 속성 순서는 달라질 수 있습니다):

```json
{"greeting":"Hello, World!","upper_name":"WORLD"}
```

`--name`을 생략하거나 빈 문자열로 지정하면 `World`를 사용합니다.
이름의 따옴표 등은 JSON writer가 이스케이프합니다. 출력 인코딩은 UTF-8이며,
`upper_name`은 ASCII 영문자만 대문자로 바꾸고 한글 등은 그대로 유지합니다.

## 하나만 빌드

위 구성 명령의 `-S samples`를 `-S samples/hello_base`, `-B out/samples`를
`-B out/hello_base`로 바꾸면 단독 프로젝트로 빌드합니다. 나머지 SDK 옵션은 같습니다.

```powershell
cmake --build out/hello_base
& ./out/hello_base/bin/hello_base.exe --name=Chromium
```

전체 구성에서 특정 샘플만 빌드할 수도 있습니다:

```powershell
cmake --build out/samples --target hello_base
```

## 동적 DLL로 연결

shared SDK를 내보낸 뒤에는 별도의 빌드 디렉터리에서 같은 샘플을 구성합니다.
`$llvm`, `$ninja`는 위와 동일하게 지정하며, `$sdk`에는 shared SDK 경로를 사용합니다.

```powershell
$sdk = (Resolve-Path 'out/sdk/relocated sdk/windows-x64-chromium-shared-release').Path
cmake -S samples -B out/samples-shared -G Ninja `
  "-DCMAKE_MAKE_PROGRAM=$ninja" `
  "-DCMAKE_PREFIX_PATH=$sdk" `
  "-DCMAKE_TOOLCHAIN_FILE=$sdk/lib/cmake/ChromiumBase/chromium-base-toolchain.cmake" `
  "-DCHROMIUM_BASE_LLVM_ROOT=$llvm" `
  -DCMAKE_BUILD_TYPE=Release
cmake --build out/samples-shared
& ./out/samples-shared/bin/hello_base.exe --name=Chromium
```

샘플의 `chromium_base_deploy_runtime(hello_base)` 호출이 필요한 DLL을 `bin`으로 복사합니다.
실행 파일을 다른 디렉터리로 옮길 때는 함께 생성된 DLL도 모두 옮기세요.
static SDK는 `/MT`, shared SDK는 `/MD`를 사용하며 SDK toolchain이 맞는 값을 설정합니다.

이 구성으로 실제 컴파일·링크와 ASCII·한글·따옴표가 포함된 인자 출력을 검증했습니다.
실행 파일의 `base.dll` import와 DLL 19개 자동 복사를 확인했고, 별도 폴더에서
시스템 PATH만 남긴 실행도 성공했습니다. `base.dll`을 제거하면 DLL 로딩 오류로
실패하는 것도 확인하여 동적 연결임을 검증했습니다.

외부 LLVM으로 검증한 동적 SDK를 사용할 때는 위 명령의 변수를 다음처럼 바꾸고,
빌드 경로를 `out/samples-external-shared`로 지정합니다.

```powershell
$sdk = (Resolve-Path 'out/sdk/relocated sdk/windows-x64-external-shared-release').Path
$llvm = (Resolve-Path '.tools/external-llvm').Path
# 나머지 CMake 옵션은 같으며 -B 경로를 out/samples-external-shared로 변경
& ./out/samples-external-shared/bin/hello_base.exe --name=LLVM
```

검증한 외부 컴파일러는 LLVM 공식 `24.0.0git`, 커밋
`6dc0e52d1e7f7ebef472d00b7e4b1e8c8cba146f`입니다. SDK와 샘플은 동일한 LLVM을 사용해야 합니다.

## 샘플 추가

1. `samples/hello_base`를 새 디렉터리로 복사하고 `project`, 실행 타깃 이름과 코드를 변경합니다.
2. `samples/CMakeLists.txt`에 `add_subdirectory(새_디렉터리)`를 추가합니다.

각 샘플은 `find_package(ChromiumBase CONFIG REQUIRED)`와
`target_link_libraries(타깃 PRIVATE ChromiumBase::base)`를 사용합니다.
SDK 내부의 헤더·라이브러리 목록이나 절대 경로를 샘플에 직접 넣을 필요가 없습니다.
