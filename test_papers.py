"""Run me: python test_papers.py"""
from papers import _date, _norm, parse

ABSTRACT = "<jats:p>We  show that retrieval helps a lot, across many benchmarks and settings.</jats:p>" * 2


def test_parse():
    payload = {
        "message": {
            "items": [
                {  # good
                    "DOI": "10.1/a",
                    "title": ["A  Good\nPaper"],
                    "abstract": ABSTRACT,
                    "author": [{"given": "Ada", "family": "Lovelace"}, {"family": "Hopper"}],
                    "issued": {"date-parts": [[2026, 3]]},
                },
                {"title": ["No DOI"], "abstract": ABSTRACT},
                {"DOI": "10.1/c", "abstract": ABSTRACT},
                {"DOI": "10.1/d", "title": ["Stub abstract"], "abstract": "<jats:p>Too short.</jats:p>"},
            ]
        }
    }
    papers = parse(payload)
    assert [p["doi"] for p in papers] == ["10.1/a"], "thin/invalid records must be dropped"
    assert papers[0]["title"] == "A Good Paper"
    assert "jats" not in papers[0]["abstract"]
    assert papers[0]["authors"] == "Ada Lovelace, Hopper"
    assert papers[0]["published"] == "2026-03", "partial dates stay partial"
    assert papers[0]["url"] == "https://doi.org/10.1/a"


def test_dates():
    assert _date({"date-parts": [[2026]]}) == "2026"
    assert _date({"date-parts": [[2026, 3, 7]]}) == "2026-03-07"
    assert _date({"date-parts": [[None, None]]}) == ""
    assert _date(None) == ""
    assert _norm(None) == ""


if __name__ == "__main__":
    test_parse()
    test_dates()
    print("ok")
