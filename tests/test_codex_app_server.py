import json
import sys
import unittest

from model_effort_router.host.codex_app_server import apply_turn_settings


FAKE_PROXY = r'''
import base64, hashlib, json, struct, sys
headers = b""
while b"\r\n\r\n" not in headers:
    headers += sys.stdin.buffer.read(1)
key = next(line.split(b":", 1)[1].strip() for line in headers.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key:"))
accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
sys.stdout.buffer.write(b"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
sys.stdout.buffer.flush()
def read_message():
    h = sys.stdin.buffer.read(2)
    n = h[1] & 127
    if n == 126: n = struct.unpack("!H", sys.stdin.buffer.read(2))[0]
    elif n == 127: n = struct.unpack("!Q", sys.stdin.buffer.read(8))[0]
    mask = sys.stdin.buffer.read(4)
    data = sys.stdin.buffer.read(n)
    return json.loads(bytes(byte ^ mask[i % 4] for i, byte in enumerate(data)))
def send(message):
    data = json.dumps(message, separators=(",", ":")).encode()
    mask = b""
    n = len(data)
    h = bytes([129, n]) if n < 126 else bytes([129, 126]) + struct.pack("!H", n)
    sys.stdout.buffer.write(h + data)
    sys.stdout.buffer.flush()
init = read_message()
assert init["method"] == "initialize" and init["params"]["capabilities"]["experimentalApi"] is True
send({"jsonrpc":"2.0", "id":init["id"], "result":{}})
assert read_message()["method"] == "initialized"
update = read_message()
assert update["method"] == "turn/settings/update"
assert update["params"] == {"threadId":"thread-1", "turnId":"turn-1", "model":"gpt-6-luna", "effort":"medium"}
send({"jsonrpc":"2.0", "id":update["id"], "result":{"status":"applied"}})
'''


class CodexAppServerTest(unittest.TestCase):
    def test_proxy_applies_matching_turn_settings(self):
        self.assertTrue(apply_turn_settings(
            "thread-1", "turn-1", "gpt-6-luna", "medium",
            timeout_s=2, _proxy_command=[sys.executable, "-c", FAKE_PROXY],
        ))

    def test_unavailable_turn_is_not_reported_as_applied(self):
        unavailable_proxy = FAKE_PROXY.replace('"status":"applied"', '"status":"targetUnavailable"')
        self.assertFalse(apply_turn_settings(
            "thread-1", "turn-1", "gpt-6-luna", "medium",
            timeout_s=2, _proxy_command=[sys.executable, "-c", unavailable_proxy],
        ))

    def test_protocol_error_is_not_reported_as_applied(self):
        error_proxy = FAKE_PROXY.replace(
            'send({"jsonrpc":"2.0", "id":update["id"], "result":{"status":"applied"}})',
            'send({"jsonrpc":"2.0", "id":update["id"], "error":{"code":-32600,"message":"rejected"}})',
        )
        self.assertFalse(apply_turn_settings(
            "thread-1", "turn-1", "gpt-6-luna", "medium",
            timeout_s=2, _proxy_command=[sys.executable, "-c", error_proxy],
        ))

    def test_mismatched_response_id_times_out(self):
        wrong_id_proxy = FAKE_PROXY.replace('"id":update["id"]', '"id":update["id"] + 1')
        self.assertFalse(apply_turn_settings(
            "thread-1", "turn-1", "gpt-6-luna", "medium",
            timeout_s=0.1, _proxy_command=[sys.executable, "-c", wrong_id_proxy],
        ))

    def test_proxy_timeout_is_bounded(self):
        self.assertFalse(apply_turn_settings(
            "thread-1", "turn-1", "gpt-6-luna", "medium", timeout_s=0.1,
            _proxy_command=[sys.executable, "-c", "import time; time.sleep(5)"],
        ))


if __name__ == "__main__":
    unittest.main()
