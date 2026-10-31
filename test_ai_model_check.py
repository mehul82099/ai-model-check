#!/usr/bin/env python3
"""Tests for ai-model-check (stdlib unittest).

Date-sensitive logic is tested against a fabricated dataset with fixed
dates, never against the real models.json - so this suite cannot age.
The shipped dataset is validated structurally only.
"""

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_model_check as amc

AS_OF = datetime.date(2026, 10, 31)

FAKE = {
    "old-model": {"id": "old-model", "provider": "fake",
                  "shutdown": "2026-01-15", "replacement": "new-model",
                  "source": "https://fake.example/deprecations"},
    "dying-model": {"id": "dying-model", "provider": "fake",
                    "shutdown": "2026-12-25", "replacement": "new-model",
                    "source": "https://fake.example/deprecations"},
    "edge-model": {"id": "edge-model", "provider": "fake",
                   "shutdown": "2026-10-31", "replacement": "new-model",
                   "source": "https://fake.example/deprecations"},
    "nodate-model": {"id": "nodate-model", "provider": "fake",
                     "shutdown": None, "replacement": "new-model",
                     "source": "https://fake.example/deprecations",
                     "status": "deprecated"},
    "live-model": {"id": "live-model", "provider": "fake",
                   "shutdown": None, "replacement": None,
                   "source": "https://fake.example/deprecations"},
}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = amc.main(argv)
    return code, out.getvalue(), err.getvalue()


def scan(text):
    return amc.scan_text(text, "app.py", FAKE, AS_OF)


class StatusTests(unittest.TestCase):
    def test_past_shutdown_is_retired(self):
        self.assertEqual(amc.entry_status(FAKE["old-model"], AS_OF),
                         "retired")

    def test_future_shutdown_is_deprecated(self):
        self.assertEqual(amc.entry_status(FAKE["dying-model"], AS_OF),
                         "deprecated")

    def test_shutdown_day_counts_as_retired(self):
        # documented convention: on the shutdown date the model is
        # being turned off
        self.assertEqual(amc.entry_status(FAKE["edge-model"], AS_OF),
                         "retired")

    def test_explicit_deprecated_status_wins(self):
        self.assertEqual(amc.entry_status(FAKE["nodate-model"], AS_OF),
                         "deprecated")

    def test_no_date_no_status_is_none(self):
        self.assertIsNone(amc.entry_status(FAKE["live-model"], AS_OF))

    def test_as_of_changes_status(self):
        before = datetime.date(2025, 6, 1)
        self.assertEqual(amc.entry_status(FAKE["old-model"], before),
                         "deprecated")


class ScannerTests(unittest.TestCase):
    def test_retired_model_flagged_as_error(self):
        fs = scan('model = "old-model"')
        self.assertEqual(fs[0].rule, "model-retired")
        self.assertEqual(fs[0].severity, "error")
        self.assertIn("2026-01-15", fs[0].message)

    def test_deprecated_model_flagged_as_warning(self):
        fs = scan('model = "dying-model"')
        self.assertEqual(fs[0].rule, "model-deprecated")
        self.assertEqual(fs[0].severity, "warning")
        self.assertIn("2026-12-25", fs[0].message)

    def test_deprecated_without_date(self):
        fs = scan('model = "nodate-model"')
        self.assertEqual(fs[0].rule, "model-deprecated")
        self.assertIn("no shutdown date", fs[0].message)

    def test_unlisted_model_clean(self):
        self.assertEqual(scan('model = "some-other-thing"'), [])

    def test_live_model_clean(self):
        self.assertEqual(scan('model = "live-model"'), [])

    def test_case_insensitive_match(self):
        fs = scan('MODEL = "OLD-MODEL"')
        self.assertEqual(len(fs), 1)

    def test_exact_token_no_prefix_match(self):
        # 'old-model-x' must not match the 'old-model' entry
        self.assertEqual(scan('model = "old-model-x"'), [])

    def test_replacement_in_message(self):
        fs = scan('"old-model"')
        self.assertIn("new-model", fs[0].message)

    def test_line_numbers(self):
        fs = scan("ok = 1\n\nmodel = 'old-model'\n")
        self.assertEqual(fs[0].line, 3)

    def test_multiple_models_multiple_findings(self):
        fs = scan('a = "old-model"\nb = "dying-model"\n')
        self.assertEqual({f.rule for f in fs},
                         {"model-retired", "model-deprecated"})

    def test_same_model_same_line_once(self):
        fs = scan('x = "old-model" + "old-model"')
        self.assertEqual(len(fs), 1)

    def test_same_model_two_lines_two_findings(self):
        fs = scan('"old-model"\n"old-model"\n')
        self.assertEqual(len(fs), 2)

    def test_finetuned_id_resolves_base(self):
        fs = scan('m = "ft:old-model:acme:run1:xyz"')
        self.assertEqual(len(fs), 1)
        self.assertIn("fine-tuned base: old-model", fs[0].message)

    def test_finetuned_unknown_base_clean(self):
        self.assertEqual(scan('m = "ft:unknown-base:acme:r:x"'), [])

    def test_provider_in_message(self):
        fs = scan('"old-model"')
        self.assertIn("(fake)", fs[0].message)


