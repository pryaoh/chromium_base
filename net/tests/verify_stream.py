"""Exercise the packaged native SSE client against a gated loopback response."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
from threading import Event, Thread


def verify(client_command: list[str], timeout: float = 20) -> None:
    first_printed = Event()
    second_sent = Event()

    class StreamHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/events" or self.headers.get("Accept") != "text/event-stream":
                self.send_error(400)
                return
            # A comment larger than the client's read buffer forces a split line.
            first = b"\xef\xbb\xbf:" + b"x" * 5000 + b"\r\ndata: first\r\n\r\n"
            second = b"data: second\rdata: piece\r\rdata: unfinished"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Content-Length", str(len(first) + len(second)))
            self.end_headers()
            self.wfile.write(first)
            self.wfile.flush()
            if first_printed.wait(timeout):
                self.wfile.write(second)
                self.wfile.flush()
                second_sent.set()

        def log_message(self, format, *args):
            pass

    output = []

    def read_output(pipe):
        for line in pipe:
            output.append(line)
            if output == ["first\n"]:
                first_printed.set()

    with ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler) as server:
        serving = Thread(target=server.serve_forever)
        serving.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/events"
            with subprocess.Popen([*client_command, url], stdout=subprocess.PIPE,
                                  text=True, encoding="utf-8") as client:
                reader = Thread(target=read_output, args=(client.stdout,))
                reader.start()
                try:
                    code = client.wait(timeout=timeout + 5)
                finally:
                    if client.poll() is None:
                        client.kill()
                    client.wait()
                    reader.join()
            if not second_sent.wait(0.5) or output != ["first\n", "second\n", "piece\n"] or code:
                raise RuntimeError(f"stream check failed (exit {code}, "
                                   f"second sent {second_sent.is_set()}, output {output!r})")
        finally:
            server.shutdown()
            serving.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", type=Path, help="path to the built sse_client executable")
    args = parser.parse_args()
    verify([str(args.client.resolve(strict=True))])
    print("Received the first SSE event before the server released the second.")
