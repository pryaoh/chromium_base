# Attach SDK runtime deployment to an executable in the caller's directory.
# Static SDKs have no runtime files, so the same call works for either linkage.
function(chromium_base_deploy_runtime target)
  if(NOT TARGET "${target}")
    message(FATAL_ERROR "Unknown executable target: ${target}")
  endif()
  get_target_property(_cb_type "${target}" TYPE)
  if(NOT _cb_type STREQUAL "EXECUTABLE")
    message(FATAL_ERROR "chromium_base_deploy_runtime expects an executable")
  endif()
  get_target_property(_cb_runtime ChromiumBase::base CHROMIUM_BASE_RUNTIME_FILES)
  if(_cb_runtime)
    add_custom_command(TARGET "${target}" POST_BUILD
      COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        ${_cb_runtime} "$<TARGET_FILE_DIR:${target}>"
      COMMAND_EXPAND_LISTS VERBATIM
    )
  endif()
endfunction()
