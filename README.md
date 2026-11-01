# ai-model-check

Find retired and deprecated AI model IDs in your code before they break
in production.

Model providers retire API models on published schedules. Code that
calls `gpt-4o`, `claude-3-5-sonnet-20241022`, or `gemini-2.0-flash`
silently turns into failing requests: `claude-3-5-sonnet-20241022` was
retired on October 28, 2025, `gemini-2.0-flash` shut down on June 1,
2026, `gpt-4o` shuts down on January 14, 2027. ai-model-check scans
source, config, and docs for model IDs from OpenAI, Anthropic, and
Google, and tells you the shutdown date and the replacement the provider
recommends:

```
app.py:3 [error] model-retired: claude-3-5-sonnet-20241022 (anthropic) was shut down on 2025-10-28; requests fail. Recommended replacement: claude-sonnet-5-5 (docs.anthropic.com).
config.py:9 [warning] model-deprecated: gpt-4o (openai) is deprecated and shuts down on 2027-01-14. Recommended replacement: gpt-6-luna (platform.openai.com).
ai-model-check: 1 error(s), 1 warning(s)
```

OpenAI fine-tuned IDs (`ft:gpt-4o-mini:org:name:id`) resolve to their
base model, because OpenAI states fine-tuned versions follow the base
model's shutdown schedule.

## Usage

```sh
python3 ai_model_check.py src/ config/
python3 ai_model_check.py --as-of 2027-01-01 src/      # future-dated check
python3 ai_model_check.py --ignore model-deprecated src/
python3 ai_model_check.py --format json --fail-on-warning src/
```

- Directories scan recursively for common text extensions
  (`.py .js .ts .json .yaml .env .md ...`); add more with `--ext`.
- Exit code `0` clean, `1` on errors (or warnings with
  `--fail-on-warning`), `2` on unreadable input.
- No dependencies, no API key, no network at runtime: the dataset ships
  in `models.json`. CI runs on Ubuntu and Windows, Python 3.9 and 3.13.

## The data

`models.json` holds 246 model entries transcribed from the providers'
own deprecation pages, last fetched on **2026-11-01**:

- [OpenAI deprecations](https://platform.openai.com/docs/deprecations) -
  171 entries, including the October 23, 2026 shutdown of
  `gpt-3.5-turbo`, `gpt-4`, `gpt-4-turbo`, `o1`, `o3-mini`, `o4-mini`
  and the January 14, 2027 shutdown announced for the GPT-4o/4.1 series.
- [Anthropic model deprecations](https://docs.anthropic.com/en/docs/about-claude/model-deprecations) -
  21 entries: every model Anthropic lists as Retired, plus
  `claude-sonnet-4-5-20250929` (deprecated September 30, 2026,
  retires November 30, 2026) and `claude-mythos-preview` (deprecated
  June 9, 2026; retirement date to be announced).
- [Gemini deprecations](https://ai.google.dev/gemini-api/docs/deprecations) -
  54 entries across Gemini, Imagen, Veo, embedding, Live and robotics
  models.

Each entry carries its provider, shutdown date (when announced),
recommended replacement, and source URL. `verified_at` records when the
pages were fetched.

**Limitations, honestly:** the dataset is a point-in-time snapshot.
Providers add deprecations without telling this repo, and a model absent
from the table is not guaranteed alive. Anthropic's "not sooner than"
dates for active models are tentative, not deprecations, so active
models are deliberately not listed. Google notes its dates are the
*earliest possible* shutdown. On a model's shutdown day the tool already
reports it retired. Matching is exact-token and case-insensitive; it
scans comments and prose too (stale model names in docs mislead as
well). To refresh the data, re-read the three sources and pass your own
file with `--data`.

## Similar projects

This space exists - compared before building:

- [model-eol](https://github.com/thossullivan/model-eol) (Node 22+,
  `npx`) - multi-provider feeds regenerated from live pages, adds
  Bedrock/Vertex/Azure lifecycle data and per-platform dates. Richer
  coverage; needs Node and a feed refresh.
- [lastorders](https://pypi.org/project/lastorders/) (Python >=3.10,
  deps incl. `libcst`/`cryptography`) - also flags code changes some
  replacements need; dual-licensed MIT + commercial.
- [llm-sunset](https://pypi.org/project/llm-sunset/) and
  [llmstatus.ai](https://llmstatus.ai/) - scanner and hosted tracker.

Where this repo differs: **zero dependencies and fully offline** - one
Python file + one JSON, runs anywhere Python 3.9+ runs, no install, no
account, no network, deterministic `--as-of` for reproducible CI, and
every entry traces to a provider source URL you can verify by hand. It
does not claim broader coverage than model-eol's multi-platform feeds.

## Sources

- https://platform.openai.com/docs/deprecations
- https://docs.anthropic.com/en/docs/about-claude/model-deprecations
- https://ai.google.dev/gemini-api/docs/deprecations

## License

MIT
