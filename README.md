# chromium_base

Chromium `base`와 필요한 의존성을 선택 추출하여 독립 라이브러리로 만들기 위한 프로젝트입니다.
**외부 LLVM과 Chromium 제공 LLVM 모두 동일한 소스 추출본을 사용합니다.**
전체 Chromium 체크아웃, Chrome 브라우저 소스, 전체 LLVM 소스 빌드는 필요하지 않습니다.

현재는 선택 추출, 고정 바이너리 도구 다운로드, Windows x64 빌드 드라이버를 제공합니다.
**Windows SDK 10.0.28000.0 설치와 필수 파일 검증을 완료**했습니다.
누락된 빌드 의존성을 보완하여 Windows x64 / Chromium LLVM의
**정적·동적 `base` 타깃의 실제 빌드와 외부 소비자 실행이 성공**했습니다.
정적 GN 생성은 847개 타깃, Ninja 입력 검사는 2,346개 작업을 통과했습니다.
동적 구성은 GN 생성 856개 타깃과 실제 빌드 2,275개 작업을 통과했습니다.
정적 산출물은 `vendor/chromium/out/dependency-audit/obj/base/base.lib`,
동적 산출물은 `vendor/chromium/out/sh/base.dll` 및 `base.dll.lib`입니다.
원본은 객체 파일을 참조하는 thin archive이며, SDK 내보내기는 이를 일반 archive로 바꾸고
헤더·의존성을 묶습니다. **SDK를 다른 경로로 옮긴 외부 CMake 소비자의 빌드와 실행도 성공**했습니다.
실행 가능한 첫 샘플은 [samples/hello_base](samples/README.md)에 있습니다.
DLL 19개를 배치한 별도 폴더에서 시스템 경로만 사용한 실행도 검증했습니다.
외부 LLVM 24 개발 빌드의 **동적 빌드·SDK·샘플·DLL 배포 실행도 검증**했습니다.
외부 LLVM 정적 빌드는 검증 중이며, Debug와 macOS/Linux 네이티브 빌드는 아직 검증하지 않았습니다.

## 구조

```text
source.lock.json            # 공통 소스 커밋·선택 경로·별도 저장소 SHA
tools.lock.json             # Windows 도구 URL·SHA-256
standalone/                # 독립 GN 진입점과 gclient 대체 설정
vendor/chromium/            # 두 LLVM 모드가 공유하는 Git 없는 추출본
.tools/gn/                 # GN
.tools/ninja/              # Ninja
.tools/rust-toolchain/     # 두 모드에 공통으로 필요한 Rust 도구
.tools/chromium-llvm/      # Chromium LLVM 모드에서만 필요
.cache/standalone/         # 부분 Git 객체 캐시와 다운로드 압축 파일
```

`vendor/`, `.tools/`, `.cache/`는 생성물로 Git에서 제외합니다. 소스 동기화에는
컴파일러 선택 옵션이 없으며, 컴파일러를 바꿀 때 소스를 다시 받지 않습니다.
원본의 경로 구조와 라이선스를 유지합니다. `standalone/`의 파일만 명시적으로 덮어씁니다.
추출 시 고정 커밋의 시각으로 `build/util/LASTCHANGE.committime`도 생성합니다.
GN의 `root_patterns`는 기본 타깃과 `base`의 전이 의존성만 선택하고,
`enable_js_protobuf=false`로 C++ 라이브러리에 불필요한 JavaScript 생성 규칙을 제외합니다.
BoringSSL, NASM, RE2, compiler-rt, LLVM libc도 Chromium `DEPS`와 같은 커밋으로 고정합니다.

## 준비 및 소스 추출

Python 3.10 이상과 Git이 필요합니다. 아래 `python`은 Windows Store 실행 별칭이 아닌
실제 Python 실행 파일이어야 합니다. 소스·LLVM 경로에는 공백이나 셸 특수문자를 쓰지 마세요.

