"""Apply settings to an active Codex turn through the local app-server proxy."""
import base64
import hashlib
import json
import os
import secrets
import select
import struct
import subprocess
import time


def _read(fd, size, deadline):
    chunks = bytearray()
    while len(chunks) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError
        chunk = os.read(fd, size - len(chunks))
        if not chunk:
            raise EOFError
        chunks.extend(chunk)
    return bytes(chunks)


def _send(fd, value):
    data = json.dumps(value, separators=(",", ":")).encode()
    mask = secrets.token_bytes(4)
    size = len(data)
    if size < 126:
        header = bytes((0x81, 0x80 | size))
    elif size < 65536:
        header = bytes((0x81, 0xfe)) + struct.pack("!H", size)
    else:
        header = bytes((0x81, 0xff)) + struct.pack("!Q", size)
    frame = header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    os.write(fd, frame)


def _receive(fd, deadline):
    first, second = _read(fd, 2, deadline)
    opcode, size = first & 0x0f, second & 0x7f
    if size == 126:
        size = struct.unpack("!H", _read(fd, 2, deadline))[0]
    elif size == 127:
        size = struct.unpack("!Q", _read(fd, 8, deadline))[0]
    if size > 1_000_000:
        raise ValueError("oversized app-server frame")
    mask = _read(fd, 4, deadline) if second & 0x80 else None
    data = _read(fd, size, deadline)
    if mask:
        data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    if opcode == 0x8:
        raise EOFError
    if opcode == 0x9:
        raise ValueError("unexpected app-server ping")
    if opcode != 0x1:
        raise ValueError("unexpected app-server frame")
    return json.loads(data)


def _response(fd, request_id, deadline):
    while True:
        message = _receive(fd, deadline)
        if message.get("id") == request_id:
            if "error" in message or "result" not in message:
                return None
            return message["result"]


def apply_turn_settings(thread_id, turn_id, model, effort=None, *, timeout_s=2.0, _proxy_command=None):
    """Return True only when the app-server confirms settings were applied to this turn."""
    if not all(isinstance(value, str) and value and len(value) <= 256
               for value in (thread_id, turn_id, model)):
        return False
    if effort is not None and (not isinstance(effort, str) or len(effort) > 32):
        return False
    process = None
    deadline = time.monotonic() + max(0.05, min(float(timeout_s), 2.0))
    try:
        process = subprocess.Popen(_proxy_command or ["codex", "app-server", "proxy"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        read_fd, write_fd = process.stdout.fileno(), process.stdin.fileno()
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = ("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode("ascii")
        os.write(write_fd, request)
        response = bytearray()
        while not response.endswith(b"\r\n\r\n"):
            response.extend(_read(read_fd, 1, deadline))
            if len(response) > 8192:
                return False
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest())
        lines = response.decode("ascii").split("\r\n")
        headers = {line.partition(":")[0].lower(): line.partition(":")[2].strip()
                   for line in lines[1:] if ":" in line}
        if not lines[0].startswith("HTTP/1.1 101 ") or headers.get("sec-websocket-accept") != accept.decode("ascii"):
            return False

        _send(write_fd, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "model-effort-router", "version": "1"},
            "capabilities": {"experimentalApi": True}}})
        if _response(read_fd, 1, deadline) is None:
            return False
        _send(write_fd, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        params = {"threadId": thread_id, "turnId": turn_id, "model": model}
        if effort is not None:
            params["effort"] = effort
        _send(write_fd, {"jsonrpc": "2.0", "id": 2, "method": "turn/settings/update", "params": params})
        result = _response(read_fd, 2, deadline)
        return isinstance(result, dict) and result.get("status") == "applied"
    except Exception:
        return False
    finally:
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()
