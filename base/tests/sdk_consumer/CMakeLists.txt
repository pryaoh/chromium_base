cmake_minimum_required(VERSION 3.25)
project(chromium_base_sdk_verification LANGUAGES CXX)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
enable_testing()
# Both sibling directories independently discover the package.
add_subdirectory(probe)
add_subdirectory(app)