```powershell
# 컴파일러 모드에 관계없이 한 번만 실행
python scripts/sync_source.py
python scripts/sync_source.py --verify

# 두 모드의 공통 빌드 도구
python scripts/sync_tools.py gn ninja rust-toolchain

# Chromium LLVM 모드를 사용할 때 추가
python scripts/sync_tools.py chromium-llvm
```

소스는 Chromium 커밋 `1633b610f5957ddd13a26fe87628c0768067e740`에 고정되어 있습니다.
`base`, GN 빌드 규칙, 선택된 C++/Rust 의존성과 라이선스를 가져옵니다.
별도 저장소인 libc++, libc++abi, libunwind, Perfetto도 해당 DEPS의 SHA로 고정합니다.
Git 부분 클론에서 선택된 파일의 객체만 내려받으며 전체 소스 트리를 체크아웃하지 않습니다.

추출본의 `.chromium-source.json`에는 잠금 목록과 파일별 SHA-256이 들어갑니다.
검증 시 수정·삭제·추가된 소스를 감지하며 `out/`만 빌드 생성물로 제외합니다.
기존 추출본은 덮어쓰지 않습니다. 잠금 목록 변경 후 다시 추출하려면 기존 폴더를
보관하거나 `--destination`으로 새 경로를 선택하고 빌드에 `--source`를 지정하세요.

선택 범위는 `//base:base`를 시작점으로 한 의존성 목록입니다. 전체 `base` 하위의
모든 테스트·선택 라이브러리가 빌드된다는 뜻은 아닙니다. GN 검증이 끝나기 전에는
이 목록을 완성된 최소 의존성 집합으로 취급하지 마세요.

## 컴파일러 선택

| 항목 | 외부 LLVM (기본값) | Chromium LLVM |
|---|---|---|
| 선택 | `--toolchain external` | `--toolchain chromium` |
| LLVM 위치 | `--llvm-root` 또는 `LLVM_ROOT` | `.tools/chromium-llvm` |
| Chromium 전용 플러그인 | 비활성화 | 원본 기본값 유지 |
| 소스 | `vendor/chromium` | 동일한 `vendor/chromium` |
| C++ 표준 라이브러리 | 고정된 Chromium libc++ | 동일한 libc++ |
| Rust 의존성 | 공통 고정 Rust 도구 | 동일한 Rust 도구 |

현재 소스 커밋은 **Clang major 24**를 요구합니다. 외부 LLVM은 호환되는 `clang-cl.exe`와
`lld-link.exe`를 별도로 준비해야 합니다. major 일치는 필요 조건이며 실제 호환성을 보장하지는
않습니다. 더 오래된 LLVM을 사용하려면 그 LLVM에 맞는 Chromium 커밋과 의존성을 함께
재고정하고 검증해야 합니다. 두 모드 사이의 자동 전환은 하지 않습니다.

`--llvm-root`와 `LLVM_ROOT`를 생략하면 `Program Files/LLVM`을 감지하지만, upstream GN의
일부 명령이 경로를 따옴표 없이 사용하므로 공백 경로는 `doctor`에서 차단합니다.
외부 LLVM에는 `C:/LLVM` 같은 경로를 사용하세요.

## Windows 빌드

Visual Studio C++ 데스크톱 도구와 선택한 커밋이 요구하는 SDK가 필요합니다.
이 PC에는 VS 2026과 SDK 10.0.28000.0이 준비되어 있습니다.
SDK 도구 버전은 10.0.28000.2526이며 x86·x64·ARM64 라이브러리와 리소스 컴파일러,
UWP 헤더 및 x64 디버깅 도구를 확인했습니다. 실행 중인 VS를 유지하기 위해 사용자 승인하에
Microsoft의 SDK 독립 설치 프로그램을 사용했으며 재부팅은 필요하지 않았습니다.
필수 GN 의존성은 보완했으며 Chromium LLVM 정적 빌드가 성공했습니다.
드라이버는 시스템 구성 요소를 자동 설치하지 않습니다.

