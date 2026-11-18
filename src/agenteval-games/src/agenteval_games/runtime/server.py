"""One immutable episode per sidecar; only public observations leave it."""

import argparse
import base64
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .engine import Session


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


class GameServer(ThreadingHTTPServer):
    def __init__(self, address, session, key_dir):
        self.session = session
        self.lock = threading.Lock()
        self.key = Ed25519PrivateKey.generate()
        key_dir = Path(key_dir)
        key_dir.mkdir(parents=True, exist_ok=True)
        public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        temporary = key_dir / "key.tmp"
        temporary.write_bytes(public)
        temporary.replace(key_dir / "key.pub")
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value):
        body = canonical(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with self.server.lock:
            if self.path == "/observation":
                return self.reply(200, self.server.session.public())
            if self.path == "/transcript":
                transcript = self.server.session.transcript()
                signature = self.server.key.sign(canonical(transcript))
                return self.reply(
                    200,
                    {
                        "transcript": transcript,
                        "signature": base64.b64encode(signature).decode(),
                    },
                )
        self.reply(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if self.path != "/step":
            return self.reply(404, {"error": "Unknown endpoint"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_048_576:
                raise ValueError("Invalid request length")
            body = json.loads(self.rfile.read(length))
            if (
                not isinstance(body, dict)
                or set(body) != {"action"}
                or not isinstance(body["action"], str)
            ):
                raise ValueError("Expected an action string")
            with self.server.lock:
                result = self.server.session.step(body["action"])
            self.reply(200, result)
        except (ValueError, UnicodeDecodeError) as error:
            self.reply(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/game/config.json")
    parser.add_argument("--data", default="/game/data")
    parser.add_argument("--key-dir", default="/game-public")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    session = Session(json.loads(Path(args.config).read_text()), args.data)
    GameServer(("0.0.0.0", args.port), session, args.key_dir).serve_forever()


if __name__ == "__main__":
    main()
