# embed-search-mcp

MCP (Model Context Protocol) server for semantic code search via [embed-server](https://github.com/egorkaBurkenya/embed-server).

Search your codebase by meaning, not just text — powered by local embeddings.

## Setup

### 1. Backend

Deploy [embed-server](https://github.com/egorkaBurkenya/embed-server) — the embedding + indexing backend.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your embed-server URL and API key
```

| Variable | Default | Description |
|---|---|---|
| `EMBED_API_URL` | `http://localhost:8100` | Base URL of embed-server API |
| `EMBED_API_KEY` | (empty) | API key for authentication |

### 4. Register with Claude Code

```bash
claude mcp add embed-search -e EMBED_API_URL=http://your-server:8100 -e EMBED_API_KEY=your-key -- python /path/to/server.py
```

## Tools

- **search_code** — Semantic search over indexed codebases. Find code by meaning.
- **index_project** — Index a local directory (respects `.gitignore`).
- **list_projects** — List all indexed projects.
- **project_info** — Get details about a specific project.
- **cache_stats** — Embedding cache statistics.

## License

MIT
