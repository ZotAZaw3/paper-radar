"""papers web UI - run the pipeline and watch each stage report as it finishes.

    python web.py   ->   http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator

from flask import Flask, Response, render_template, request

import papers

app = Flask(__name__)


def sse(**payload) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def stream(steps) -> Response:
    """Run a generator of events, turning any failure into an error event the page can show."""

    def run() -> Iterator[str]:
        try:
            yield from steps
        except Exception as exc:  # network, bad key, empty corpus - all belong on the page
            yield sse(error=f"{type(exc).__name__}: {exc}")

    return Response(run(), mimetype="text/event-stream")


def _clamp(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(request.args.get(name, default))))
    except ValueError:
        return default


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/pull")
def pull():
    topic = request.args.get("topic", "").strip()
    rows, days = _clamp("rows", 30, 1, 100), _clamp("days", 180, 1, 3650)
    if not topic:
        return stream(iter([sse(error="give me a topic first")]))

    def steps() -> Iterator[str]:
        papers.current_topic(topic)  # remember it, so the CLI and /ask agree on the default

        clock = time.time()
        payload = papers.fetch(topic, rows, days)
        found = len(payload.get("message", {}).get("items", []))
        yield sse(step="fetch", detail=f"{found} works returned", ms=int((time.time() - clock) * 1000))

        clock = time.time()
        parsed = papers.parse(payload)
        dropped = found - len(parsed)
        yield sse(
            step="filter",
            detail=f"{len(parsed)} kept" + (f", {dropped} dropped (no DOI, title, or real abstract)" if dropped else ""),
            ms=int((time.time() - clock) * 1000),
        )
        if not parsed:
            yield sse(error=f"nothing usable for {topic!r} in the last {days} days - try a broader topic")
            return

        clock = time.time()
        total = papers.index(topic, parsed)
        yield sse(
            step="index",
            detail=f"{len(parsed)} embedded into '{topic}' ({total} papers in the collection)",
            ms=int((time.time() - clock) * 1000),
        )
        yield sse(
            done=True,
            papers=[{"title": p["title"], "published": p["published"], "url": p["url"]} for p in parsed[:8]],
        )

    return stream(steps())


@app.get("/ask")
def ask():
    question = request.args.get("question", "").strip()
    k = _clamp("k", 5, 1, 20)
    # read every arg here: the generator below runs after the request context is gone
    wanted = request.args.get("topic") or None
    if not question:
        return stream(iter([sse(error="ask me something first")]))

    def steps() -> Iterator[str]:
        topic = papers.current_topic(wanted)

        clock = time.time()
        docs, metas = papers.retrieve(question, topic, k)
        yield sse(
            step="retrieve",
            detail=f"{len(docs)} nearest abstracts in '{topic}'",
            ms=int((time.time() - clock) * 1000),
        )
        if not docs:
            yield sse(error=f"nothing indexed for {topic!r} yet - pull it first")
            return

        clock = time.time()
        text = papers.answer(question, docs)
        yield sse(step="answer", detail="model replied", ms=int((time.time() - clock) * 1000))
        yield sse(
            done=True,
            answer=text,
            sources=[{"title": m["title"], "published": m["published"], "url": m["url"]} for m in metas],
        )

    return stream(steps())


if __name__ == "__main__":
    app.run(debug=True, threaded=True)
