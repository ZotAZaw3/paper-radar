# paper-radar

Keep up with a research topic without reading every paper. Pulls recent
papers from Crossref, indexes their abstracts locally, and answers questions
about them with citations.

```console
$ papers pull "retrieval augmented generation"
28 papers from the last 180 days indexed under 'retrieval augmented generation'

$ papers ask "what evaluation metrics do they use?"

Most report hit-rate@k and nDCG for retrieval [1][3], while [2] uses an
LLM judge for answer faithfulness.

sources:
  [1] Agentic RAG: A Survey (2026-03)
      https://doi.org/10.xxxx/yyyy
  ...
```

## Setup

```bash
pip install -e .
cp .env.example .env    # then paste your key
```

Defaults to Gemini via its OpenAI-compatible endpoint. Any OpenAI-compatible
provider works — change `LLM_BASE_URL` and `LLM_MODEL` in `.env`.

## Usage

| Command | What it does |
| --- | --- |
| `papers pull "<topic>"` | Fetch + index recent papers. `--rows 30`, `--days 180` |
| `papers ask "<question>"` | Answer from the last topic you pulled. `--topic`, `-k 5` |

Each topic is its own local index under `data/chroma/`. Re-pulling a topic
refreshes it (upsert by DOI) rather than duplicating it. Papers without an
abstract are skipped — there'd be nothing to answer from.

Tests: `python test_papers.py`
