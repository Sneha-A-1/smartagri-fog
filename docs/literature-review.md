# Literature review

The **Literature matrix** page (Research group in the sidebar) supports a systematic review from the first database
search to the tables in your thesis. Everything is stored in the platform database, so it is backed up with the rest of
your data folder.

## 1. Import references

1. Run your search in Scopus, Web of Science, IEEE Xplore or ACM Digital Library and export the results as **BibTeX**.
   From Zotero, right-click a collection, choose **Export Collection…** and pick **BibTeX** or **CSL JSON**.
2. On the **Papers** tab, type where the file came from (for example `Scopus`). This name is used in the PRISMA
   diagram's "records identified" box.
3. Click **Import .bib or .json** and choose the file.

Import one file per database. A paper already in the matrix is skipped when its DOI matches (ignoring case and any
`https://doi.org/` prefix) or its title matches after removing case, braces and punctuation. Skipped papers are
counted as *duplicates removed*. LaTeX accents such as `M{\"u}ller` are converted to `Müller`.

You can also add a paper by hand. Its citation key is generated as `firstauthorYEARword`, for example
`sharma2024scheduler`, and kept unique.

## 2. Screen (PRISMA 2020)

The **Screening** tab shows one paper at a time.

- **Title and abstract**: choose *Keep for full text* or *Exclude*.
- **Full text**: read the paper, then *Include in review* or *Exclude* with a reason. PRISMA 2020 asks you to report
  the reasons for full-text exclusions, so a reason is required here.

The flow on the left updates as you go. Copy its numbers into the PRISMA 2020 flow diagram template
(<https://www.prisma-statement.org/prisma-2020-flow-diagram>). The platform does not draw the final diagram for you,
because journals expect their own template.

| Box in the PRISMA diagram | Where the number comes from |
| --- | --- |
| Records identified (per database) | Every record in every import, including duplicates, plus papers added by hand |
| Duplicates removed | Records skipped at import |
| Records screened | Papers that have left the *Awaiting screening* stage |
| Records excluded | Papers marked *Excluded at screening* |
| Reports assessed for eligibility | Papers marked *Included* or *Excluded on full text* |
| Reports excluded, with reasons | *Excluded on full text*, grouped by reason |
| Studies included in review | Papers marked *Included* |

Deleting a paper removes it from these counts. Records skipped as duplicates stay counted, because they were part of
what the searches returned.

## 3. Classify included studies

Open a paper on the **Papers** tab and fill in the classification. Each field accepts several values; suggestions come
from a starting vocabulary plus every value you have already used, most used first, so spellings stay consistent.

| Field | Examples |
| --- | --- |
| Computing layers | iot, edge, fog, cloud |
| Techniques | Genetic algorithm, Other deep RL, Greedy heuristic |
| Metrics | Latency, Energy, Network usage, Cost |
| Agricultural domains | Irrigation, Crop disease, Livestock |
| Evaluation method | iFogSim, Real testbed, Analytical model |
| Datasets | PlantVillage, own field data |

Write the main contribution and limitations in your own words; these become the comparison table in your related-work
chapter.

## 4. Find gaps

The **Gap matrix** tab cross-tabulates any two fields, for example techniques against layers. Each cell counts the
papers tagged with both values; click a cell to list them. Empty cells are marked **gap**.

An empty cell is a gap in the papers you collected, not proof of a gap in the field. Before claiming it in a paper,
run a targeted search for that combination and record the query you used.

## 5. Export

| Button | File | Use |
| --- | --- | --- |
| BibTeX | `references.bib` | Included studies. Imported entries keep their original BibTeX, so nothing is lost |
| LaTeX table | `studies-table.tex` | A `longtable` summary of included studies with `\cite{}` keys. Needs `\usepackage{booktabs,longtable}` |
| CSV (all) | `literature-matrix.csv` | Every paper with its stage, reason and tags, for Excel or for the review's supplementary material |

The citation keys in the LaTeX table match the BibTeX file, so `\cite{gupta2017ifogsim}` resolves when both are in your
thesis project.
