"""MCP server for semantic code search via embed-server API."""

import logging
import os
import sys
from pathlib import Path
from fnmatch import fnmatch

import httpx
from mcp.server.fastmcp import FastMCP

# Logging to stderr only
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

API_URL = os.environ.get("EMBED_API_URL", "http://localhost:8100")
API_KEY = os.environ.get("EMBED_API_KEY", "0aqKA3SGiJhHYfLo3Yp95ZyQcN_1XF9IF-vwKumdrWA")

mcp = FastMCP("embed-search", instructions="Semantic code search over indexed codebases. Use search_code to find relevant code, index_project to index new codebases.")


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API_URL, headers=_headers(), timeout=600)


def _parse_gitignore(directory: str) -> list[str]:
    """Parse .gitignore and return patterns."""
    gitignore = Path(directory) / ".gitignore"
    if not gitignore.exists():
        return []
    patterns = []
    for line in gitignore.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: str, patterns: list[str]) -> bool:
    """Check if path matches any gitignore pattern."""
    for pattern in patterns:
        if fnmatch(path, pattern) or fnmatch(path, f"**/{pattern}") or any(
            fnmatch(part, pattern) for part in Path(path).parts
        ):
            return True
    return False


@mcp.tool()
async def search_code(
    project: str,
    query: str,
    k: int = 10,
    file_pattern: str | None = None,
    chunk_type: str | None = None,
) -> str:
    """Search indexed codebase semantically. Use this to find relevant code snippets, functions, or documentation by meaning rather than exact text match.

    Args:
        project: Project name to search in
        query: Natural language search query (e.g. "database connection handling", "error retry logic")
        k: Number of results to return (default 10)
        file_pattern: Optional glob to filter files (e.g. "*.go", "internal/*.py")
        chunk_type: Optional filter: "code" or "text"
    """
    try:
        body: dict = {"query": query, "k": k}
        if file_pattern:
            body["file_pattern"] = file_pattern
        if chunk_type:
            body["chunk_type"] = chunk_type

        async with _client() as client:
            r = await client.post(f"/projects/{project}/search", json=body)
            r.raise_for_status()
            data = r.json()

        results = data.get("results", [])
        if not results:
            return f"No results found for '{query}' in project '{project}'."

        lines = [f"## Search: '{query}' in {project} ({len(results)} results)\n"]
        for i, res in enumerate(results, 1):
            score = res.get("score", 0)
            fp = res.get("file_path", "unknown")
            content = res.get("content", "").strip()
            preview = content[:500] + ("..." if len(content) > 500 else "")
            lines.append(f"### {i}. {fp} (score: {score:.3f})")
            lines.append(f"```\n{preview}\n```\n")

        return "\n".join(lines)
    except httpx.ConnectError:
        return f"Error: Cannot connect to embed-server at {API_URL}. Is it running?"
    except httpx.HTTPStatusError as e:
        return f"Error: API returned {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def index_project(
    project: str,
    directory: str,
    extensions: str = ".go,.py,.js,.ts,.md",
) -> str:
    """Index or reindex a project from a local directory. Reads source files, respects .gitignore, and sends them to the embedding server for chunking and indexing.

    Args:
        project: Project name (will be created if new)
        directory: Absolute path to the project directory
        extensions: Comma-separated file extensions to index (default: ".go,.py,.js,.ts,.md")
    """
    try:
        # Handle paths with spaces — use raw string, don't let shell interpret
        dirpath = Path(directory).expanduser().resolve()
        if not dirpath.is_dir():
            return f"Error: Directory '{directory}' does not exist (resolved to '{dirpath}')."

        ext_set = set(e.strip() for e in extensions.split(","))
        gitignore_patterns = _parse_gitignore(str(dirpath))
        # Always ignore common dirs
        gitignore_patterns.extend([".git", "node_modules", "__pycache__", ".venv", "vendor", "dist", "build"])

        files = []
        skipped = 0
        for fp in sorted(dirpath.rglob("*")):
            if not fp.is_file():
                continue
            rel = str(fp.relative_to(dirpath))
            if _is_ignored(rel, gitignore_patterns):
                continue
            if fp.suffix not in ext_set:
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
                if content.strip():
                    files.append({"path": rel, "content": content})
            except (OSError, PermissionError) as e:
                log.warning(f"Skipped {rel}: {e}")
                skipped += 1
                continue

        if not files:
            return f"No files found matching extensions {extensions} in {dirpath}. (skipped: {skipped})"

        # Send in batches of 10 (smaller batches = less timeout risk on slow CPU servers)
        # First batch creates/replaces the project, subsequent batches append
        batch_size = 10
        total_chunks = 0
        async with _client() as client:
            for i in range(0, len(files), batch_size):
                batch = files[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(files) + batch_size - 1) // batch_size
                log.info(f"Indexing batch {batch_num}/{total_batches} ({len(batch)} files)")
                append = i > 0  # first batch replaces, rest append
                r = await client.put(f"/projects/{project}/index-files", json={"files": batch}, params={"append": str(append).lower()})
                r.raise_for_status()
                data = r.json()
                total_chunks = data.get("total_chunks", total_chunks + data.get("chunks_count", 0))

        return f"Indexed project '{project}': {len(files)} files, {total_chunks} chunks created."
    except httpx.ConnectError:
        return f"Error: Cannot connect to embed-server at {API_URL}. Is it running?"
    except httpx.HTTPStatusError as e:
        return f"Error: API returned {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def list_projects() -> str:
    """List all indexed projects with their chunk counts."""
    try:
        async with _client() as client:
            r = await client.get("/projects")
            r.raise_for_status()
            data = r.json()

        projects = data.get("projects", [])
        if not projects:
            return "No projects indexed yet."

        lines = ["## Indexed Projects\n"]
        for p in projects:
            name = p.get("name", "unknown")
            chunks = p.get("chunks_count", 0)
            lines.append(f"- **{name}**: {chunks} chunks")

        return "\n".join(lines)
    except httpx.ConnectError:
        return f"Error: Cannot connect to embed-server at {API_URL}. Is it running?"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def project_info(project: str) -> str:
    """Get detailed information about an indexed project.

    Args:
        project: Project name
    """
    try:
        async with _client() as client:
            r = await client.get(f"/projects/{project}")
            r.raise_for_status()
            data = r.json()

        lines = [f"## Project: {project}\n"]
        for key, val in data.items():
            lines.append(f"- **{key}**: {val}")

        return "\n".join(lines)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Project '{project}' not found."
        return f"Error: {e.response.status_code}: {e.response.text}"
    except httpx.ConnectError:
        return f"Error: Cannot connect to embed-server at {API_URL}. Is it running?"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def cache_stats() -> str:
    """Get embedding cache statistics (cache size, entry count)."""
    try:
        async with _client() as client:
            r = await client.get("/cache/stats")
            r.raise_for_status()
            data = r.json()

        lines = ["## Cache Statistics\n"]
        for key, val in data.items():
            lines.append(f"- **{key}**: {val}")

        return "\n".join(lines)
    except httpx.ConnectError:
        return f"Error: Cannot connect to embed-server at {API_URL}. Is it running?"
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
