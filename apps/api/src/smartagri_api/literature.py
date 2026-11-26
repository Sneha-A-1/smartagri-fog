"""Literature review support: import (BibTeX, CSL-JSON), de-duplication, PRISMA screening and exports."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from typing import Any

import bibtexparser
from bibtexparser import middlewares

DIMENSIONS = ["layers", "techniques", "metrics", "domains", "evaluation", "datasets", "tags"]

# Screening stages, following the PRISMA 2020 flow.
STAGES = {
    "identified": "Awaiting screening",
    "screened_out": "Excluded at screening",
    "full_text": "Full text to assess",
    "excluded": "Excluded on full text",
    "included": "Included",
}

# Suggested values. Free text is always allowed; suggestions keep tags consistent across papers.
VOCABULARY: dict[str, list[str]] = {
    "layers": ["iot", "edge", "fog", "cloud"],
    "techniques": [
        "FCFS",
        "Round Robin",
        "Priority",
        "EDF",
        "Min-Min",
        "Max-Min",
        "HEFT",
        "Greedy heuristic",
        "GA",
        "PSO",
        "ACO",
        "GWO",
        "WOA",
        "NSGA-II",
        "Other metaheuristic",
        "DQN",
        "PPO",
        "Other deep RL",
        "Federated learning",
        "Supervised ML",
        "CNN",
        "LSTM",
        "Transformer",
        "MILP/ILP",
        "Game theory",
        "Fuzzy logic",
        "Queueing model",
        "Digital twin",
        "Blockchain",
    ],
    "metrics": [
        "Latency",
        "Response time",
        "Deadline success",
        "Energy",
        "Cost",
        "Network usage",
        "Bandwidth",
        "Throughput",
        "Makespan",
        "Resource utilisation",
        "Load balancing",
        "Accuracy",
        "Data freshness (AoI)",
        "Reliability",
        "Availability",
        "Scalability",
        "Security",
    ],
    "domains": [
        "Irrigation",
        "Crop health / disease",
        "Pest detection",
        "Yield prediction",
        "Soil monitoring",
        "Weather",
        "Greenhouse",
        "Livestock",
        "Aquaculture",
        "Supply chain",
        "General smart farming",
    ],
    "evaluation": [
        "iFogSim",
        "CloudSim",
        "YAFS",
        "EdgeCloudSim",
        "Other simulator",
        "Testbed",
        "Real deployment",
        "Analytical model",
        "None",
    ],
    "datasets": ["PlantVillage", "PlantDoc", "Crop recommendation (Kaggle)", "Proprietary field data", "Synthetic"],
    "tags": [],
}


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I).lower()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


def parse_bibtex(text: str) -> tuple[list[dict[str, Any]], int]:
    """Parse BibTeX into entry dicts. Returns (entries, number of blocks that failed to parse)."""
    library = bibtexparser.parse_string(text, append_middleware=[middlewares.LatexDecodingMiddleware()])
    entries = []
    for e in library.entries:
        fields = {f.key.lower(): _clean(str(f.value)) for f in e.fields}
        raw = bibtexparser.write_string(bibtexparser.Library([e])).strip()
        authors = " and ".join(a.strip() for a in fields.get("author", "").split(" and ") if a.strip())
        entries.append(
            {
                "bibtex_key": e.key,
                "entry_type": e.entry_type.lower(),
                "title": fields.get("title", "(untitled)"),
                "authors": authors,
                "year": _year(fields.get("year") or fields.get("date", "")),
                "venue": fields.get("journal") or fields.get("booktitle") or fields.get("publisher", ""),
                "doi": normalize_doi(fields.get("doi")),
                "url": fields.get("url", ""),
                "abstract": fields.get("abstract", ""),
                "keywords": fields.get("keywords", ""),
                "raw_bibtex": raw,
            }
        )
    return entries, len(library.failed_blocks)


def parse_csl_json(text: str) -> tuple[list[dict[str, Any]], int]:
    """Parse CSL-JSON (Zotero 'Better CSL JSON' or 'CSL JSON' export)."""
    data = json.loads(text)
    items = data if isinstance(data, list) else data.get("items", [])
    entries, failed = [], 0
    for it in items:
        if not isinstance(it, dict) or not it.get("title"):
            failed += 1
            continue
        authors = " and ".join(
            ", ".join(p for p in [a.get("family", ""), a.get("given", "")] if p) or a.get("literal", "")
            for a in it.get("author", [])
        )
        issued = it.get("issued", {}).get("date-parts", [[None]])
        year = issued[0][0] if issued and issued[0] else None
        entries.append(
            {
                "bibtex_key": it.get("citation-key") or it.get("id") or "",
                "entry_type": it.get("type", "article"),
                "title": _clean(it["title"]),
                "authors": authors,
                "year": int(year) if isinstance(year, int | str) and str(year).isdigit() else None,
                "venue": it.get("container-title", "") or it.get("publisher", ""),
                "doi": normalize_doi(it.get("DOI")),
                "url": it.get("URL", ""),
                "abstract": it.get("abstract", ""),
                "keywords": it.get("keyword", ""),
                "raw_bibtex": "",
            }
        )
    return entries, failed


def _year(value: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", value or "")
    return int(m.group(0)) if m else None


def make_key(authors: str, year: int | None, title: str) -> str:
    first = authors.split(" and ")[0] if authors else ""
    family = first.split(",")[0] if "," in first else (first.split()[-1] if first.split() else "anon")
    family = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", family).encode("ascii", "ignore").decode().lower())
    word = next((w for w in normalize_title(title).split() if len(w) > 3), "paper")
    return f"{family or 'anon'}{year or ''}{word}"


def to_bibtex(entry: dict[str, Any]) -> str:
    if entry.get("raw_bibtex"):
        return entry["raw_bibtex"]
    fields = {
        "title": entry["title"],
        "author": entry.get("authors"),
        "year": entry.get("year"),
        "journal": entry.get("venue"),
        "doi": entry.get("doi"),
        "url": entry.get("url"),
    }
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@{entry.get('entry_type') or 'article'}{{{entry['bibtex_key']},\n{body}\n}}"


def to_csv(entries: list[dict[str, Any]]) -> str:
    cols = [
        "bibtex_key",
        "title",
        "authors",
        "year",
        "venue",
        "doi",
        "stage",
        "exclusion_reason",
        "relevance",
        *DIMENSIONS,
        "contribution",
        "limitations",
        "notes",
    ]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(cols)
    for e in entries:
        w.writerow(
            ["; ".join(e.get(c) or []) if c in DIMENSIONS else ("" if e.get(c) is None else e.get(c)) for c in cols]
        )
    return out.getvalue()


def _tex(s: str) -> str:
    for a, b in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
    ]:
        s = s.replace(a, b)
    return s


def to_latex(entries: list[dict[str, Any]]) -> str:
    """Summary table of studies with \\cite keys, for the review chapter. Requires booktabs and longtable."""
    lines = [
        "% Generated by SmartAgri-Fog. Requires \\usepackage{booktabs,longtable}.",
        "% Citation keys match the BibTeX export.",
        r"\begin{longtable}{p{2.2cm}p{1.6cm}p{3.2cm}p{3.2cm}p{2.2cm}}",
        r"\caption{Summary of reviewed studies.}\\",
        r"\toprule",
        r"Study & Layers & Techniques & Metrics & Evaluation \\",
        r"\midrule",
        r"\endhead",
    ]
    for e in sorted(entries, key=lambda x: (x.get("year") or 0, x["bibtex_key"])):
        cells = [
            ", ".join(_tex(v) for v in (e.get(d) or [])) or "--"
            for d in ("layers", "techniques", "metrics", "evaluation")
        ]
        lines.append(rf"\cite{{{e['bibtex_key']}}} ({e.get('year') or 'n.d.'}) & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{longtable}"]
    return "\n".join(lines) + "\n"
