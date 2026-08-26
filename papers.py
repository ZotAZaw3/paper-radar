#!/usr/bin/env python
"""papers - pull recent papers on a topic from Crossref, then ask questions about them.

    papers pull "retrieval augmented generation"
    papers ask "what evaluation metrics do they use?"
"""
from __future__ import annotations

import argparse
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import chromadb
import requests
from dotenv import load_dotenv
from openai import OpenAI

DATA = Path(__file__).parent / "data"
WORKS_URL = "https://api.crossref.org/works"
RETRY_CODES = {429, 500, 502, 503, 504}
MIN_ABSTRACT = 100  # chars; shorter abstracts are stubs, not worth indexing


def _norm(value: str | None) -> str:
    """Strip JATS markup (Crossref abstracts are XML) and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"</?jats:[^>]*>", " ", value or "")).strip()


def _date(node: dict | None) -> str:
    """Crossref date-parts -> 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'. Partial dates are common."""
    parts = [p for p in ((node or {}).get("date-parts") or [[]])[0] if p is not None]
    return "-".join(f"{p:02d}" if i else f"{p:04d}" for i, p in enumerate(parts))


def parse(payload: dict) -> list[dict]:
    """Crossref /works payload -> indexable records. Drops anything too thin to answer from."""
    papers = []
    for item in payload.get("message", {}).get("items", []):
        doi, titles = item.get("DOI"), item.get("title") or []
        title, abstract = _norm(titles[0] if titles else ""), _norm(item.get("abstract"))
        if not (doi and title) or len(abstract) < MIN_ABSTRACT:
            continue
        authors = [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in item.get("author") or []
            if a.get("given") or a.get("family")
        ]
        papers.append(
            {
                "doi": doi,
                "title": title,
                "abstract": abstract,
                "authors": ", ".join(authors),
                "published": _date(item.get("issued")),
                "url": item.get("URL") or f"https://doi.org/{doi}",
            }
        )
    return papers


def fetch(topic: str, rows: int, days: int) -> list[dict]:
    params = {
        "query": topic,
        "rows": rows,
        "filter": f"from-pub-date:{date.today() - timedelta(days=days)},has-abstract:true",
    }
    backoff, problem = 1.0, ""
    for _ in range(5):
        try:
            response = requests.get(WORKS_URL, params=params, timeout=30)
        except requests.RequestException as exc:  # flaky network, worth another go
            problem = str(exc)
        else:
            if response.status_code == 200:
                return parse(response.json())
            if response.status_code not in RETRY_CODES:
                response.raise_for_status()
            problem = f"HTTP {response.status_code}"
        time.sleep(backoff)
        backoff *= 2
    raise SystemExit(f"crossref kept failing ({problem}), try again later")


def collection(topic: str):
    """One Chroma collection per topic. Chroma embeds with all-MiniLM-L6-v2 by default."""
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60] or "papers"
    return chromadb.PersistentClient(path=str(DATA / "chroma")).get_or_create_collection(slug)


def current_topic(topic: str | None) -> str:
    """--topic wins; otherwise reuse whatever was pulled last."""
    marker = DATA / "last_topic.txt"
    if topic:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(topic, encoding="utf-8")
        return topic
    if not marker.exists():
        raise SystemExit('nothing indexed yet - run: papers pull "your topic"')
    return marker.read_text(encoding="utf-8").strip()


def pull(topic: str, rows: int, days: int) -> None:
    papers = fetch(topic, rows, days)
    if not papers:
        raise SystemExit(f"crossref returned no usable papers for {topic!r} in the last {days} days")
    # upsert by DOI: re-pulling a topic refreshes it instead of duplicating it
    collection(topic).upsert(
        ids=[p["doi"] for p in papers],
        documents=[f"{p['title']}\n\n{p['abstract']}" for p in papers],
        metadatas=[{k: v for k, v in p.items() if k != "abstract"} for p in papers],
    )
    print(f"{len(papers)} papers from the last {days} days indexed under {topic!r}")


def ask(question: str, topic: str, k: int) -> None:
    hits = collection(topic).query(query_texts=[question], n_results=k)
    docs, metas = hits["documents"][0], hits["metadatas"][0]
    if not docs:
        raise SystemExit(f"no papers indexed for {topic!r} - run pull first")

    context = "\n\n".join(f"[{i}] {doc}" for i, doc in enumerate(docs, 1))
    load_dotenv(Path(__file__).parent / ".env")
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SystemExit("set LLM_API_KEY in .env (copy .env.example)")
    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    )
    reply = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "Answer only from the numbered paper abstracts. Cite them like [1]. "
                "If they do not answer the question, say so instead of guessing.",
            },
            {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
        ],
    )
    print(f"\n{reply.choices[0].message.content}\n\nsources:")
    for i, meta in enumerate(metas, 1):
        print(f"  [{i}] {meta['title']} ({meta['published']})\n      {meta['url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pull", help="fetch recent papers on a topic and index them")
    p.add_argument("topic")
    p.add_argument("--rows", type=int, default=30, help="papers to fetch (default 30)")
    p.add_argument("--days", type=int, default=180, help="how far back to look (default 180)")

    a = sub.add_parser("ask", help="ask a question about the indexed papers")
    a.add_argument("question")
    a.add_argument("--topic", help="defaults to the last topic you pulled")
    a.add_argument("-k", type=int, default=5, help="papers to feed the model (default 5)")

    args = parser.parse_args()
    if args.cmd == "pull":
        pull(current_topic(args.topic), args.rows, args.days)
    else:
        ask(args.question, current_topic(args.topic), args.k)


if __name__ == "__main__":
    main()
