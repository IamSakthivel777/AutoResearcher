# Install and use AutoResearcher

AutoResearcher researches a question with a supported LLM and writes a source-grounded Microsoft Word (`.docx`) report.

The PyPI installation name is `autoresearcher-ai`. The Python import name is `autoresearcher`.

## Install

Create a virtual environment for your application and install the published package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install autoresearcher-ai
```

Verify it:

```bash
python -c "from autoresearcher import AutoResearcher; print('AutoResearcher is ready')"
autoresearcher --help
```

AutoResearcher supports Python 3.10 and later. It uses LangChain 1.x and LangGraph 1.x, so it can share an environment with an application using `langchain>=1,<2`.

## Configure API keys

Set at least one LLM provider key before starting Python. For OpenAI:

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

For a local application, place keys in a `.env` file in the application's working directory:

```dotenv
OPENAI_API_KEY=your-openai-api-key
TAVILY_API_KEY=optional-search-key
```

| Provider or service | Environment variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Tavily search (optional) | `TAVILY_API_KEY` |

Tavily is optional; DuckDuckGo is the fallback search provider. Never commit `.env` files or keys. For production, inject secrets through the environment or a secret manager.

## First Python report

Create `research.py`:

```python
from pathlib import Path

from autoresearcher import AutoResearcher


researcher = AutoResearcher(
    models={
        "planner": "openai",
        "worker": "openai",
        "critic": "openai",
        "writer": "openai",
    },
    max_subagents=8,
    llm_timeout_seconds=180,
)

result = researcher.run(
    "Compare electric vehicle battery technologies for city buses",
    output=Path("reports/battery-research.docx"),
)

print(f"Report: {result.docx_path}")
print(f"Sources: {len(result.sources)}")
print(f"Token usage: {result.token_usage}")
for warning in result.warnings:
    print(f"Warning: {warning}")
```

Run it with `python research.py`. Parent output directories are created automatically, and `result.docx_path` is the absolute path of the generated file.

The repository also includes this complete copyable example: `examples/use_pypi_package.py`.

## Trip reports, languages, and images

This creates a trip report with a cover image, four gallery images, and translated highlights:

```python
from autoresearcher import AutoResearcher


researcher = AutoResearcher(
    models={"planner": "openai", "worker": "openai", "critic": "openai", "writer": "openai"},
    max_subagents=8,
    max_critic_loops=1,
    llm_timeout_seconds=180,
    languages=["tamil", "hindi", "telugu", "malayalam"],
    include_images=True,
    image_limit=5,
)

result = researcher.run(
    "Chennai trip for 3 days from 10 December 2026",
    output="reports/chennai-trip.docx",
)
print(result.docx_path)
```

For trip questions, the report includes a current weather forecast and separately researched best-time-to-visit guidance. A complete date such as `10 December 2026` is used only when the user provides it. Without one, the report labels the live forecast as beginning on the report date and does not invent itinerary dates.

Images are optional and sourced from Wikimedia Commons. They include creator, license, and source attribution in the document. Image search is best-effort, so inspect `result.warnings` if one cannot be found or downloaded.

## Command-line use

Use the installed command instead of writing Python:

```bash
autoresearcher "Chennai trip for 3 days from 10 December 2026" \
  --models planner=openai,worker=openai,critic=openai,writer=openai \
  --max-subagents 8 \
  --llm-timeout 180 \
  --languages tamil,hindi,telugu,malayalam \
  --images \
  --output reports/chennai-trip.docx
```

| Option | Meaning |
| --- | --- |
| `-o`, `--output` | DOCX destination; default `autoresearcher_report.docx`. |
| `--models` | Comma-separated routes, for example `planner=openai,worker=gemini`. |
| `--max-subagents` | Maximum parallel workers, 1 to 64; default 8. |
| `--llm-timeout` | Per-model timeout in seconds; default 180. |
| `--languages` | Comma-separated: tamil, hindi, telugu, malayalam. |
| `--images` | Add attributed Wikimedia Commons images. |

## Model routing

Each role accepts a provider name or a provider and model identifier:

```python
researcher = AutoResearcher(
    models={
        "planner": "openai:gpt-5",
        "worker": "gemini",
        "critic": "claude",
        "writer": "openai:gpt-5-mini",
    }
)
```

Valid roles are `planner`, `worker`, `critic`, and `writer`. Providers are `openai`, `anthropic`/`claude`, and `gemini`/`google`. If a requested provider has no configured key, AutoResearcher uses another configured provider and adds a warning to the result.

## Result object

`run()` returns a `RunResult` with these useful fields:

| Field | Description |
| --- | --- |
| `docx_path` | Absolute path to the generated DOCX file. |
| `sources` | Deduplicated web and image sources used by the report. |
| `token_usage` | Reported model token totals by role. |
| `warnings` | Non-fatal limit, provider, worker, translation, or image warnings. |
| `plan` | Generated research plan. |
| `report_spec` | Validated data used to render the document. |

## Async applications

Use `arun()` from FastAPI, Jupyter, or any process that already has an event loop:

```python
from autoresearcher import AutoResearcher


async def make_report(question: str) -> str:
    researcher = AutoResearcher(models={"planner": "openai", "writer": "openai"})
    result = await researcher.arun(question, output="reports/report.docx")
    return str(result.docx_path)
```

Do not call synchronous `run()` from an active event loop; use `await arun()`.

## Progress events

Use `stream()` for a synchronous worker process that needs updates:

```python
from autoresearcher import AutoResearcher, ReportWritten, TaskFinished, TaskStarted


researcher = AutoResearcher(models={"planner": "openai"})
for event in researcher.stream("Compare battery storage technologies", output="reports/storage.docx"):
    if isinstance(event, TaskStarted):
        print(f"Starting: {event.task.title}")
    elif isinstance(event, TaskFinished):
        print(f"Finished {event.task_id}: {event.source_count} sources")
    elif isinstance(event, ReportWritten):
        print(f"Saved: {event.path}")
```

## Runtime controls and production

| Constructor option | Default | Purpose |
| --- | ---: | --- |
| `max_subagents` | 8 | Hard maximum parallel workers. |
| `max_critic_loops` | 2 | Maximum evidence-review loops. |
| `max_tool_calls` | 6 | Tool calls allowed per worker. |
| `token_budget` | 100000 | Budget for optional model work based on reported tokens. |
| `task_timeout_seconds` | 60 | Per-worker timeout. |
| `llm_timeout_seconds` | 180 | Per-model timeout. |
| `image_limit` | 5 | Number of images, from 1 through 5. |

Run long reports in a background worker rather than directly in a normal HTTP request. Use unique output paths for concurrent runs. Generated reports are research assistance: review citations for time-sensitive, legal, medical, or financial decisions.

## Common errors

### `ModuleNotFoundError: No module named 'autoresearcher'`

Activate the same environment that runs your application and reinstall:

```bash
source .venv/bin/activate
python -m pip install --upgrade autoresearcher-ai
python -c "import sys, autoresearcher; print(sys.executable, autoresearcher.__file__)"
```

### No API key or request timeout

Set a supported provider key before starting Python. For a slow provider, increase the timeout:

```python
AutoResearcher(models={"planner": "openai"}, llm_timeout_seconds=300)
```

### Existing LangChain application

Install the current package with `python -m pip install --upgrade autoresearcher-ai`. It shares the LangChain 1.x / LangGraph 1.x dependency line. A separate dependency locked to LangChain 0.x cannot share that virtual environment and must be upgraded or isolated.
