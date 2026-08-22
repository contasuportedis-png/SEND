#!/usr/bin/env python3
"""Testes do cadastro e da troca de providers (sem acessar a rede)."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import send


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = send.SEND_HOME
        self.old_config = send.CONFIG_PATH
        send.SEND_HOME = Path(self.tmp.name)
        send.CONFIG_PATH = send.SEND_HOME / "config.json"

    def tearDown(self):
        send.SEND_HOME = self.old_home
        send.CONFIG_PATH = self.old_config
        self.tmp.cleanup()

    def test_presets_and_model_are_kept_separately(self):
        cfg = send.load_config()
        send.activate_provider(cfg, "openai")
        cfg["model"] = "gpt-test"
        cfg.setdefault("providers", {}).setdefault("openai", {})["model"] = "gpt-test"
        send.activate_provider(cfg, "claude")
        self.assertIsNone(cfg["model"])
        send.activate_provider(cfg, "openai")
        self.assertEqual(cfg["model"], "gpt-test")
        self.assertEqual(cfg["base_url"], "https://api.openai.com")

    def test_provider_environment_key_is_not_persisted(self):
        cfg = send.load_config()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "secret-from-env"}):
            send.activate_provider(cfg, "openai")
            self.assertEqual(send.provider_api_key(cfg), "secret-from-env")
            self.assertEqual(cfg["api_key"], "")
            send.save_config(cfg)
        self.assertNotIn("secret-from-env", send.CONFIG_PATH.read_text(encoding="utf-8"))

    def test_all_documented_presets_are_available(self):
        required = {
            "ollama", "lmstudio", "claude", "openai", "nvidia", "gemini",
            "mistral", "groq", "cohere", "together", "perplexity",
            "deepseek", "xai", "openrouter", "azure", "bedrock",
            "huggingface",
        }
        self.assertTrue(required.issubset(send.PROVIDER_PRESETS))

    def test_provider_specific_api_paths(self):
        cfg = send.load_config()
        send.activate_provider(cfg, "openai")
        self.assertEqual(send.provider_api_url(cfg, "models"),
                         "https://api.openai.com/v1/models")
        send.activate_provider(cfg, "gemini")
        self.assertEqual(
            send.provider_api_url(cfg, "chat/completions"),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        send.activate_provider(cfg, "perplexity")
        self.assertEqual(send.provider_api_url(cfg, "chat/completions"),
                         "https://api.perplexity.ai/chat/completions")

    def test_anthropic_payload_conversion(self):
        payload = {
            "model": "claude-test", "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "Ajude."},
                {"role": "user", "content": "Oi"},
            ],
            "tools": [{"type": "function", "function": {
                "name": "read_file", "description": "Lê",
                "parameters": {"type": "object", "properties": {}},
            }}],
        }
        converted = send._anthropic_payload(payload)
        self.assertEqual(converted["system"], "Ajude.")
        self.assertEqual(converted["tools"][0]["name"], "read_file")
        self.assertEqual(converted["messages"][0]["role"], "user")

    def test_anthropic_stream_conversion(self):
        events = [
            '{"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"Olá"}}',
            '{"type":"content_block_start","index":1,"content_block":'
            '{"type":"tool_use","id":"tool_1","name":"read_file","input":{}}}',
            '{"type":"content_block_delta","index":1,'
            '"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"a.txt\\"}"}}',
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            content, calls, _ = send._consume_stream(events, send.C(False),
                                                      send.load_config())
        self.assertEqual(content, "Olá")
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(calls[0]["function"]["arguments"], '{"path":"a.txt"}')

    def test_slash_autocomplete_filters_commands(self):
        self.assertEqual(send._command_completer("/prov", 0), "/provider")
        model_matches = []
        state = 0
        while True:
            value = send._command_completer("/m", state)
            if value is None:
                break
            model_matches.append(value)
            state += 1
        self.assertIn("/model", model_matches)

    def test_custom_provider(self):
        cfg = send.load_config()
        answers = iter(["Minha API", "https://example.test/api", "openai"])
        with mock.patch("send.getpass.getpass", return_value="custom-secret"):
            provider_id = send.configure_provider(
                cfg, "custom", send.C(False), input_fn=lambda _prompt: next(answers)
            )
        self.assertEqual(provider_id, "minha-api")
        self.assertEqual(cfg["base_url"], "https://example.test/api")
        self.assertEqual(send.provider_api_key(cfg), "custom-secret")


if __name__ == "__main__":
    unittest.main()
