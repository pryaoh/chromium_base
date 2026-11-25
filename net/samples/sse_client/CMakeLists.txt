cmake_minimum_required(VERSION 3.25)
project(sse_client LANGUAGES CXX)

find_package(ChromiumNet CONFIG REQUIRED)

add_executable(sse_client main.cc)
target_link_libraries(sse_client PRIVATE ChromiumNet::net)
chromium_net_deploy_runtime(sse_client)