```powershell
# 설정 미리보기와 환경 검사
python scripts/chromium_base.py plan --llvm-root C:/LLVM
python scripts/chromium_base.py doctor --llvm-root C:/LLVM

# 외부 LLVM, 정적 라이브러리
python scripts/chromium_base.py configure --llvm-root C:/LLVM
python scripts/chromium_base.py build --llvm-root C:/LLVM

# Chromium LLVM, 동적 라이브러리
python scripts/chromium_base.py configure --toolchain chromium --linkage shared --output-dir vendor/chromium/out/sh
python scripts/chromium_base.py build --toolchain chromium --linkage shared --output-dir vendor/chromium/out/sh
```

`--linkage static|shared`, `--configuration release|debug`를 조합합니다.
`configure`와 `build`에는 같은 옵션을 전달하세요. 기본값은 `external/static/release`입니다.
GN과 Ninja는 `.tools`에서 사용하며 `--gn`, `--ninja`로 경로를 지정할 수 있습니다.
`depot_tools`는 필수가 아닙니다. 기존 환경에서는 `--depot-tools`로 `autoninja.py`를
명시하여 사용할 수 있습니다.

출력은 `<source>/out/chromium-base/windows-x64-<compiler>-<linkage>-<configuration>`으로
분리합니다. `.chromium-base.json`에 소스 식별값, LLVM/GN/Ninja 버전, 검증한 Rust 도구,
VS/SDK 정보와 실행 상태를 기록합니다. 환경이 달라지거나 `args.gn`이 수정되면 기존 출력을
재사용하지 않습니다. GN 생성 후 실제 명령이 선택한 `clang-cl`과 `lld-link`를 참조하는지
확인하고, 실패하면 실패 종료 코드와 상태를 유지합니다.

Windows에서는 Rust 임시 파일 경로가 길어질 수 있습니다. 이 PC에서는 269자 경로가 실패해
동적 빌드에 `--output-dir vendor/chromium/out/sh`를 사용합니다. 이 옵션은 `<source>/out`의
하위 디렉터리만 허용하며 `configure`와 `build`에 동일하게 지정해야 합니다.
기존 기본 출력과 manifest는 보존됩니다. 정적 빌드에도 별도의 짧은 경로를 지정할 수 있습니다.

`base` 타깃 출력이 곧 단일 배포용 라이브러리는 아닙니다. 전이 의존 라이브러리,
생성 헤더, 시스템 링크 옵션, DLL 및 import library 등을 포함한 패키징과 소비자 검증이
추가로 필요합니다. 소비 프로그램도 같은 표준 라이브러리와 호환되는 설정을 사용해야 합니다.

## SDK와 CMake 연결

`scripts/export_sdk.py`는 성공한 **Windows x64 / static 또는 shared / Release / libc++** 빌드에서
SDK를 만듭니다. 원본 소스나 빌드의 `args.gn`은 수정하지 않습니다. 별도의 GN 소비 타깃에서
공개 include·define·옵션을 얻고, Ninja의 실제 링크 입력으로 전이 의존성을 수집합니다.
버전별 라이브러리 이름 목록을 별도로 관리하지 않습니다.

```powershell
# 먼저 Chromium LLVM 정적 Release를 빌드한 경우
python scripts/export_sdk.py `
  --toolchain chromium `
  --build-dir vendor/chromium/out/chromium-base/windows-x64-chromium-static-release `
  --destination out/sdk/windows-x64-chromium-static-release

# 이 PC의 기존 검증 빌드(dependency-audit)는 드라이버 manifest 생성 이전의 산출물입니다.
# 이를 사용할 때만 명시적으로 --allow-unmanaged-build를 전달합니다.
python scripts/export_sdk.py `
  --toolchain chromium --allow-unmanaged-build `
  --build-dir vendor/chromium/out/dependency-audit `
  --destination out/sdk/from-audited-build

# 위의 짧은 경로에서 동적 Release 빌드를 완료한 경우
python scripts/export_sdk.py `
  --toolchain chromium --linkage shared `
  --build-dir vendor/chromium/out/sh `
  --destination out/sdk/windows-x64-chromium-shared-release
