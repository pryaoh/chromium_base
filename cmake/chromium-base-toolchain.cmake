# Run from an x64 Visual Studio Developer shell with Windows SDK installed.
# Supply -DCHROMIUM_BASE_LLVM_ROOT=<the LLVM used to build/export the SDK>.
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR AMD64)
if(NOT CHROMIUM_BASE_LLVM_ROOT)
  message(FATAL_ERROR "Set CHROMIUM_BASE_LLVM_ROOT to the SDK's exact LLVM installation")
endif()
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES CHROMIUM_BASE_LLVM_ROOT)
file(TO_CMAKE_PATH "${CHROMIUM_BASE_LLVM_ROOT}" CHROMIUM_BASE_LLVM_ROOT)
set(CMAKE_C_COMPILER "${CHROMIUM_BASE_LLVM_ROOT}/bin/clang-cl.exe")
set(CMAKE_CXX_COMPILER "${CHROMIUM_BASE_LLVM_ROOT}/bin/clang-cl.exe")
set(CMAKE_LINKER "${CHROMIUM_BASE_LLVM_ROOT}/bin/lld-link.exe")
set(CMAKE_AR "${CHROMIUM_BASE_LLVM_ROOT}/bin/lld-link.exe")
set(CMAKE_USER_MAKE_RULES_OVERRIDE "${CMAKE_CURRENT_LIST_DIR}/chromium-base-rules.cmake")
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)
# Avoid CMake's default /EHsc, /GR and /MD conflicting with the GN ABI contract.
set(CMAKE_C_FLAGS "" CACHE STRING "C flags")
set(CMAKE_CXX_FLAGS "" CACHE STRING "C++ flags")
set(CMAKE_BUILD_TYPE Release CACHE STRING "SDK configuration")
