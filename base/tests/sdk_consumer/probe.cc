#include "probe.h"
#include "base/strings/string_util.h"

std::string SdkUpper(const std::string& value) {
  return base::ToUpperASCII(value);
}
