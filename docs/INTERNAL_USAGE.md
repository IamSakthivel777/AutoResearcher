# Using AutoResearcher inside your system

This guide covers installing AutoResearcher into another Python application on the same
computer, configuring API keys, calling the Python API, and distributing an internal wheel.

## Requirements

- Python 3.10 or newer
- At least one supported LLM key: OpenAI, Anthropic, or Gemini
- Internet access for the selected model and research tools
- A virtual environment for each application

Do not install the project into the operating system's Python with `sudo pip`.

## Option 1: editable installation for development

Use this while changing AutoResearcher locally. Changes under `src/autoresearcher` become
available to the consuming environment without reinstalling the package.

```bash
cd /path/to/your-application
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e /home/sakthivel/Downloads/autoresearcher
```

Verify the installation:

```bash
python -c "from autoresearcher import AutoResearcher; print('AutoResearcher is ready')"
autoresearcher --help
```

## Option 2: normal local installation

Use a normal installation when the consuming application should not change as the source
directory changes:

```bash
source /path/to/your-application/.venv/bin/activate
python -m pip install /home/sakthivel/Downloads/autoresearcher
```

Reinstall after updating AutoResearcher:

```bash
python -m pip install --upgrade --force-reinstall /home/sakthivel/Downloads/autoresearcher
```

## Option 3: install an internal wheel

Build and validate the wheel from the repository:

```bash
cd /home/sakthivel/Downloads/autoresearcher
source .venv/bin/activate
python -m build
python -m twine check dist/*
```

Install that immutable artifact in another environment:

```bash
source /path/to/your-application/.venv/bin/activate
python -m pip install \
  /home/sakthivel/Downloads/autoresearcher/dist/autoresearcher_ai-0.1.1-py3-none-any.whl
```

For several internal computers, copy the wheel to an internal file share or package registry.
To prepare an offline wheel directory, including dependencies, run this on a connected system:

```bash
mkdir -p wheelhouse
python -m pip download --dest wheelhouse \
  dist/autoresearcher_ai-0.1.1-py3-none-any.whl
```

Then copy `wheelhouse` to the offline computer and install from it:

```bash
python -m pip install --no-index --find-links wheelhouse autoresearcher-ai
```

## Configure API keys

The safest normal setup is to export keys in the process environment:

```bash
export OPENAI_API_KEY="your-key"
export TAVILY_API_KEY="your-key"  # optional; DuckDuckGo is the fallback
```

Alternatively, put a `.env` file in the directory from which your application starts:

```dotenv
OPENAI_API_KEY=your-key
TAVILY_API_KEY=your-key
```

Never commit `.env` or print API keys. Constructor keys are also accepted, but environment or
secret-manager injection is preferable for deployed applications.

## Basic Python integration

```python
from pathlib import Path

from autoresearcher import AutoResearcher


researcher = AutoResearcher(
    models={
        "planner": "openai",
        "critic": "openai",
        "writer": "openai",
    },
    max_subagents=8,
    max_critic_loops=1,
    llm_timeout_seconds=180,
    languages=["tamil", "hindi", "telugu", "malayalam"],
    include_images=True,
    image_limit=5,
)

result = researcher.run(
    "Chennai trip for 3 days",
    output=Path("reports/chennai-trip.docx"),
)

print(result.docx_path)
print(f"Sources: {len(result.sources)}")
print(f"Token usage: {result.token_usage}")
for warning in result.warnings:
    print(f"Warning: {warning}")
```

`run()` is for ordinary synchronous Python programs. It creates missing output directories and
returns a `RunResult`; it does not return the document bytes.

## Async applications

Use `arun()` in FastAPI, Jupyter, asyncio services, or any process that already has a running
event loop:

```python
from autoresearcher import AutoResearcher


async def create_report(question: str, output: str):
    researcher = AutoResearcher(
        models={"planner": "openai", "critic": "openai", "writer": "openai"},
        include_images=True,
    )
    return await researcher.arun(question, output=output)
```

Calling synchronous `run()` inside an active event loop raises `SyncInAsyncError` intentionally.

## Progress events

For a synchronous worker process, use `stream()` to receive typed progress events:

```python
from autoresearcher import AutoResearcher, ReportWritten, TaskFinished


researcher = AutoResearcher(models={"planner": "openai"})

for event in researcher.stream(
    "Compare battery storage technologies",
    output="reports/storage.docx",
):
    if isinstance(event, TaskFinished):
        print(f"Completed {event.task_id}: {event.source_count} sources")
    elif isinstance(event, ReportWritten):
        print(f"Report written to {event.path}")
```

## `RunResult` fields

| Field | Meaning |
| --- | --- |
| `docx_path` | Absolute path to the generated Word document |
| `report_spec` | Validated structured representation used to render the document |
| `plan` | Research plan and tasks selected for the run |
| `sources` | Deduplicated sources used by factual claims and images |
| `token_usage` | Reported model-token totals grouped by role |
| `warnings` | Non-fatal worker, limit, translation, or image warnings |

## Supported language and image options

`languages` accepts `tamil`, `hindi`, `telugu`, and `malayalam`. These are translated,
source-linked highlights; the English report remains the primary report. Online images are
optional and come from Wikimedia Commons. Their license and creator attribution are added to
the document's Sources section.

## Production guidance

- Create one `AutoResearcher` configuration per application, but run expensive report jobs in a
  background worker rather than during a normal HTTP request.
- Give each report a unique output path when several jobs may run concurrently.
- Store output and its hidden image asset directory in an application-controlled workspace.
- Set model and spending limits in your provider account; `token_budget` only controls optional
  work based on token usage reported to this package.
- Treat generated reports as research assistance. Recheck time-sensitive and high-stakes facts.
- Pin the internal version, for example `autoresearcher-ai==0.1.1`, after publishing under your
  final distribution name.

## Common problems

### `ModuleNotFoundError: No module named 'autoresearcher'`

Install the package into the same interpreter that runs the application:

```bash
python -m pip install -e /home/sakthivel/Downloads/autoresearcher
python -c "import sys, autoresearcher; print(sys.executable, autoresearcher.__file__)"
```

### `OPENAI_API_KEY is missing`

Set the key before starting Python, or create `.env` in the application's working directory.

### `Planner request timed out after retries`

Retry after a short wait and, if needed, increase the model timeout:

```python
AutoResearcher(models={"planner": "openai"}, llm_timeout_seconds=300)
```

### Images are missing

Image search is best-effort. Confirm that `include_images=True`, outbound HTTPS works, and the
result warnings do not report a Wikimedia search or download failure.
