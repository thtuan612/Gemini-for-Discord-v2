
class ConfigTests(unittest.TestCase):
    def test_defaults_and_order(self):
        self.assertTrue(config.GEMINI_ENABLED)
        self.assertEqual(config.GEMINI_MODELS[0], config.GEMINI_MODEL)
        self.assertEqual(sorted(config.AI_PROVIDER_ORDER), ["gemini", "literouter"])
        self.assertFalse(config.CHAT_INCLUDE_CHANNEL_CONTEXT)
        self.assertFalse(config.LITEROUTER_ENABLED)
        self.assertEqual(config.LITEROUTER_BASE_URL, "https://literouter.fun/api/v1")

    def test_gemini_model_accepts_comma_list(self):
        # Trường hợp thực tế: người dùng điền cả danh sách vào GEMINI_MODEL.
        import subprocess

        env = {**os.environ, "GEMINI_MODEL": "m1, m2 ,m3", "GEMINI_FALLBACK_MODELS": "m3,m4"}
        code = "import json, config as c; print(json.dumps([c.GEMINI_MODEL, c.GEMINI_MODELS]))"
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True)
        main, models = json.loads(out.stdout)
        self.assertEqual(main, "m1")
        self.assertEqual(models, ["m1", "m2", "m3", "m4"])

        env["GEMINI_MODEL"] = ""
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, check=True)
        main, models = json.loads(out.stdout)