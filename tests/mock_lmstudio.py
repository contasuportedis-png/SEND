#!/usr/bin/env python3
"""Servidor LM Studio simulado para testar o SEND (porta 1234)."""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MODELS = [
    {"id": "qwen2.5-coder-7b", "object": "model", "owned_by": "mock"},
    {"id": "deepseek-r1-distill", "object": "model", "owned_by": "mock"},
]


class _ClientGone(Exception):
    """Cliente fechou a conexão no meio do stream — ignora e segue."""


def _safe_emit(self, data):
    try:
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        raise _ClientGone

# Mapa: ferramenta -> (id do call, argumentos)
TOOL_PLAN = {
    "pesquise na internet": ("call_search", "web_search",
                             '{"query": "inteligencia artificial local", "max_results": 3}'),
    "informacoes do pc": ("call_sys", "system_info", "{}"),
    "edite o arquivo": ("call_edit", "edit_file",
                        '{"path": "notas.txt", "old_text": "velho", "new_text": "novo"}'),
    "liste os arquivos": ("call_list", "list_files", '{"path": "."}'),
    "procure": ("call_find", "find_files", '{"pattern": "*.md"}'),
    "status do git": ("call_git", "git_status", "{}"),
    "lista de processos": ("call_ps", "list_processes",
                           '{"filter": "python", "n": 5}'),
    "lembre que": ("call_rem", "remember",
                   '{"content": "O usuário prefere Python e respostas curtas."}'),
    "crie uma skill": ("call_cskill", "create_skill",
                       '{"name": "formatar", "description": "formata codigo", '
                       '"instructions": "Formate o codigo com 4 espacos."}'),
    "leia a memoria": ("call_mem", "read_memory", "{}"),
    "delegue": ("call_delegate", "delegate",
                '{"nome": "revisor", "tarefa": "revise o codigo"}'),
    "crie um subagente": ("call_csub", "create_subagent",
                          '{"nome": "tradutor", "descricao": "traduz texto", '
                          '"instrucoes": "Traduza para ingles."}'),
}


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
        system = msgs[0].get("content", "") if msgs else ""
        user_text = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        last = msgs[-1] if msgs else {}
        tools = payload.get("tools") or []
        thinking = bool(payload.get("reasoning_effort"))
        tool_names = [t["function"]["name"] for t in tools] if tools else []

        # ---- Estágios do workflow ----
        if "ETAPA 1 (PLANEJAR)" in system:
            answer = ("PLANO:\n1. Criar o arquivo app.py\n2. Escrever o codigo\n"
                      "3. Rodar o codigo\n4. Testar\nDeseja que eu execute?")
            event = {"choices": [{"index": 0, "delta": {"content": answer}}]}
        elif "ETAPA 3 (VERIFICAR)" in system:
            answer = "VERIFICAÇÃO OK: o codigo roda e os testes passaram."
            event = {"choices": [{"index": 0, "delta": {"content": answer}}]}
        elif "ETAPA 4 (CORRIGIR)" in system:
            answer = "Corrigido: ajustei a indentacao do arquivo app.py."
            event = {"choices": [{"index": 0, "delta": {"content": answer}}]}
        # ---- Depois de uma ferramenta executada: responde o resultado ----
        elif last.get("role") == "tool":
            content = ("Resultado da ferramenta recebido. Consegui a "
                       "informação que você pediu. " + user_text[:80])
            event = {"choices": [{"index": 0, "delta": {"content": content}}]}
        else:
            # ---- Decide qual ferramenta chamar (se estiver disponível) ----
            call_info = None
            for key, (cid, fname, fargs) in TOOL_PLAN.items():
                if key in user_text.lower() and fname in tool_names:
                    call_info = (cid, fname, fargs)
                    break
            if call_info is None and "leia o arquivo" in user_text.lower() and "read_file" in tool_names:
                call_info = ("call_read", "read_file", '{"path": "README.md"}')

            if call_info:
                cid, fname, fargs = call_info
                event = {
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "id": cid,
                                "function": {"name": fname, "arguments": fargs},
                            }]
                        },
                    }]
                }
            else:
                answer = "Olá! Este é o modelo simulado. " + user_text[:80]
                event = {"choices": [{"index": 0, "delta": {"content": answer}}]}

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()


        try:
            if thinking:
                _safe_emit(self, {"choices": [{"index": 0, "delta": {"reasoning_content": "Raciocinando..."}}]})
                time.sleep(0.1)
            if "content" in event["choices"][0]["delta"]:
                content = event["choices"][0]["delta"]["content"]
                for chunk in [content[:5], content[5:]]:
                    evt = {"choices": [{"index": 0, "delta": {"content": chunk}}]}
                    _safe_emit(self, evt)
                    time.sleep(0.05)
            else:
                _safe_emit(self, event)
            _safe_emit(self, {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except _ClientGone:
            pass


if __name__ == "__main__":
    print("Mock LM Studio em http://127.0.0.1:1234")
    HTTPServer(("127.0.0.1", 1234), Handler).serve_forever()
