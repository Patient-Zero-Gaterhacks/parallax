"""Test startup in isolated copies, without touching the user's .env or keys."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DotenvStartup(unittest.TestCase):
    def test_entry_points_and_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT / "parallax", root / "parallax", ignore=shutil.ignore_patterns("__pycache__"))
            env = {k: v for k, v in os.environ.items() if not k.startswith(("PARALLAX_", "GEMINI_", "GOOGLE_", "CONTENT_SAFETY_"))}
            env["PYTHONPATH"] = str(root)
            # Startup must find the repository .env even from another working directory.
            cwd = root / "elsewhere"
            cwd.mkdir()
            code = "from parallax.server import DETECTORS, PUBLIC; import json; print(json.dumps([[d.name for d in DETECTORS], PUBLIC]))"

            def run(code, extra=None):
                return json.loads(subprocess.check_output([sys.executable, "-c", code], cwd=cwd, env={**env, **(extra or {})}, text=True).strip())

            baseline = run(code)
            self.assertIn("parallax-ml", baseline[0])  # missing .env is fine
            (root / ".env").write_text("PARALLAX_ML=0\nPARALLAX_PUBLIC=1\n")
            loaded = run(code)
            self.assertNotIn("parallax-ml", loaded[0])
            self.assertTrue(loaded[1])
            explicit = run(code, {"PARALLAX_ML": "1", "PARALLAX_PUBLIC": "0"})
            self.assertIn("parallax-ml", explicit[0])
            self.assertFalse(explicit[1])
            gateway = run("import parallax.mcp_gateway.__main__; from parallax.detect import default_detectors; import json; print(json.dumps([d.name for d in default_detectors()]))")
            self.assertNotIn("parallax-ml", gateway)


if __name__ == "__main__":
    unittest.main()
