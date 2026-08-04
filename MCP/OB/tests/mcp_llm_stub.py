"""Deterministic OpenAI-compatible stub used by Docker MCP integration tests."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time


def _completion(system: str, user: str) -> str:
    if user.startswith("PLAN:\n"):
        payload = {"resolved": False, "confidence": 0.0, "reason": "docker stub"}
    elif "日记整理专家" in system:
        payload = [
            {
                "name": "docker-grow-one",
                "content": f"{user.strip()}\n[docker split 1]",
                "domain": ["integration"],
                "valence": 0.6,
                "arousal": 0.4,
                "tags": ["docker", "mcp"],
                "importance": 6,
            },
            {
                "name": "docker-grow-two",
                "content": "Docker integration second split",
                "domain": ["integration"],
                "valence": 0.5,
                "arousal": 0.3,
                "tags": ["docker", "mcp"],
                "importance": 5,
            },
        ]
    elif "内容分析器" in system:
        payload = {
            "domain": ["integration"],
            "valence": 0.6,
            "arousal": 0.4,
            "tags": ["docker", "mcp"],
            "suggested_name": "docker-memory",
            "importance": 6,
        }
    elif "计划" in system or "plan" in system.lower():
        payload = {"resolved": False, "confidence": 0.0, "reason": "docker stub"}
    else:
        payload = {
            "core_facts": [user.strip()[:120]],
            "todos": [],
            "summary": user.strip()[:120],
        }
    return json.dumps(payload, ensure_ascii=False)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        messages = request.get("messages") or []
        system = str(messages[0].get("content") or "") if messages else ""
        user = str(messages[-1].get("content") or "") if messages else ""
        content = _completion(system, user)
        response = {
            "id": "chatcmpl-ombre-docker",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.get("model") or "ombre-stub",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        body = json.dumps(response, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
