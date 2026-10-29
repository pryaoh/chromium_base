find_package(ChromiumBase CONFIG REQUIRED)
add_executable(sdk_consumer ../main.cc)
target_link_libraries(sdk_consumer PRIVATE sdk_probe ChromiumBase::base)
add_test(NAME sdk_consumer COMMAND sdk_consumer)
