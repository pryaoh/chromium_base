# chromium_base

Chromium `base`를 독립 라이브러리로 사용하기 위한 프로젝트입니다.
현재는 **기존 Chromium 체크아웃을 빌드하는 Windows x64 드라이버**를 제공합니다.
외부 LLVM과 Chromium 제공 LLVM을 명시적으로 선택할 수 있습니다.

아직 Chromium 소스를 이 저장소로 추출하지 않았으며, 배포용 SDK·CMake 패키지는
구현하지 않았습니다. 실제 `base` 컴파일 및 외부 소비 프로그램 실행도 검증 전입니다.
macOS/Linux 네이티브 빌드는 후속 범위입니다. CI의 Linux 작업은 Python 드라이버
테스트이며 Linux용 `base` 빌드가 아닙니다.

## 컴파일러 모드

| 옵션 | 외부 LLVM (기본값) | Chromium 제공 LLVM |
|---|---|---|
| 선택 | `--toolchain external` | `--toolchain chromium` |
| LLVM 경로 | `--llvm-root`, `LLVM_ROOT`, `Program Files/LLVM` 순 | 체크아웃의 `third_party/llvm-build/Release+Asserts` |
| Chromium 전용 플러그인 | 비활성화 | 원본 기본값 유지 |
| 표준 라이브러리 | Chromium의 libc++ | Chromium의 libc++ |
| 모드 자동 전환 | 하지 않음 | 하지 않음 |

컴파일러가 없으면 실패합니다. Chromium 모드에서 `--llvm-root`를 지정하면 오류입니다.
두 모드의 바이너리나 오브젝트 파일을 혼합하는 ABI 호환성은 보장하지 않습니다.
라이브러리 소비 프로그램에도 동일한 표준 라이브러리·호환되는 빌드 설정이 필요합니다.

## 사전 준비

1. Python 3.10 이상 및 Git.
2. Visual Studio의 C++ 데스크톱 개발 도구와 해당 Chromium 리비전이 요구하는
   Windows SDK 및 추가 구성 요소. `doctor`는 기본 x64 도구를 확인하며, 정확한
   최소 SDK 버전과 전체 구성 요소 호환성은 GN 생성/컴파일 단계에서 검증됩니다.
3. `depot_tools`와 의존성 및 hooks가 정상 동기화된 Chromium `src` 체크아웃.
   `base/`만 복사한 디렉터리는 사용할 수 없습니다.
4. 외부 모드에서는 `clang-cl.exe`, `lld-link.exe`를 포함한 별도 LLVM.
   Chromium 모드에서는 체크아웃에 맞춰 hooks로 설치된 LLVM.

정적 라이브러리 생성은 원본 GN 규칙대로 `lld-link /lib`를 사용합니다.
Chromium 소스와 LLVM은 **공백과 셸 특수문자가 없는 경로**에 준비하세요.
LLVM 기본 설치 위치인 `C:/Program Files/LLVM`은 감지 대상이지만, 원본 GN 규칙이
컴파일러 경로를 따옴표 없이 사용하는 부분이 있어 `doctor`에서 빌드를 차단합니다.
외부 LLVM은 `C:/LLVM` 같은 위치를 권장합니다. `plan`은 오프라인 설정 미리보기라
이러한 경로도 표현할 수 있으며, 실제 빌드 적합성은 `doctor`가 검사합니다.

