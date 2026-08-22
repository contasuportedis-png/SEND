#!/usr/bin/env python3
"""Testes do cadastro e da troca de providers (sem acessar a rede)."""
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

    def test_custom_provider(self):
        cfg = send.load_config()
        answers = iter(["Minha API", "https://example.test/api"])
        with mock.patch("send.getpass.getpass", return_value="custom-secret"):
            provider_id = send.configure_provider(
                cfg, "custom", send.C(False), input_fn=lambda _prompt: next(answers)
            )
        self.assertEqual(provider_id, "minha-api")
        self.assertEqual(cfg["base_url"], "https://example.test/api")
        self.assertEqual(send.provider_api_key(cfg), "custom-secret")


if __name__ == "__main__":
    unittest.main()
