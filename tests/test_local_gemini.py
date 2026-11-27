import io
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import chdir, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from travel_app import config, create_app
from travel_app.models import Gemini, ModelError


class LocalGeminiTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        project = directory / "project"
        package = project / "travel_app"
        package.mkdir(parents=True)
        self.env_file = project / ".env"
        self.enterContext(patch.object(config, "__file__", str(package / "config.py")))
        foreign = directory / "foreign"
        foreign.mkdir()
        (foreign / ".env").write_text("GEMINI_API_KEY=foreign\nFOREIGN_ENV=leaked\n", encoding="utf-8")
        (foreign / ".flaskenv").write_text("FOREIGN_FLASKENV=leaked\n", encoding="utf-8")
        self.enterContext(chdir(foreign))
        self.enterContext(patch.dict(os.environ, {"TRAVEL_DB_PATH": str(directory / "travel.sqlite3")}, clear=True))

    def assert_workflow_key(self, app, expected):
        self.assertEqual(app.config["GEMINI_API_KEY"], expected)
        flow = app.extensions["travel_workflow"]
        self.assertEqual((flow.member.key, flow.mediator.key), (expected, expected))
        self.assertNotEqual(flow.member.model, flow.mediator.model)

    def test_wsgi_reads_only_the_literal_project_key(self):
        self.env_file.write_text(
            'GEMINI_API_KEY="fixture ${PART} # literal"  # comment\n'
            'PART=expanded\nROOM_CREATE_CODE=unexpected\n', encoding="utf-8-sig")
        before = dict(os.environ)
        app = runpy.run_module("travel_app.wsgi")["app"]
        runner = app.extensions["travel_runner"]
        self.addCleanup(runner.thread.join)
        self.addCleanup(runner.close)
        self.assert_workflow_key(app, "fixture ${PART} # literal")
        self.assertEqual(app.config["ROOM_CREATE_CODE"], "")
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(app.test_client().get("/healthz").get_json()["status"], "ok")

    def test_process_key_including_empty_skips_file(self):
        self.env_file.write_text("GEMINI_API_KEY=file-fixture\n", encoding="utf-8")
        with patch.object(config, "dotenv_values", side_effect=AssertionError("unexpected file lookup")):
            for value in ("process-fixture", ""):
                with self.subTest(value=value), patch.dict(os.environ, GEMINI_API_KEY=value):
                    self.assert_workflow_key(create_app({"START_WORKER": False}), value)

    def test_explicit_app_key_including_empty_skips_lookup(self):
        with patch.dict(os.environ, GEMINI_API_KEY="process-fixture"), patch(
            "travel_app.gemini_api_key", side_effect=AssertionError("unexpected lookup")
        ):
            for value in ("config-fixture", ""):
                with self.subTest(value=value):
                    app = create_app({"START_WORKER": False, "GEMINI_API_KEY": value})
                    self.assert_workflow_key(app, value)

    def test_missing_key_preserves_startup_and_model_error(self):
        for contents in (None, "OTHER=value", "GEMINI_API_KEY", "GEMINI_API_KEY="):
            with self.subTest(contents=contents):
                if contents is not None:
                    self.env_file.write_text(contents, encoding="utf-8")
                app = create_app({"START_WORKER": False})
                self.assert_workflow_key(app, "")
                self.assertEqual(app.test_client().get("/healthz").status_code, 200)
                with patch("travel_app.models.urlopen", side_effect=AssertionError("unexpected network access")):
                    with self.assertRaisesRegex(ModelError, "Gemini API 키"):
                        app.extensions["travel_workflow"].member.generate("fixture", {})

    def test_no_waitress_starts_same_app_without_loading_foreign_dotenv(self):
        self.env_file.write_text("GEMINI_API_KEY=project-fixture\n", encoding="utf-8")
        with patch.dict(os.environ, FLASK_SKIP_DOTENV="0", HOST="127.0.0.5", PORT="8124"), patch.dict(
            sys.modules, {"waitress": None}
        ), patch("werkzeug.serving.run_simple") as serve:
            before = dict(os.environ)
            app = runpy.run_module("travel_app.__main__", run_name="__main__")["app"]
            runner = app.extensions["travel_runner"]
            self.addCleanup(runner.thread.join)
            self.addCleanup(runner.close)
            serve.assert_called_once_with("127.0.0.5", 8124, app, threaded=True, use_reloader=False)
            self.assert_workflow_key(app, "project-fixture")
            self.assertEqual(dict(os.environ), before)

    def test_provider_check_gate_and_shared_key(self):
        with patch.object(sys, "path", sys.path.copy()):
            from scripts import check_live_providers as check

        version = (check.ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with patch.object(check, "gemini_api_key", side_effect=AssertionError("unexpected lookup")), patch.object(
            check, "Gemini", side_effect=AssertionError("unexpected provider")
        ), redirect_stdout(io.StringIO()) as output:
            check.main()
            with patch.dict(os.environ, PROVIDER_CHECK_VERSION="other-version"):
                check.main()
            self.assertEqual(output.getvalue(), "")

        self.env_file.write_text("GEMINI_API_KEY=release-fixture\n", encoding="utf-8")
        responses = [{"ok": True}, {"ok": True}, {"groundingMetadata": {
            "webSearchQueries": ["museum"], "groundingChunks": [{"web": {"uri": "https://example.org"}}]}}]
        with patch.dict(os.environ, PROVIDER_CHECK_VERSION=version, MEMBER_MODEL="member", MEDIATOR_MODEL="judge"), patch.object(
            Gemini, "generate", autospec=True, side_effect=responses
        ) as generate, redirect_stdout(io.StringIO()) as output:
            check.main()
        calls = [(call.args[0].key, call.args[0].model, call.kwargs.get("search", False))
                 for call in generate.call_args_list]
        self.assertEqual(calls, [("release-fixture", "member", False),
                                 ("release-fixture", "judge", False), ("release-fixture", "member", True)])
        self.assertEqual(output.getvalue().splitlines(), [
            f"Provider check {version} member member verified", f"Provider check {version} decision judge verified",
            f"Provider check {version} search member verified"])
