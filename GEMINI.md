# Coder-Codex-Gemini (CCG) - Developer Context

This `GEMINI.md` provides context for AI agents and developers working on the Coder-Codex-Gemini (CCG) project.

## 1. Project Overview

**Coder-Codex-Gemini (CCG)** is a Model Context Protocol (MCP) server designed to orchestrate a multi-model AI collaboration workflow. It enables **Gemini** (as the architect) to analyze requirements, plan tasks, guide Coder, and then accept changes before handing off to Codex for review. Gemini delegates execution to specialized models:
*   **Coder:** High-throughput models (e.g., GLM-4.7, DeepSeek) for code generation/execution.
*   **Codex:** OpenAI models for independent code review and quality assurance.
*   **Claude:** Anthropic Claude models for expert advice or deep technical insights.

The project uses a Python-based MCP server (`mcp[cli]`) to expose these capabilities as tools to Gemini.

## 2. Architecture

The system operates on a three-layer architecture:

1.  **MCP Layer (`src/ccg_mcp/`)**:
    *   Provides the physical tools (`coder`, `codex`, `claude`, `gemini` (sub-agent)).
    *   Handles execution, structured error handling, metrics, and sandboxing.
    *   **Tech Stack:** Python 3.12+, `mcp`, `uv` (package manager).

2.  **Skills Layer (`skills/`)**:
    *   Provides workflow guidance documents that Gemini reads to understand *how* to use the tools effectively.
    *   `ccg-workflow`: Guides the standard "Coder execution -> Codex review" loop.
    *   `claude-collaboration`: Guides when and how to involve Claude.

3.  **Global Prompt Layer (`templates/`)**:
    *   `ccg-global-prompt.md` is appended to the user's `AGENTS.md`.
    *   Enforces strict rules (e.g., "Always use Coder for changes", "Always preserve SESSION_ID").

## 3. Directory Structure

*   **`src/ccg_mcp/`**: Core source code.
    *   `cli.py`: Entry point for the CLI application.
    *   `server.py`: Main MCP server logic and tool registration.
    *   `tools/`: Individual tool implementations (`coder.py`, `codex.py`, `gemini.py`).
    *   `config.py`: Configuration loading logic.
*   **`skills/`**: Markdown guides for AI workflow orchestration.
*   **`cases/`**: Real-world test cases and benchmarks.
*   **`templates/`**: Global prompt templates.
*   **`setup.sh` / `setup.bat`**: Automated installation scripts for users.
*   **`pyproject.toml`**: Python project configuration (Hatch/UV).

## 4. Building and Running

The project uses `uv` for dependency management and execution.

### Prerequisites
*   Python 3.12+
*   `uv` (Universal Python Package Installer)

### Development Commands

*   **Install Dependencies:**
    ```bash
    uv sync
    ```

*   **Run Locally (Debug Mode):**
    ```bash
    uv run ccg-mcp
    ```

*   **Register with Claude (Local Dev):**
    ```bash
    claude mcp add ccg-dev -s user --transport stdio -- uv run --directory $(pwd) ccg-mcp
    ```

## 5. Configuration

Runtime configuration is stored in `~/.ccg-mcp/config.toml`. This is **required** for the `coder` tool to function, as it defines the backend model API details.

**Example `config.toml`:**
```toml
[coder]
api_token = "YOUR_API_TOKEN"
base_url = "https://open.bigmodel.cn/api/anthropic" # Example for GLM
model = "glm-4.7"

[claude] # Optional, defaults to official Anthropic API
# api_token = "sk-ant-..." 
```

## 6. Key Development Conventions

*   **Session Management:** All tools MUST support and return a `SESSION_ID` to maintain context across multi-turn interactions.
*   **Sandboxing:**
    *   `coder`, `claude` and `gemini` default to `workspace-write`.
    *   `codex` defaults to `read-only` (strictly enforced for reviews).
*   **Error Handling:** Tools return structured JSON errors (`error_kind`, `error_detail`) to allow the calling AI to decide on retries.
*   **Metrics:** Tools support a `return_metrics` flag to output execution time and token usage data.

## 7. Tool Capabilities

*   **`coder`**:
    *   **Input**: `PROMPT`, `cd`.
    *   **Behavior**: Executes code changes via a CLI wrapper around the configured backend model.
*   **`codex`**:
    *   **Input**: `PROMPT`, `cd`.
    *   **Behavior**: Reviews code or answers questions. **Read-only**.
*   **`claude`**:
    *   **Input**: `PROMPT`, `cd`.
    *   **Behavior**: Expert consultant. Can provide deep architectural advice.
*   **`gemini`**:
    *   **Input**: `PROMPT`, `cd`.
    *   **Behavior**: Sub-agent. Executes sub-tasks in parallel or for isolation.