```

일반 사용에서는 빌드 드라이버의 성공 manifest와 소스·도구 식별값을 검사합니다.
`--allow-unmanaged-build`는 이 manifest 검사를 생략하므로 빌드 이력을 직접 관리하는
기존 산출물에만 사용하세요. 이 경우에도 소스 무결성·GN 인자·선택 LLVM 경로를 검사하고
Ninja로 `base`를 갱신합니다. 현재 내보내기는 direct Ninja 빌드를 대상으로 하며,
`autoninja`로 구성한 빌드는 드라이버의 `--ninja` 옵션으로 별도 구성해야 합니다.

패키지 내용:

- `include/source`, `include/generated`: 공개 헤더, 생성 헤더, 고정 libc++ 헤더와 설정.
- `lib`: 일반 `.lib`/`.rlib` 및 직접 연결할 `.obj`. thin archive는 원래 Ninja 객체 목록으로
  재생성합니다. 현재 LLVM의 thin 입력 재포장 오류를 피하며, 직접 연결 객체의 의미도 유지합니다.
- `lib/cmake/ChromiumBase`: `ChromiumBase::base`와 LLVM toolchain 파일.
- `bin` (shared): GN의 런타임 의존성에 포함된 컴포넌트 DLL과 VC 런타임·진단 DLL.
  `.pdb` 디버그 심볼은 실행에 필요하지 않아 제외합니다.
- `licenses`, `sdk-manifest.json`, `files.sha256.json`: 의존성 라이선스, 출처·설정·무결성 정보.

기존 SDK 경로는 덮어쓰지 않습니다. 새 경로에 생성한 뒤 검증하여 교체하세요.
실패한 `*.staging-*` 디렉터리는 진단용으로 남고 완료된 SDK로 게시되지 않습니다.
출처 manifest의 원래 경로는 이력용이며, CMake 사용 경로는 SDK 위치를 기준으로 계산합니다.
소비 프로그램을 빌드하는 PC에는 Visual Studio C++ 도구와 Windows SDK가 필요합니다.
shared 패키지는 GN이 런타임 의존성으로 지정한 DLL도 포함합니다. 다른 곳으로 배포할 때는
동봉된 출처·라이선스 정보와 해당 도구의 재배포 조건을 확인하세요.

소비 프로젝트의 `CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.25)
project(my_app LANGUAGES CXX)
find_package(ChromiumBase CONFIG REQUIRED)
add_executable(my_app main.cc)
target_link_libraries(my_app PRIVATE ChromiumBase::base)
chromium_base_deploy_runtime(my_app)
```

**x64 Visual Studio Developer PowerShell**에서 아래와 같이 구성합니다.

```powershell
$sdk = 'C:/sdk/chromium-base' # 내보낸 SDK는 다른 경로로 옮겨도 됩니다.
cmake -S . -B build -G Ninja `
  "-DCMAKE_PREFIX_PATH=$sdk" `
  "-DCMAKE_TOOLCHAIN_FILE=$sdk/lib/cmake/ChromiumBase/chromium-base-toolchain.cmake" `
  -DCHROMIUM_BASE_LLVM_ROOT=C:/tools/chromium-llvm `
  -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

LLVM은 SDK를 빌드한 것과 동일한 `clang-cl`/`lld-link`를 사용해야 합니다. CMake 구성 시
실행 파일의 SHA-256을 확인하며 CRT는 static SDK의 경우 `/MT`, shared SDK는 `/MD`입니다.
표준 라이브러리는 각 SDK에 맞춰 빌드된 libc++를 사용합니다.
`chromium_base_deploy_runtime()`은 shared SDK의 DLL을 실행 파일 옆에 복사하며 static SDK에서는
추가 복사를 하지 않습니다. 정적·동적 SDK의 헤더나 라이브러리를 섞어 사용하지 마세요.
SDK 종류를 바꿀 때는 CMake 빌드 디렉터리도 새로 만드세요.
Debug·다중 구성 generator·추가 sanitizer 설정은 현재 내보내기 범위에 포함되지 않습니다.
초기 패키지의 컴파일 옵션은 C++ 소비 타깃을 대상으로 합니다. C 소스는 별도 타깃으로 분리하고,
C/C++ 혼합 타깃에 이 C++ 옵션을 그대로 전달하지 마세요.
외부 LLVM 모드에도 같은 내보내기 경로를 사용하며 해당 LLVM으로 빌드한 SDK를 사용해야 합니다.

