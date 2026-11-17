import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows batch encoding regression")
class BatchEncodingTest(unittest.TestCase):
    def test_start_batch_decodes_tailscale_json(self):
        source = Path(__file__).resolve().parents[1] / "start_edge.bat"
        batch = source.read_text(encoding="utf-8")
        self.assertIn("uv run main.py", batch)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            probe = folder / "probe.py"
            probe.write_text(
                "import subprocess, json\n"
                "r = subprocess.run(['tailscale','status','--json'], capture_output=True, text=True, timeout=8)\n"
                "assert r.returncode == 0 and r.stdout\n"
                "assert json.loads(r.stdout)['Self']\n",
                encoding="utf-8",
            )
            batch = batch.replace("uv run main.py", f'"{sys.executable}" "{probe}"')
            wrapper = folder / "probe.bat"
            wrapper.write_text(batch, encoding="utf-8")
            env = dict(os.environ)
            env.pop("PYTHONUTF8", None)
            result = subprocess.run(["cmd", "/c", str(wrapper)], env=env, capture_output=True, text=True, errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout[-500:] + result.stderr[-500:])
