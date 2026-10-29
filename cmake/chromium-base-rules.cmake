# lld-link dispatches to its librarian only when /lib is the FIRST argument.
foreach(_cb_language C CXX)
  set(CMAKE_${_cb_language}_CREATE_STATIC_LIBRARY
      "<CMAKE_AR> /lib /nologo <LINK_FLAGS> /out:<TARGET> <OBJECTS>")
endforeach()
unset(_cb_language)
