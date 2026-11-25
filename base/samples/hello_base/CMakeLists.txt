cmake_minimum_required(VERSION 3.25)
project(hello_base LANGUAGES CXX)

find_package(ChromiumBase CONFIG REQUIRED)

add_executable(hello_base main.cc)
target_link_libraries(hello_base PRIVATE ChromiumBase::base)
set_target_properties(hello_base PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
if(COMMAND chromium_base_deploy_runtime)
  chromium_base_deploy_runtime(hello_base)
endif()
