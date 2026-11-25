find_package(ChromiumBase CONFIG REQUIRED)
add_library(sdk_probe STATIC ../probe.cc)
target_link_libraries(sdk_probe PUBLIC ChromiumBase::base)