class DatasetTests(unittest.TestCase):
    """Structural checks on the shipped models.json - no date asserts."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "models.json")
        with open(path, encoding="utf-8") as fh:
            cls.data = json.load(fh)

    def test_verified_at_is_iso_date(self):
        datetime.date.fromisoformat(self.data["verified_at"])

    def test_sources_listed(self):
        self.assertEqual(len(self.data["sources"]), 3)

    def test_every_entry_has_required_fields(self):
        for m in self.data["models"]:
            for key in ("id", "provider", "source"):
                self.assertTrue(m.get(key), "missing %s in %r" % (key, m))

    def test_ids_unique(self):
        ids = [m["id"] for m in self.data["models"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ids_lowercase(self):
        for m in self.data["models"]:
            self.assertEqual(m["id"], m["id"].lower())

    def test_shutdown_is_iso_or_null(self):
        for m in self.data["models"]:
            if m.get("shutdown"):
                datetime.date.fromisoformat(m["shutdown"])

    def test_shutdown_or_deprecated_status_present(self):
        for m in self.data["models"]:
            self.assertTrue(m.get("shutdown") or m.get("status"),
                            "entry without date or status: %r" % m)

    def test_sources_are_https_urls(self):
        for m in self.data["models"]:
            self.assertTrue(m["source"].startswith("https://"),
                            m["source"])

    def test_providers_known(self):
        for m in self.data["models"]:
            self.assertIn(m["provider"],
                          ("openai", "anthropic", "google"))


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.data = os.path.join(self.dir, "data.json")
        with open(self.data, "w", encoding="utf-8") as fh:
            json.dump({"verified_at": "2026-10-31", "sources": [],
                       "models": list(FAKE.values())}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_clean_exit_zero(self):
        p = self.write("ok.py", 'model = "unlisted"')
        code, out, _ = run(["--data", self.data, p])
        self.assertEqual(code, 0)
        self.assertIn("clean", out)

    def test_retired_exit_one(self):
        p = self.write("bad.py", 'model = "old-model"')
        code, out, _ = run(["--data", self.data, p])
        self.assertEqual(code, 1)
        self.assertIn("model-retired", out)

    def test_warning_only_exit_zero_default(self):
        p = self.write("w.py", 'model = "dying-model"')
        code, _, _ = run(["--data", self.data, p])
        self.assertEqual(code, 0)

    def test_fail_on_warning(self):
        p = self.write("w.py", 'model = "dying-model"')
        code, _, _ = run(["--data", self.data, "--fail-on-warning", p])
        self.assertEqual(code, 1)

    def test_as_of_changes_result(self):
        p = self.write("w.py", 'model = "dying-model"')
        code, out, _ = run(["--data", self.data, "--as-of", "2027-01-01", p])
        self.assertEqual(code, 1)
        self.assertIn("model-retired", out)

    def test_bad_as_of_exit_two(self):
        p = self.write("w.py", "x = 1")
        code, _, err = run(["--data", self.data, "--as-of", "tomorrow", p])
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)

    def test_ignore_suppresses(self):
        p = self.write("bad.py", 'model = "old-model"')
        code, out, _ = run(["--data", self.data, "--ignore",
                            "model-retired", p])
        self.assertEqual(code, 0)
        self.assertIn("clean", out)

    def test_json_output_shape(self):
        p = self.write("bad.py", 'model = "old-model"')
        code, out, _ = run(["--data", self.data, "--as-of", "2026-10-31",
                            "--format", "json", p])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["summary"]["errors"], 1)
        self.assertEqual(data["summary"]["as_of"], "2026-10-31")
        self.assertEqual(data["findings"][0]["rule"], "model-retired")

    def test_directory_scan(self):
        self.write("a.py", 'm = "old-model"')
        self.write("b.py", 'm = "unlisted"')
        code, out, _ = run(["--data", self.data, self.dir])
        self.assertEqual(code, 1)
        self.assertIn("model-retired", out)

    def test_directory_skips_binary_extension(self):
        self.write("c.bin", 'm = "old-model"')
        code, out, _ = run(["--data", self.data, self.dir])
        self.assertNotIn("c.bin", out)

    def test_ext_flag(self):
        self.write("c.conf", 'm = "old-model"')
        code, out, _ = run(["--data", self.data, "--ext", ".conf",
                            self.dir])
        self.assertIn("model-retired", out)

    def test_missing_file_exit_two(self):
        code, _, err = run(["--data", self.data, "/nonexistent/x.py"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_missing_data_file_exit_two(self):
        p = self.write("w.py", "x = 1")
        code, _, err = run(["--data", "/nonexistent/data.json", p])
        self.assertEqual(code, 2)
        self.assertIn("cannot load dataset", err)

    def test_text_counts(self):
        p = self.write("m.py", 'a = "old-model"\nb = "dying-model"\n')
        code, out, _ = run(["--data", self.data, p])
        self.assertIn("1 error(s), 1 warning(s)", out)

    def test_bundled_dataset_loads(self):
        _, table = amc.load_dataset(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "models.json"))
        self.assertGreater(len(table), 100)


if __name__ == "__main__":
    unittest.main()