`tests/sdk_consumer`와 `tests/verify_sdk.py`는 문자열·JSON·파일·태스크 실행 및 정적 라이브러리를
포함한 외부 연결 검증용입니다. Ninja의 실제 헤더 의존성을 검사해 원본 소스/빌드 경로 참조와
동봉 libc++·생성 헤더 사용 여부를 확인합니다. 사용자용 샘플과 추가 방법은
[samples/README.md](samples/README.md)에 있습니다.

이 PC에서 검증된 정적 SDK는 `out/sdk/relocated sdk/windows-x64-chromium-static-release`입니다.
파일 크기 합계는 약 **399 MiB**(10,017개 파일)이며 원본 빌드·도구·캐시 용량은 별도입니다.
일반 archive 121개(`.lib` 95개, `.rlib` 26개)와 직접 연결 객체 458개를 포함합니다.
공백이 있는 경로로 옮긴 뒤 소비자 정적 라이브러리·실행 파일의 컴파일, 링크, 실행을 통과했고,
실제 헤더 의존성 2,315건에 원래 Chromium 소스/빌드 경로가 없음을 확인했습니다.
서로 다른 CMake 하위 디렉터리에서 `find_package`를 각각 호출하는 경우도 검증했습니다.
CMake는 4.3.1-msvc1로 검증했습니다. 전체 Python 단위 테스트는 59개가 통과했습니다.

동적 SDK는 `out/sdk/relocated sdk/windows-x64-chromium-shared-release`입니다.
크기는 약 **121 MiB**(127,028,061바이트, 9,469개 파일)이며 링크 입력 11개와
런타임 DLL 19개를 포함합니다. 공백이 있는 경로로 옮긴 뒤 외부 소비자와 `hello_base`의
컴파일·링크·실행을 통과했습니다. 소비자의 실제 헤더 의존성 2,307건에 원본 소스/빌드
경로가 없으며, 실행 파일의 PE import에 `base.dll`이 포함됨을 확인했습니다.

`tests/verify_dll_runtime.py`로 두 실행 파일을 각각 별도 폴더에 배치하고
PATH를 Windows 및 System32만 남긴 상태에서 실행했습니다. 정상 출력과 함께
`base.dll`을 잠시 제거했을 때 `0xC0000135`(DLL 없음)로 실패하는 것도 확인했습니다.
결과는 `out/shared-deployment/hello_base/runtime-verification.json`과
`out/shared-deployment/sdk_consumer/runtime-verification.json`에 있습니다.
기존 정적 SDK의 복사본에 현재 CMake 패키지 생성 코드를 적용한 회귀 검사도 통과했습니다.

검증 재실행 예시(새 `--work` 경로 필요):

```powershell
python tests/verify_sdk.py `
  --sdk 'out/sdk/relocated sdk/windows-x64-chromium-static-release' `
  --llvm-root .tools/chromium-llvm --cmake cmake --ninja .tools/ninja/ninja.exe `
  --work out/sdk-consumer-check
