#include <iostream>
#include <string>

#include "base/at_exit.h"
#include "base/command_line.h"
#include "base/json/json_writer.h"
#include "base/strings/strcat.h"
#include "base/strings/string_util.h"
#include "base/values.h"

int main(int argc, char* argv[]) {
  // Keep process-wide base objects alive until the program exits.
  base::AtExitManager at_exit;
  base::CommandLine::Init(argc, argv);
  const auto& command_line = *base::CommandLine::ForCurrentProcess();

  if (command_line.HasSwitch("help")) {
    std::cout << "Usage: hello_base [--name=World] [--help]\n"
                 "Print a greeting as UTF-8 JSON using Chromium base.\n";
    return 0;
  }

  std::string name = command_line.GetSwitchValueUTF8("name");
  if (name.empty()) {
    name = "World";
  }

  base::DictValue message;
  message.Set("greeting", base::StrCat({"Hello, ", name, "!"}));
  // ToUpperASCII changes only a-z; non-ASCII characters are preserved.
  message.Set("upper_name", base::ToUpperASCII(name));

  const auto json = base::WriteJson(message);
  if (!json) {
    std::cerr << "Could not serialize the greeting.\n";
    return 1;
  }
  std::cout << *json << '\n';
  return 0;
}
