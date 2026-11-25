#include <iostream>
#include <string>
#include "probe.h"

#include "base/files/file_util.h"
#include "base/files/scoped_temp_dir.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/location.h"
#include "base/run_loop.h"
#include "base/strings/string_util.h"
#include "base/task/single_thread_task_executor.h"
#include "base/task/single_thread_task_runner.h"

int main() {
  const auto json = base::JSONReader::ReadDict(R"({"name":"Chromium base"})",
                                              base::JSON_PARSE_RFC);
  if (!json || !json->FindString("name")) return 1;
  const auto name = SdkUpper(*json->FindString("name"));
  base::ScopedTempDir directory;
  if (!directory.CreateUniqueTempDir()) return 2;
  const auto file = directory.GetPath().AppendASCII("sdk.txt");
  if (!base::WriteFile(file, name)) return 3;
  std::string content;
  if (!base::ReadFileToString(file, &content) || content != "CHROMIUM BASE") return 4;
  base::SingleThreadTaskExecutor executor;
  base::RunLoop loop;
  bool ran = false;
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce([](bool* flag, base::OnceClosure quit) {
        *flag = true;
        std::move(quit).Run();
      }, &ran, loop.QuitClosure()));
  loop.Run();
  if (!ran) return 5;
  std::cout << content << ": JSON, files, task runner OK\n";
  return 0;
}
