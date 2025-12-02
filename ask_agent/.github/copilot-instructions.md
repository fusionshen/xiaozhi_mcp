## Purpose

This file gives concise, actionable guidance for AI coding agents working in this repository so they can be productive immediately.

**Quick Start**
- **Run:**: create and activate a venv then install deps: `python -m venv ask_agent_venv` then `ask_agent_venv\Scripts\activate` and `pip install -r requirements.txt`.
- **Serve:**: start the app with `uvicorn main_v2:app --host 0.0.0.0 --port 9001` (the `readme.md` also documents `main:app` on port 9000).
- **Python version:**: prefer CPython 3.12 (README warns Python 3.12+ may cause issues).

**Big Picture / Architecture**
- **Entrypoints:**: `main.py` and `main_v2.py` are the application entrypoints and wire FastAPI/uvicorn.
- **Orchestration:**: `core/pipeline.py` is the primary message processor; see `process_message` which retrieves the `ContextGraph` and dispatches to handlers in `core/pipeline_handlers.py`.
- **LLM abstraction:**: `core/llm_client.py` encapsulates model selection and provides `safe_llm_parse` and `safe_llm_chat`. It prefers a remote Ollama endpoint (`REMOTE_OLLAMA_URL`) and falls back to local models.
- **Tools / APIs:**: `tools/formula_api.py` exposes a standalone FastAPI-backed formula search service and shows the repository's pattern for one-time initialization (`initialize()` with an `_initialized` guard).

**Project-specific Conventions**
- **One-time init guards:**: Modules that load heavy resources (embeddings, CSVs) use `_initialized` flags and explicit `initialize()` functions; avoid re-running initialization by importing modules naively.
- **Logger pattern:**: modules configure loggers with `if not logger.handlers:` to avoid duplicate logging handlers—preserve that pattern when adding modules.
- **Async-first LLM calls:**: LLM helper functions are async and return JSON-safe data. Prefer calling `safe_llm_parse` / `safe_llm_chat` rather than calling model clients directly.
- **Context lifecycle:**: conversation state is stored in a `ContextGraph` (see `core/context_graph.py`) and accessed via `core/pipeline_context.get_graph` / `set_graph` in `process_message`.
- **Return shapes:**: tool APIs and handlers commonly return dicts with explicit keys like `done`, `message`, `candidates` (see `tools/formula_api.py:formula_query_dict`). Keep changes backward compatible.

**Developer Workflows & Commands**
- **Install deps:**: `pip install -r requirements.txt` or use the `readme.md` Windows venv instructions.
- **Run tests:**: `pytest tests/test_v2_full_flow.py` or `pytest -q` (tests live in `tests/` and validate end-to-end flows).
- **Run a single module locally:**: many `tools/*.py` modules support `if __name__ == "__main__":` for quick runs (e.g., `tools/formula_api.py`).

**Integration Points & External Dependencies**
- **LLM / Ollama:**: configured in `config.py` (`REMOTE_OLLAMA_URL`, `REMOTE_MODEL`, `LOCAL_MODEL`). `core/llm_client.py` checks remote availability.
- **Embedding / SBERT:**: `tools/formula_api.py` prefers local SentenceTransformer models under `models/sbert_offline_models` and caches embeddings to `data/`.
- **Prompts & tools:**: `prompts/` contains prompt templates. `prompts/v2_workplace_models_tools/` contains tool prompts and logs used during model testing.

**Files To Read First (for any code change)**
- `readme.md` : environment, run and Docker notes.
- `core/pipeline.py` : overall message routing (`process_message`).
- `core/pipeline_handlers.py` : concrete handler implementations (classify, compare, slot fill, etc.).
- `core/llm_client.py` : LLM selection and robust JSON parsing logic.
- `tools/formula_api.py` : example of heavy-init, caching, and API-return patterns.

**Guidance For AI Agents Editing Code**
- **Preserve init and logging patterns:** avoid duplicate initialization and duplicate log handlers.
- **Prefer small, focused changes:** follow existing function signatures and return shapes; tests exercise end-to-end flows.
- **Add unit tests for behavioral changes:** use `tests/test_v2_full_flow.py` as an integration reference.
- **When editing prompts:** update or add files under `prompts/` and include short examples in tests or `test_logs/`.

Please review this draft — tell me which sections need more examples or if you want me to merge existing docs from other files into this file.
