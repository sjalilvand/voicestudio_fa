import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "OmniVoice_Studio_Colab.ipynb"


class ColabWebBuildTests(unittest.TestCase):
    def build_source(self):
        cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
        source = next("".join(c["source"]) for c in cells
                      if "# 2d." in "".join(c["source"]))
        return source[source.index("# 2d."):source.index("# 2e.")]

    def run_build(self, exists):
        calls = []
        with patch("os.path.exists", side_effect=exists):
            exec(self.build_source(), {
                "os": os, "REPO_DIR": "/content/VoiceStudio", "BUN": "bun",
                "run": lambda cmd, **kwargs: calls.append((cmd, kwargs)),
            })
        return calls

    def test_clean_runtime_builds_electron_web_renderer(self):
        calls = self.run_build([False, True])
        self.assertEqual([cmd for cmd, _ in calls], [
            ["bun", "install", "--frozen-lockfile"],
            ["bun", "run", "--cwd", "electron", "build:web"],
        ])
        self.assertTrue(all(opts["cwd"] == "/content/VoiceStudio" for _, opts in calls))

    def test_existing_bundle_skips_install_and_build(self):
        self.assertEqual(self.run_build([True]), [])

    def test_missing_build_output_stops_setup(self):
        with self.assertRaisesRegex(SystemExit, "frontend/dist/index.html is missing"):
            self.run_build([False, False])


# CLEAN-ROOM (spec P-pr1874 §8): ASR-setup test class (setup cell contents, rerun behaviour, failure resets ready flag, gating of cells 13 and 18, ordering, prefetch-before-launch) goes here.



class ColabLicenceErrorTests(unittest.TestCase):
    """Model-licence 403s read as a licence problem, not a download/GPU failure (#3076)."""

    BODY = {"detail": {"code": "model_licence_required", "message": "Accept the licence.",
                       "models": [{"repo_id": "org/model-a"}]}}

    def cell(self, marker):
        cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
        return next("".join(c["source"]) for c in cells
                    if c["cell_type"] == "code" and marker in "".join(c["source"]))

    def helpers(self):
        src = self.cell("def api_fail")
        ns = {"json": json, "LOG_HINT": "LOG"}
        exec(src[src.index("def _error_detail"):src.index("def speak")], ns)
        return ns

    def test_api_fail_names_licence_and_models(self):
        resp = types.SimpleNamespace(status_code=403, text=json.dumps(self.BODY),
                                     json=lambda: self.BODY)
        with self.assertRaisesRegex(SystemExit, r"model licence not accepted[\s\S]*org/model-a[\s\S]*cell 6[\s\S]*Model Catalogue"):
            self.helpers()["api_fail"](resp, "/generate")

    def test_api_fail_keeps_plain_http_errors(self):
        def not_json():
            raise ValueError("not json")
        resp = types.SimpleNamespace(status_code=500, text="boom", json=not_json)
        with self.assertRaisesRegex(SystemExit, r"HTTP 500\nboom") as cm:
            self.helpers()["api_fail"](resp, "/generate")
        self.assertNotIn("licence", str(cm.exception))

    def run_smoke(self, body, code):
        import io
        import urllib.error

        def urlopen(req, timeout=None):
            if isinstance(req, str):
                return io.BytesIO(b"{}")
            raise urllib.error.HTTPError(
                "http://x/generate", code, "err", {}, io.BytesIO(body.encode()))
        with patch("urllib.request.urlopen", side_effect=urlopen):
            exec(self.cell("# ── 7. Smoke test"), {})

    def test_smoke_cell_names_licence(self):
        with self.assertRaisesRegex(SystemExit, r"model licence not accepted[\s\S]*org/model-a[\s\S]*cell 6[\s\S]*Model Catalogue"):
            self.run_smoke(json.dumps(self.BODY), 403)

    def test_smoke_cell_keeps_plain_http_errors(self):
        with self.assertRaisesRegex(SystemExit, r"HTTP 500\nboom") as cm:
            self.run_smoke("boom", 500)
        self.assertNotIn("licence", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
