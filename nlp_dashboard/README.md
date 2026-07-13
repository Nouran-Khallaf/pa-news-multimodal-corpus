# PA Corpus Explorer

A static, browser-based dashboard for the Patriotic Alternative news corpus. It provides:

- searchable document metadata;
- year, author, tag, image, word-count and date-quality filters;
- publication, term, n-gram, collocation, frame, legitimation, entity and readability visualisations;
- complete human-review queues for frame and legitimation candidates;
- a coded-language candidate queue;
- locally stored review decisions with JSON and CSV export;
- optional in-browser import of the current `articles.jsonl` for full article text and image metadata;
- data-quality and file-integrity summaries.

## Open the dashboard

The project has no package dependencies and no build step. Open `index.html` in a modern browser.

For the most reliable browser behaviour, run a local web server:

```bash
cd pa_nlp_dashboard
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

On Aire, port forwarding may be needed. The dashboard also works when `index.html` is opened directly because the analysis data is provided as a JavaScript file rather than fetched over HTTP.

## Attach the current corpus text

Click **Import articles JSONL** and select:

```text
outputs/pa_news/data/processed/articles.jsonl
```

The browser parses the file locally. It is not uploaded to a server. Full article text remains in memory for the current session; review decisions are stored separately in browser local storage.


## BNC informative-writing reference

The dashboard now accepts the original UCREL List 4.1 file directly:

```text
4_1_imagvinform_alpha.txt
```

It identifies the `FrIn` column as the informative-writing frequency per
million. To align the reference with the dashboard's cleaned spaCy lemma
frequencies, it retains only the List 4.1 lemma-head rows tagged as:

- `NoC` (common noun)
- `NoP` (proper noun)
- `Verb`
- `Adj`
- `Adv`

The parser excludes `@/@` inflection rows, function-word POS categories and
multiword or composite headwords. Duplicate lemma heads across retained POS
categories are summed. The supplied source produces 627 unique compatible
reference lemmas.

You can either upload the original List 4.1 text file in the browser, or use
the prepared file:

```text
data/bnc_informative_content_lemmas.csv
```

To recreate the prepared CSV:

```bash
python scripts/prepare_bnc_reference.py \
  --input /path/to/4_1_imagvinform_alpha.txt \
  --output data/bnc_informative_content_lemmas.csv
```

`FrIn` is already expressed per million words. The dashboard therefore treats
this source as a per-million reference and does not interpret missing entries
as zero by default.


## Human review

The review workspace includes three queues:

1. frame candidates;
2. legitimation candidates;
3. coded-language candidates.

Available decisions are `valid`, `reject`, and `uncertain`. Notes and reviewer initials can be recorded. Use **Export annotations** regularly; clearing browser storage removes locally saved decisions.

Keyboard controls in the review view:

- `1`: valid
- `2`: reject
- `3`: uncertain
- right arrow: next
- left arrow: previous

## Rebuild after rerunning the NLP analysis

```bash
python scripts/build_dashboard_data.py \
  /path/to/analysis-pa \
  data/dashboard_data.js \
  --reference-date 2026-07-13
```

Expected analysis layout:

```text
analysis-pa/
├── interim/
│   └── documents.csv
└── results/
    ├── term_frequencies.csv
    ├── 2gram_frequencies.csv
    ├── 3gram_frequencies.csv
    ├── collocations.csv
    ├── publication_by_year.csv
    ├── publication_by_month.csv
    ├── quality_control/
    └── political_discourse/
```

The data builder currently uses pandas. Install it in the active environment if needed:

```bash
python -m pip install pandas
```

## Interpretation

Automated frames, legitimation strategies, actor mentions, rhetorical markers and coded-language items are candidate retrieval outputs. They must not be reported as validated political findings until reviewed in context.


