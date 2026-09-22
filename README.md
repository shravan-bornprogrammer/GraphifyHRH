# Helpdesk Knowledge Graph API

A FastAPI service that converts the `Helpdesk_POC.ipynb` notebook into a
reusable HTTP API — and, unlike the notebook, it isn't tied to one fixed
spreadsheet schema. Upload **any** Excel/CSV, tell the API which columns
play which role, and it builds the same kind of searchable knowledge graph
+ graph-grounded Q&A the notebook produced.

## What changed vs. the notebook

| Notebook | API |
|---|---|
| Hard-coded columns (`Ticket Number`, `Category`, `Topic`, `Subtopic`, `Intent`, `Feedback Summary`, `Sentiment`) | Any columns — you map them at request time (or accept auto-suggested roles) |
| Ran top-to-bottom in a Jupyter kernel, one dataset at a time | Stateless HTTP endpoints, many concurrent sessions (one per uploaded file) |
| `net.show(...)` wrote a local HTML file | `GET /api/graph/view/{id}` serves the interactive graph over HTTP |
| `ollama.chat(model="mistral:7b")` hard-coded | Pluggable `LLM_PROVIDER` (`ollama` / `openai` / `anthropic` / `none`) |
| KeyBERT/embeddings assumed always available | Optional — the API degrades gracefully (skips those steps) if those packages/models aren't installed |

## Project layout

```
app/
  main.py                  FastAPI routes
  config.py                Settings (env-driven)
  models.py                Pydantic request/response schemas
  storage.py                Session store (in-memory + disk-persisted)
  services/
    data_loader.py         Reads any .xlsx/.xls/.csv, profiles columns
    nlp_extraction.py      spaCy concepts/entities, KeyBERT issues, canonicalization
    graph_builder.py       Builds the NetworkX graph from a dynamic column mapping
    graph_viz.py           Renders the searchable vis-network HTML
    llm_qa.py               GraphRAG-style Q&A over the graph
run.py                     `python run.py` to start the dev server
requirements.txt
.env.example
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Entity extraction (extractor="spacy" / "both")
python -m spacy download en_core_web_sm

cp .env.example .env   # then edit LLM_PROVIDER / API keys as needed
python run.py           # http://localhost:8000/docs
```

Everything under `requirements.txt`'s "Optional" sections (KeyBERT,
sentence-transformers, scikit-learn, the LLM SDKs) can be skipped if you
only need `extractor="spacy"` or `extractor="none"` and
`LLM_PROVIDER=none` — the service still runs and just returns raw graph
facts instead of an LLM-generated answer.

## Workflow

### 1. Upload any spreadsheet

```bash
curl -F "file=@my_tickets.xlsx" http://localhost:8000/api/upload
```

Returns a `session_id` plus a profile of every column with a
`suggested_role` (`id` / `hierarchy` / `attribute` / `text` / `ignore`) —
e.g. a short, low-cardinality text column like "Category" is suggested as
`hierarchy`; a long free-text column like "Description" is suggested as
`text`; a near-unique column like "Ticket Number" is suggested as `id`.
These are hints, not requirements — you decide the final mapping.

### 2. Build the graph with your column mapping

```bash
curl -X POST http://localhost:8000/api/graph/build \
  -H "Content-Type: application/json" \
  -d '{
        "session_id": "<from step 1>",
        "id_column": "Ticket Number",
        "hierarchy_columns": ["Category", "Topic", "Subtopic"],
        "attribute_columns": ["Intent", "Sentiment"],
        "text_columns": ["Feedback Summary"],
        "extractor": "spacy",
        "extract_people": true,
        "canonicalize": false
      }'
```

- `hierarchy_columns`: any ordered list of categorical columns becomes a
  parent → child chain (works for 1, 3, or 10 levels — not just the
  notebook's fixed 3).
- `attribute_columns`: flat facts attached directly to each row (status,
  priority, sentiment, owner, date, ...).
- `text_columns`: free-text columns run through NLP; each becomes
  `Keyword`/`Issue`/`Person` nodes depending on `extractor`.
- `extractor`: `"spacy"` (concepts/entities), `"keybert"` (short issue
  phrases), `"both"`, or `"none"`.
- `canonicalize: true` clusters near-duplicate issue phrases (e.g. "salary
  was late" and "salary credited late") into one node, via sentence
  embeddings + agglomerative clustering — same technique as the notebook's
  `canonicalize_issues`.

### 3. View the interactive graph

Open `view_url` from the build response (`/api/graph/view/{session_id}`)
in a browser — same search/highlight/focus UI as the notebook's
`render_graph_with_search`, but now dynamically colored for whatever node
types your columns produced (not a fixed 8-type legend).

### 4. Ask questions grounded in the graph

```bash
curl -X POST http://localhost:8000/api/graph/ask \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<id>", "question": "What are the major problems with compensation?"}'
```

Matches your question against node labels, pulls the surrounding subgraph
(`radius` hops, default 2), and — if `LLM_PROVIDER` isn't `none` — asks the
configured LLM to answer using only those facts (same guarded-RAG prompt
as the notebook's `ask_hr_bot`). The response also includes a
`subgraph_view_url` so you can see exactly which part of the graph was
used.

### 5. Manage sessions

```bash
curl http://localhost:8000/api/sessions            # list
curl -X DELETE http://localhost:8000/api/sessions/<id>
```

Sessions (uploaded data + built graph) persist to `./storage/` so they
survive a process restart, keyed by `session_id`.

## Notes / production hardening ideas

- **Storage**: swap `app/storage.py`'s pickle-on-disk store for
  Redis/Postgres if you need multi-worker/multi-instance deployment
  (pickle files aren't safe to share across processes without a lock).
- **Auth**: none is included — add an API-key/OAuth dependency on the
  router if this is exposed beyond a trusted network.
- **Large files**: `MAX_UPLOAD_BYTES` guards request size; for very large
  graphs consider paginating `/api/graph/view` or pre-filtering
  `subset_nodes`.
- **LLM cost/latency**: `/api/graph/ask` calls out to whichever
  `LLM_PROVIDER` you configure — cache repeated questions if needed.
