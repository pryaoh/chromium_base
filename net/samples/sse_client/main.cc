#include <iostream>
#include <string>
#include <string_view>

#include "base/at_exit.h"
#include "base/command_line.h"
#include "base/feature_list.h"
#include "base/i18n/icu_util.h"
#include "base/memory/ref_counted.h"
#include "base/run_loop.h"
#include "base/strings/string_util.h"
#include "base/task/single_thread_task_executor.h"
#include "base/task/thread_pool/thread_pool_instance.h"
#include "net/base/io_buffer.h"
#include "net/base/isolation_info.h"
#include "net/base/net_errors.h"
#include "net/proxy_resolution/configured_proxy_resolution_service.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "net/url_request/url_request.h"
#include "net/url_request/url_request_context.h"
#include "net/url_request/url_request_context_builder.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace {

// Print each complete event's data, including newlines between data fields.
// A line, its delimiter, and an event can each span multiple URLRequest reads.
class EventPrinter {
 public:
  bool Consume(std::string_view bytes) {
    for (char c : bytes) {
      if (after_cr_ && c == '\n') {
        after_cr_ = false;
        continue;
      }
      after_cr_ = c == '\r';
      if (after_cr_ || c == '\n') {
        if (!FinishLine()) {
          return false;
        }
        line_.clear();
      } else {
        if (line_.size() == kLimit) {
          return false;
        }
        line_.push_back(c);
      }
    }
    return true;
  }

 private:
  bool FinishLine() {
    std::string_view line(line_);
    if (first_line_) {
      first_line_ = false;
      if (line.starts_with("\xef\xbb\xbf")) {
        line.remove_prefix(3);
      }
    }
    if (line.empty()) {
      if (!data_.empty()) {
        std::cout << data_ << std::flush;
        data_.clear();
      }
      return true;
    }
    auto colon = line.find(':');
    if (line.substr(0, colon) == "data") {
      auto value =
          colon == line.npos ? std::string_view() : line.substr(colon + 1);
      if (value.starts_with(' ')) {
        value.remove_prefix(1);
      }
      if (data_.size() + value.size() + 1 > kLimit) {
        return false;
      }
      data_.append(value);
      data_.push_back('\n');
    }
    return true;
  }

  static constexpr size_t kLimit = 1024 * 1024;
  std::string line_;
  std::string data_;
  bool first_line_ = true;
  bool after_cr_ = false;
};

class StreamDelegate : public net::URLRequest::Delegate {
 public:
  int Wait() {
    loop_.Run();
    return result_;
  }

  void OnResponseStarted(net::URLRequest* request, int net_error) override {
    if (net_error != net::OK) {
      Finish(net_error);
      return;
    }
    std::string mime;
    request->GetMimeType(&mime);
    if (request->GetResponseCode() != 200 ||
        !base::EqualsCaseInsensitiveASCII(mime, "text/event-stream")) {
      std::cerr << "Expected an SSE response, got HTTP "
                << request->GetResponseCode() << " with media type '" << mime
                << "'.\n";
      Finish(net::ERR_INVALID_RESPONSE);
      return;
    }
    Drain(request, request->Read(buffer_.get(), buffer_->size()));
  }

  void OnReadCompleted(net::URLRequest* request, int bytes_read) override {
    Drain(request, bytes_read);
  }

 private:
  void Drain(net::URLRequest* request, int bytes_read) {
    while (bytes_read > 0) {
      if (!printer_.Consume(std::string_view(buffer_->data(), bytes_read))) {
        std::cerr << "SSE line or event exceeds the sample's 1 MiB limit.\n";
        Finish(net::ERR_FILE_TOO_BIG);
        return;
      }
      bytes_read = request->Read(buffer_.get(), buffer_->size());
    }
    // For a pending read Chromium resumes us in OnReadCompleted. Zero is EOF.
    if (bytes_read != net::ERR_IO_PENDING) {
      Finish(bytes_read);
    }
  }

  void Finish(int error) {
    if (error != net::OK) {
      std::cerr << net::ErrorToString(error) << '\n';
    }
    result_ = error == net::OK ? 0 : 1;
    loop_.Quit();
  }

  base::RunLoop loop_;
  scoped_refptr<net::IOBufferWithSize> buffer_ =
      base::MakeRefCounted<net::IOBufferWithSize>(4096);
  EventPrinter printer_;
  int result_ = 1;
};

int Stream(const GURL& url) {
  net::URLRequestContextBuilder builder;
  builder.DisableHttpCache();
  builder.set_proxy_resolution_service(
      net::ConfiguredProxyResolutionService::CreateDirect());
  auto context = builder.Build();
  StreamDelegate delegate;
  constexpr auto annotation =
      net::DefineNetworkTrafficAnnotation("sse_client_sample", R"(
    semantics {
      sender: "Chromium Net SDK SSE sample"
      description: "Reads server-sent events and prints each event's data."
      trigger: "The user supplies an event stream URL on the command line."
      data: "The URL provided by the user."
      destination: OTHER
      destination_other: "The host in the URL."
    }
    policy {
      cookies_allowed: NO
      setting: "Launched explicitly by the user."
      policy_exception_justification: "Standalone command-line sample."
    })");
  auto request =
      context->CreateRequest(url, net::DEFAULT_PRIORITY, &delegate, annotation,
                             net::handles::kInvalidNetworkHandle);
  request->set_isolation_info(
      net::IsolationInfo::CreateForInternalRequest(url::Origin::Create(url)));
  request->set_disallow_credentials();
  request->SetExtraRequestHeaderByName("Accept", "text/event-stream", true);
  request->Start();
  return delegate.Wait();
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc != 2) {
    std::cerr << "Usage: sse_client <http-or-https-url>\n";
    return 2;
  }
  base::AtExitManager at_exit;
  base::CommandLine::Init(argc, argv);
  base::FeatureList::InitInstance("", "");
  if (!base::i18n::InitializeICU()) {
    std::cerr << "Could not initialize ICU.\n";
    return 1;
  }
  GURL url(argv[1]);
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS()) {
    std::cerr << "Expected an absolute HTTP or HTTPS URL.\n";
    return 2;
  }
  base::SingleThreadTaskExecutor io(base::MessagePumpType::IO);
  base::ThreadPoolInstance::CreateAndStartWithDefaultParams("SseClient");
  int result = Stream(url);
  base::ThreadPoolInstance::Get()->Shutdown();
  return result;
}
