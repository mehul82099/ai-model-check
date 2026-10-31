#!/usr/bin/env python3
"""ai-model-check - find retired and deprecated AI model IDs in your code.

Model providers retire API models on published schedules: a model string
that worked last quarter can return 404 today. ai-model-check scans
source files, configs, and docs for model IDs from OpenAI, Anthropic,
and Google (Gemini), and matches them against a dataset built from the
providers' own deprecation pages:

- model-retired (error): the model's shutdown/retirement date has been
  reached; requests fail.
- model-deprecated (warning): a shutdown date is announced but still
  ahead; migrate to the recommended replacement.

Matching is exact-token (case-insensitive), plus OpenAI fine-tuned model
IDs of the form ft:<base-model>:org:name:id resolve to their base model
- OpenAI states fine-tuned versions follow the base model's shutdown
schedule. Absence of a finding is not a guarantee: the dataset is a
point-in-time snapshot (see verified_at in models.json) and only covers
IDs the providers list. Re-verify against the linked sources, or pass an
updated dataset with --data.

Pure standard library; no network at runtime.

Sources (all fetched 2026-10-31):
- https://platform.openai.com/docs/deprecations
- https://docs.anthropic.com/en/docs/about-claude/model-deprecations
- https://ai.google.dev/gemini-api/docs/deprecations
"""

import argparse
import datetime
import json
import os
import re
import sys

DEFAULT_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json",
    ".yaml", ".yml", ".toml", ".env", ".cfg", ".ini", ".md", ".txt",
    ".sh", ".rb", ".go", ".java", ".kt", ".cs", ".php", ".rs",
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._\-:]{2,}")


class Finding:
    def __init__(self, path, line, rule, severity, message):
        self.path = path
        self.line = line
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        return {
            "file": self.path,
            "line": self.line,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }


def load_dataset(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    table = {}
    for entry in data.get("models", []):
        table[entry["id"].lower()] = entry
    return data, table


def entry_status(entry, as_of):
    """Return 'retired', 'deprecated', or None.

    An explicit status in the dataset wins. Otherwise the shutdown date
    decides: on the shutdown date the model is being turned off, so
    shutdown <= as_of counts as retired (documented convention).
    """
    if entry.get("status") == "deprecated":
        return "deprecated"
    shutdown = entry.get("shutdown")
    if not shutdown:
        return None
    day = datetime.date.fromisoformat(shutdown)
    return "retired" if day <= as_of else "deprecated"


def _host(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else url


def scan_text(text, path, table, as_of):
    findings = []
    for lineno, line in enumerate(text.split("\n"), 1):
        seen = set()
        for match in TOKEN_RE.finditer(line):
            token = match.group(0)
            low = token.lower()
            entry = table.get(low)
            shown = token
            if entry is None and low.startswith("ft:"):
                parts = low.split(":")
                if len(parts) > 1:
                    entry = table.get(parts[1])
                    shown = "%s (fine-tuned base: %s)" % (token, parts[1])
            if entry is None or low in seen:
                continue
            status = entry_status(entry, as_of)
            if status is None:
                continue
            seen.add(low)
            seen.add(token.lower())
            provider = entry.get("provider", "?")
            replacement = entry.get("replacement") or "none listed"
            source = _host(entry.get("source"))
            if status == "retired":
                findings.append(Finding(
                    path, lineno, "model-retired", "error",
                    "%s (%s) was shut down on %s; requests fail. "
                    "Recommended replacement: %s (%s)." % (
                        shown, provider, entry["shutdown"], replacement,
                        source)))
            else:
                if entry.get("shutdown"):
                    msg = ("%s (%s) is deprecated and shuts down on %s. "
                           "Recommended replacement: %s (%s)." % (
                               shown, provider, entry["shutdown"],
                               replacement, source))
                else:
                    msg = ("%s (%s) is deprecated (no shutdown date "
                           "announced yet). Recommended replacement: "
                           "%s (%s)." % (shown, provider, replacement,
                                         source))
                findings.append(Finding(
                    path, lineno, "model-deprecated", "warning", msg))
    return findings


def iter_files(paths, extensions):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                for name in sorted(names):
                    if name.lower().endswith(extensions):
                        yield os.path.join(root, name)
        else:
            yield p


def build_parser():
    p = argparse.ArgumentParser(
        prog="ai-model-check",
        description="Find retired and deprecated AI model IDs (OpenAI, "
                    "Anthropic, Google) in source files, with the "
                    "provider-recommended replacement.")
    p.add_argument("paths", nargs="+",
                   help="files or directories (directories are scanned "
                        "recursively for common text extensions)")
    p.add_argument("--data", metavar="JSON",
                   help="use a custom/updated dataset instead of the "
                        "bundled models.json")
    p.add_argument("--as-of", metavar="YYYY-MM-DD",
                   help="evaluate status as of this date (default: "
                        "today) for reproducible CI runs")
    p.add_argument("--ext", action="append", default=[], metavar=".EXT",
                   help="extra file extension for directory scans "
                        "(repeatable)")
    p.add_argument("--ignore", action="append", default=[], metavar="RULE",
                   help="suppress a rule by name (repeatable)")
    p.add_argument("--fail-on-warning", action="store_true",
                   help="exit 1 when only warnings are present")
    p.add_argument("--format", choices=["text", "json"], default="text",
                   help="output format (default: text)")
    return p


def format_text(results):
    lines = []
    errors = warnings = 0
    for path, findings in results:
        for f in findings:
            lines.append("%s:%d [%s] %s: %s" % (
                f.path, f.line, f.severity, f.rule, f.message))
            if f.severity == "error":
                errors += 1
            else:
                warnings += 1
    if errors or warnings:
        lines.append("ai-model-check: %d error(s), %d warning(s)" % (
            errors, warnings))
    else:
        lines.append("ai-model-check: clean")
    return "\n".join(lines), errors, warnings


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.as_of:
        try:
            as_of = datetime.date.fromisoformat(args.as_of)
        except ValueError:
            print("ai-model-check: --as-of must be YYYY-MM-DD",
                  file=sys.stderr)
            return 2
    else:
        as_of = datetime.date.today()
    data_path = args.data or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "models.json")
    try:
        _, table = load_dataset(data_path)
    except (OSError, ValueError) as exc:
        print("ai-model-check: cannot load dataset %s: %s" % (
            data_path, exc), file=sys.stderr)
        return 2
    ignore = set(args.ignore)
    exts = DEFAULT_EXTENSIONS + tuple(
        e if e.startswith(".") else "." + e for e in args.ext)
    results = []
    for path in iter_files(args.paths, exts):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            print("ai-model-check: cannot read %s: %s" % (path, exc),
                  file=sys.stderr)
            return 2
        findings = [f for f in scan_text(text, path, table, as_of)
                    if f.rule not in ignore]
        results.append((path, findings))

    text_out, errors, warnings = format_text(results)
    if args.format == "json":
        print(json.dumps({
            "findings": [f.as_dict() for _, fs in results for f in fs],
            "summary": {"files": len(results), "errors": errors,
                        "warnings": warnings, "as_of": as_of.isoformat()},
        }, indent=2))
    else:
        print(text_out)
    if errors:
        return 1
    if args.fail_on_warning and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