이 드라이버는 다운로드나 시스템 설치를 수행하지 않습니다.
먼저 [Windows 체크아웃 안내](https://chromium.googlesource.com/chromium/src/+/main/docs/windows_build_instructions.md)를
따라 여유 공간이 충분한 위치에서 Chromium과 `depot_tools`를 준비하세요.
원하는 **특정 커밋 SHA로 체크아웃한 뒤 해당 리비전의 DEPS와 hooks를 동기화**해야 합니다.
Chromium 소스와 별개로 관리되는 의존성도 맞춰야 하므로 Git checkout만으로는 부족합니다.
Windows의 로컬 Visual Studio 사용 설정은 동기화 전에 적용합니다.

```powershell
$env:DEPOT_TOOLS_WIN_TOOLCHAIN = '0'
```

LLVM 버전은 선택한 Chromium 리비전과 함께 결정하세요. 드라이버는 읽을 수 있는
단일 리터럴로 선언된 `clang_version`과 LLVM 도구의 major 버전 불일치를 차단합니다.
조건부/동적 선언은 잘못 추측하지 않고 경고를 남겨 GN 검증으로 넘깁니다. 같은 major라도
최신 Clang 기능·libc++ 요구사항 때문에 실패할 수 있으므로 실제 빌드가 필요합니다.
외부 LLVM 설정 근거는 [Chromium Clang 문서](https://chromium.googlesource.com/chromium/src/+/main/docs/clang.md#using-a-custom-clang-binary)입니다.

## 사용

아래 경로는 준비한 체크아웃과 도구의 실제 위치로 바꿔 사용합니다.
`python`은 Windows Store 실행 별칭이 아닌 실제 Python이어야 합니다.

```powershell
$src = 'D:/chromium/src'
$depot = 'D:/depot_tools'
$llvm = 'C:/LLVM'

# 설치나 파일 변경 없이 생성할 설정 확인
python scripts/chromium_base.py plan --source $src --llvm-root $llvm

# 필요한 도구를 한 번에 확인: 누락 시 JSON 오류 목록 및 종료 코드 1
python scripts/chromium_base.py doctor --source $src --llvm-root $llvm --depot-tools $depot

# 외부 LLVM, 정적 라이브러리
python scripts/chromium_base.py configure --source $src --llvm-root $llvm --depot-tools $depot
python scripts/chromium_base.py build --source $src --llvm-root $llvm --depot-tools $depot

# Chromium 제공 LLVM, 동적 라이브러리
python scripts/chromium_base.py configure --source $src --toolchain chromium --linkage shared --depot-tools $depot
python scripts/chromium_base.py build --source $src --toolchain chromium --linkage shared --depot-tools $depot
```

`--linkage static|shared`, `--configuration release|debug`를 조합할 수 있습니다.
`configure`와 `build`에는 같은 옵션을 전달하세요. 기본값은 `external/static/release`입니다.
GN은 체크아웃의 `buildtools/win/gn.exe`를 사용하며 `--gn PATH`로 명시할 수 있습니다.
`--source` 생략 시 이 저장소의 `.upstream/src`를 사용합니다.

빌드는 선택한 체크아웃 안에서 `autoninja.py -C <output> base`를 실행합니다.
자식 프로세스에만 `DEPOT_TOOLS_WIN_TOOLCHAIN=0`, `DEPOT_TOOLS_UPDATE=0`을 적용하며,
원격 빌드는 GN 인자로 비활성화합니다.

## 출력과 재현 정보

```text
<src>/out/chromium-base/
  windows-x64-external-static-release/
  windows-x64-external-shared-release/
  windows-x64-chromium-static-release/
  windows-x64-chromium-shared-release/
  ...-debug/
```

각 폴더에는 `args.gn`과 `.chromium-base.json`이 생성됩니다. JSON에는 소스 커밋,
LLVM 버전 출력, GN 버전, 감지한 VS/SDK 경로와 실행 상태를 기록합니다.
기존 사용자 출력 폴더를 덮어쓰지 않으며 수동으로 변경한 `args.gn`도 보존합니다.
컴파일러·소스 커밋·기록된 환경이 변경되면 기존 출력을 재사용하지 않습니다.
그 경우 기존 출력 폴더를 별도 위치에 보관한 뒤 다시 `configure`하세요.

GN 생성 후 `toolchain.ninja`가 선택한 `clang-cl`과 `lld-link`를 참조하는지 확인합니다.
생성 또는 빌드 실패 시 종료 코드를 전달하고 성공 상태를 기록하지 않습니다.
중단된 생성/빌드는 다시 `configure`한 후 실행할 수 있습니다.

`base` 타깃 빌드 결과가 곧 단일 배포용 라이브러리는 아닙니다. 정적 빌드는 전이
의존 라이브러리와 시스템 라이브러리가 필요할 수 있고, 동적 빌드는 의존 DLL과
import library가 필요합니다. 공개/생성 헤더, 링크 설정, 런타임 파일을 수집하는
패키징과 외부 소비 프로젝트 테스트는 다음 단계입니다.

## 테스트 및 현재 검증 범위

```powershell
python -m unittest discover -s tests -v
```

테스트는 CLI 설정 선택, 출력 분리, 환경 누락 보고, 기존 출력 보호, 소스/도구 변경
감지, 명령 실패 전파를 검증합니다. GN과 빌드 실행 경계는 테스트 대역을 사용하므로
이 테스트 통과를 실제 Chromium 빌드 성공으로 해석하면 안 됩니다.

## 소스 및 라이선스

이 저장소의 빌드 도구는 루트 `LICENSE`를 따릅니다. 향후 가져올 Chromium 코드와
제3자 의존성은 각각의 원본 라이선스를 유지해야 하며 루트 라이선스로 대체하지 않습니다.
Chromium은 `base`의 외부 사용과 API/ABI 안정성을 보장하지 않습니다.
[원본 base README](https://github.com/chromium/chromium/blob/main/base/README.md)

- [구성 설계](docs/toolchain-design.md)
- [구현 계획](docs/superpowers/plans/2026-10-27-dual-clang.md)
