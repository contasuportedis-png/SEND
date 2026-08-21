#!/usr/bin/env python3
"""Servidor LM Studio simulado para testar o SEND (porta 1234)."""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MODELS = [
    {"id": "qwen2.5-coder-7b", "object": "model", "owned_by": "mock"},
    {"id": "deepseek-r1-distill", "object": "model", "owned_by": "mock"},
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._json({"object": "list", "data": MODELS})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        msgs = payload.get("messages", [])
        user_text = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        last = msgs[-1] if msgs else {}
        tools = payload.get("tools")
        thinking = bool(payload.get("reasoning_effort"))

        # Já existe resultado de ferramenta? Então é a rodada final.
        if last.get("role") == "tool":
            content = ("O arquivo README.md foi lido com sucesso. "
                       "Ele documenta o projeto SEND.")
            event = {"choices": [{"index": 0, "delta": {"content": content}}]}
        # Simula o modelo chamando a ferramenta read_file
        elif tools and "leia o arquivo" in user_text.lower():
            event = {
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_mock1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "README.md"}',
                            },
                        }]
                    },
                }]
            }
        else:
            answer = "Olá! Este é o modelo simulado. " + user_text
            if "plano" in user_text.lower():
                answer = ("PLANO:\n1. Analisar o projeto\n2. Criar arquivos\n"
                          "3. Testar\nDeseja que eu execute?")
            event = {
                "choices": [{"index": 0, "delta": {"content": answer}}]
            }

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(data):
            self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        if thinking:
            emit({"choices": [{"index": 0, "delta": {"reasoning_content": "Raciocinando..."}}]})
            time.sleep(0.1)
        if "content" in event["choices"][0]["delta"]:
            content = event["choices"][0]["delta"]["content"]
            for chunk in [content[:5], content[5:]]:
                evt = {"choices": [{"index": 0, "delta": {"content": chunk}}]}
                emit(evt)
                time.sleep(0.05)
        else:
            emit(event)
        emit({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    print("Mock LM Studio em http://127.0.0.1:1234")
    HTTPServer(("127.0.0.1", 1234), Handler).serve_forever()
