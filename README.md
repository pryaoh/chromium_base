# chromium_base

Chromium `base`와 필요한 의존성을 선택 추출하여 독립 라이브러리로 만들기 위한 프로젝트입니다.
**외부 LLVM과 Chromium 제공 LLVM 모두 동일한 소스 추출본을 사용합니다.**
전체 Chromium 체크아웃, Chrome 브라우저 소스, 전체 LLVM 소스 빌드는 필요하지 않습니다.

현재는 선택 추출, 고정 바이너리 도구 다운로드, Windows x64 빌드 드라이버를 제공합니다.
**Windows SDK 10.0.28000.0 설치와 필수 파일 검증을 완료**했습니다.
누락된 빌드 의존성을 보완하여 Windows x64 / Chromium LLVM의
**정적 `base` 타깃 실제 빌드가 성공**했습니다. 정적 GN 생성은 847개 타깃,
Ninja 입력 검사는 2,346개 작업을 통과했습니다. 동적 구성도 GN 생성(856개 타깃)과
Ninja 입력 검사(2,275개 작업)를 통과했습니다.
검증 산출물은 `vendor/chromium/out/dependency-audit/obj/base/base.lib`입니다.
이는 객체 파일을 참조하는 thin archive이므로, 배포용으로 쓰려면 일반 정적 라이브러리와
전이 의존성을 묶는 패키징이 필요합니다. DLL 링크와 외부 LLVM의 실제 빌드는 미검증입니다.
배포용 SDK/CMake 패키지와 소비 프로그램, macOS/Linux 네이티브 빌드는 후속 작업입니다.

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
현재 남은 오류는 SDK가 아닌 추출본의 GN 의존성 누락입니다.
이 의존성 보완과 후속 검증이 완료되어야 아래 빌드가 성공할 수 있습니다.
드라이버는 시스템 구성 요소를 자동 설치하지 않습니다.

```powershell
# 설정 미리보기와 환경 검사
python scripts/chromium_base.py plan --llvm-root C:/LLVM
python scripts/chromium_base.py doctor --llvm-root C:/LLVM

# 외부 LLVM, 정적 라이브러리
python scripts/chromium_base.py configure --llvm-root C:/LLVM
python scripts/chromium_base.py build --llvm-root C:/LLVM

# Chromium LLVM, 동적 라이브러리
python scripts/chromium_base.py configure --toolchain chromium --linkage shared
python scripts/chromium_base.py build --toolchain chromium --linkage shared
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

`base` 타깃 출력이 곧 단일 배포용 라이브러리는 아닙니다. 전이 의존 라이브러리,
생성 헤더, 시스템 링크 옵션, DLL 및 import library 등을 포함한 패키징과 소비자 검증이
추가로 필요합니다. 소비 프로그램도 같은 표준 라이브러리와 호환되는 설정을 사용해야 합니다.

## 용량과 검증 범위

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
두 LLVM 설정과 출력 분리, 실패 전파를 검증합니다. GN/컴파일 경계의 단위 테스트는
대역을 사용합니다. CI의 Linux 작업도 Python 테스트이며 Linux용 `base` 빌드가 아닙니다.

## 라이선스와 참고

자체 도구는 루트 `LICENSE`를 따릅니다. 가져온 Chromium과 제3자 코드는
각각의 원본 라이선스를 유지하며 루트 라이선스로 대체하지 않습니다.

- [구성 설계](docs/toolchain-design.md)
- [공통 소스 구현 계획](docs/superpowers/plans/2026-10-28-standalone-source.md)
- [Chromium base 안내](https://github.com/chromium/chromium/blob/main/base/README.md)
- [외부 Clang 설정](https://chromium.googlesource.com/chromium/src/+/main/docs/clang.md#using-a-custom-clang-binary)
