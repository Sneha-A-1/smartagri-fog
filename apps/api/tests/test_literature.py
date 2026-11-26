from __future__ import annotations

import json

from fastapi.testclient import TestClient

BIB = r"""@article{gupta2017ifogsim,
  title={{iFogSim}: A toolkit for modeling and simulation of resource management techniques in the {Internet of Things}, Edge and Fog computing environments},
  author={Gupta, Harshit and Vahid Dastjerdi, Amir and Ghosh, Soumya K. and Buyya, Rajkumar},
  journal={Software: Practice and Experience}, year={2017}, doi={10.1002/spe.2509}
}
@inproceedings{muller2020, title={Caf\'{e} scheduling for smart irrigation}, author={M{\"u}ller, Jan}, booktitle={Proc. X}, year=2020}
@article{dup, title={iFogSim: a toolkit for modeling and simulation of resource management techniques in the Internet of Things, edge and fog computing environments}, year=2017}
"""

CSL = [
    {
        "id": "k1",
        "type": "article-journal",
        "title": "Deep RL offloading for farms",
        "author": [{"family": "Rao", "given": "A."}],
        "issued": {"date-parts": [[2023]]},
        "DOI": "https://doi.org/10.1/ABC",
    },
    {"id": "k2", "type": "article-journal", "title": "Again the iFogSim one", "DOI": "10.1002/SPE.2509"},
]


def _import(client: TestClient, name: str, content: str, source: str = "Scopus") -> dict:
    return client.post(
        "/api/literature/import", files={"file": (name, content.encode(), "text/plain")}, data={"source": source}
    ).json()


def test_import_bibtex_and_csl_with_deduplication(client: TestClient) -> None:
    first = _import(client, "refs.bib", BIB)
    assert first["added"] == 2 and first["duplicates"] == 1  # same title, different case and braces
    second = _import(client, "zotero.json", json.dumps(CSL), source="Web of Science")
    assert second["added"] == 1 and second["duplicates"] == 1  # DOI match, despite case and URL prefix
    entries = client.get("/api/literature").json()
    titles = {e["title"] for e in entries}
    assert "Café scheduling for smart irrigation" in titles  # LaTeX accents decoded
    rao = next(e for e in entries if e["title"].startswith("Deep RL"))
    assert rao["doi"] == "10.1/abc" and rao["year"] == 2023 and rao["stage"] == "identified"
    assert (
        client.post("/api/literature/import", files={"file": ("x.bib", b"nothing here", "text/plain")}).status_code
        == 422
    )


def test_screening_tags_prisma_and_matrix(client: TestClient) -> None:
    _import(client, "refs.bib", BIB)
    _import(client, "zotero.json", json.dumps(CSL), source="Web of Science")
    by_title = {e["title"][:6]: e for e in client.get("/api/literature").json()}
    ifog, cafe, rao = by_title["iFogSi"], by_title["Café s"], by_title["Deep R"]

    client.patch(
        f"/api/literature/{ifog['id']}",
        json={
            "stage": "included",
            "layers": ["fog", "cloud", "fog"],
            "techniques": ["Greedy heuristic"],
            "evaluation": ["iFogSim"],
        },
    )
    client.patch(
        f"/api/literature/{rao['id']}", json={"stage": "included", "layers": ["edge"], "techniques": ["Other deep RL"]}
    )
    patched = client.patch(
        f"/api/literature/{cafe['id']}", json={"stage": "excluded", "exclusion_reason": "Not fog computing"}
    ).json()
    assert patched["exclusion_reason"] == "Not fog computing"
    assert client.get(f"/api/literature/{ifog['id']}").json()["layers"] == ["fog", "cloud"]  # de-duplicated

    p = client.get("/api/literature/prisma").json()
    assert p["identified"] == 5 and p["duplicates_removed"] == 2
    assert p["by_source"] == {"Scopus": 3, "Web of Science": 2}
    assert p["included"] == 2 and p["excluded_full_text"] == 1 and p["exclusion_reasons"] == {"Not fog computing": 1}

    m = client.get("/api/literature/matrix", params={"rows": "techniques", "cols": "layers"}).json()
    assert m["cols"] == ["edge", "fog", "cloud"] and m["total"] == 2
    r = m["rows"].index("Greedy heuristic")
    assert m["counts"][r] == [0, 1, 1]

    vocab = client.get("/api/literature/vocabulary").json()
    assert vocab["suggestions"]["layers"][:2] == ["fog", "cloud"] or "fog" in vocab["suggestions"]["layers"]
    assert "included" in vocab["stages"]


def test_manual_entry_and_exports(client: TestClient) -> None:
    e = client.post(
        "/api/literature", json={"title": "A fog scheduler", "authors": "Sharma, Priya and Li, Wei", "year": 2024}
    ).json()
    assert e["bibtex_key"] == "sharma2024scheduler"
    assert client.post("/api/literature", json={"title": "A FOG scheduler!"}).status_code == 409
    client.patch(f"/api/literature/{e['id']}", json={"stage": "included", "layers": ["fog"], "metrics": ["Latency"]})
    bib = client.get("/api/literature/export/bib", params={"stage": "included"}).text
    assert "@article{sharma2024scheduler" in bib
    tex = client.get("/api/literature/export/tex", params={"stage": "included"}).text
    assert r"\cite{sharma2024scheduler}" in tex and "longtable" in tex
    csv_text = client.get("/api/literature/export/csv").text
    assert csv_text.splitlines()[0].startswith("bibtex_key,title") and "Latency" in csv_text
    assert client.delete(f"/api/literature/{e['id']}").status_code == 204