```

위 명령은 x64 VS Developer 환경에서 실행합니다. 이 PC의 GN 환경을 재사용하려면
`--environment-file vendor/chromium/out/dependency-audit/environment.x64`를 추가할 수 있습니다.
동적 SDK를 검사하려면 `--sdk`를 shared SDK 경로로, `--environment-file`을
`vendor/chromium/out/sh/environment.x64`로 지정하고 새 `--work` 경로를 사용하세요.

## 용량과 검증 범위

외부 LLVM 검증에는 [LLVM 공식 Windows x64 개발 빌드](https://github.com/llvm/llvm-project/actions/runs/37080272399)의
`24.0.0git`(커밋 `6dc0e52d1e7f7ebef472d00b7e4b1e8c8cba146f`)을 사용했습니다.
위치는 `.tools/external-llvm`이며 시스템 PATH는 변경하지 않았습니다.
Chromium 소스·공통 Rust 도구는 동일하고 `clang_use_chrome_plugins=false`를 적용합니다.

동적 빌드 `vendor/chromium/out/eh`는 2,275개 작업을 완료했습니다.
SDK는 `out/sdk/relocated sdk/windows-x64-external-shared-release`,
샘플은 `out/samples-external-shared/bin/hello_base.exe`입니다.
외부 소비자의 헤더 의존성 2,307건에 원본 소스/빌드 경로 참조가 없고,
샘플과 소비자 모두 DLL 19개를 별도 배치한 실행 및 누락 DLL 실패 검사를 통과했습니다.
정적 구성 `vendor/chromium/out/es`는 중단된 빌드를 재개하여 검증 중입니다.
이 결과는 위 개발 빌드에 대한 것이며 다른 LLVM 버전의 호환성을 보장하지 않습니다.

```powershell
python scripts/chromium_base.py configure --toolchain external --llvm-root .tools/external-llvm --linkage shared --output-dir vendor/chromium/out/eh
python scripts/chromium_base.py build --toolchain external --llvm-root .tools/external-llvm --linkage shared --output-dir vendor/chromium/out/eh
python scripts/export_sdk.py --toolchain external --linkage shared --build-dir vendor/chromium/out/eh --destination out/sdk/windows-x64-external-shared-release
```

외부 LLVM 설치본은 약 3.65 GiB입니다. 공식 아티팩트 ZIP(약 1.54 GiB)과
그 안에서 꺼낸 tar.xz(약 751 MiB)는 `.cache/external`에 별도 보관되어 있습니다.

현재 실제 선택 추출본은 34,706개 파일, 약 360 MiB입니다.
부분 Git 캐시, 압축 파일,
도구 설치본과 빌드 산출물의 용량은 별도입니다.
실제 다운로드·설치 후 측정한 크기입니다. 설치 크기는 파일 크기의 합계로,
파일시스템 할당 단위에 따른 차이는 포함하지 않습니다.

| 도구 | 압축 다운로드 | 설치 후 |
|---|---:|---:|
| Chromium LLVM | 약 50 MiB | 약 227 MiB |
| 공통 Rust 도구 | 약 406 MiB | 약 2.39 GiB |
| GN + Ninja | 약 1.5 MiB | 약 3.2 MiB |

LLVM 자체보다 공통 Rust 도구가 더 큽니다. Visual Studio/Windows SDK 및 정적·동적
빌드 산출물은 위 표에 포함하지 않습니다.

```powershell
python -m unittest discover -s tests -v
```

테스트는 선택 추출, Git 없는 소스 식별, 파일·도구 무결성, 덮어쓰기 방지,
두 LLVM 설정과 출력 분리, 실패 전파, SDK 명령 해석과 경로 처리를 검증합니다. GN/컴파일 경계의 단위 테스트는
대역을 사용합니다. CI의 Linux 작업도 Python 테스트이며 Linux용 `base` 빌드가 아닙니다.

## 라이선스와 참고

자체 도구는 루트 `LICENSE`를 따릅니다. 가져온 Chromium과 제3자 코드는
각각의 원본 라이선스를 유지하며 루트 라이선스로 대체하지 않습니다.

- [구성 설계](docs/toolchain-design.md)
- [공통 소스 구현 계획](docs/superpowers/plans/2026-10-28-standalone-source.md)
- [Chromium base 안내](https://github.com/chromium/chromium/blob/main/base/README.md)
- [외부 Clang 설정](https://chromium.googlesource.com/chromium/src/+/main/docs/clang.md#using-a-custom-clang-binary)
