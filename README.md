# Patriotic Alternative public-news multimodal corpus pipeline

This repository now contains the **complete research workflow**, not only the crawler. It combines public-page collection, raw/derived separation, schemas, manifests, quality control, advanced NLP, political-discourse analysis, image analysis, image–text analysis, human-review templates and Slurm jobs.

## What each stage produces

1. **Collection (`src/collect_pa_news.py`)** — public news URLs, raw HTML, article text, tags, dates, authors, embedded images, alt text and explicit captions.
2. **Validation (`src/validate_pa_news.py`)** — schema, hash, duplicate and file-consistency checks.
3. **Reprocessing and quality control (`src/normalise.py`, `src/extract.py`, `src/deduplicate.py`)** — deterministic analysis layer, raw-HTML re-extraction audit, exact and near-duplicate candidates.
4. **Text preprocessing (`src/preprocess_text.py`)** — document, sentence, token and named-entity tables.
5. **Corpus analysis (`src/analyse_corpus.py`, `src/analyse_collocations.py`)** — trends, readability, lexical diversity, terms, n-grams, comparator keyness and collocations.
6. **Topics (`src/analyse_topics.py`)** — document embeddings, three BERTopic runs and assignment stability.
7. **Political discourse (`src/analyse_political_discourse.py`)** — candidate frames, legitimation strategies, actors, predications, co-occurrence and optional NLI frame scores.
8. **Coded-language review (`src/build_coded_language_candidates.py`)** — an evidence queue with blank interpretation fields; it never automatically calls a term a dog whistle.
9. **Images (`src/analyse_images.py`, `src/embed_and_cluster_images.py`)** — perceptual duplicates, OCR, generated captions, provisional visual categories, optional objects and visual clusters.
10. **Image–text relations (`src/analyse_multimodal.py`)** — alignment with title, lead and caption; OCR overlap; stratified human-review samples.

## Installation on Aire

```bash
cd /mnt/scratch/smlnkh
unzip pa_news_multimodal_corpus.zip
cd pa_news_multimodal_corpus
conda activate mlenv
python -m pip install -r requirements-gpu.txt
python -m spacy download en_core_web_trf
pytest -q
```

For OCR, ensure the `tesseract` executable is available through an Aire module or conda package. OCR is optional.

## Collection sequence

Use a transparent institutional contact:

```bash
export CRAWLER_CONTACT_EMAIL='your.name@university.ac.uk'
mkdir -p logs
sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL" slurm/00_preflight_pa_news.sbatch
sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL" slurm/00b_pilot_pa_news.sbatch
# Inspect five articles and their images, then:
sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL" slurm/01_collect_pa_news.sbatch
sbatch slurm/02_validate_pa_news.sbatch
sbatch slurm/02b_normalise_deduplicate.sbatch
```

Collection is single-threaded and CPU/network-bound. It stops on 401, 403 or 429 and does not circumvent controls.

## Analysis sequence

CPU corpus and rule-based political analysis:

```bash
sbatch slurm/03_preprocess_and_cpu_analysis.sbatch
```

To use a matched comparator, set a folder of `.txt` files, or a CSV/JSONL containing `text` or `body`:

```bash
COMPARATOR_PATH=/path/to/matched_political_news sbatch --export=ALL,COMPARATOR_PATH slurm/03_preprocess_and_cpu_analysis.sbatch
```

GPU stages:

```bash
sbatch slurm/04_topics_gpu.sbatch
sbatch slurm/05_political_zero_shot_gpu.sbatch
sbatch slurm/06_images_gpu.sbatch
sbatch slurm/06b_objects_gpu.sbatch       # optional and slower
sbatch slurm/07_multimodal_gpu.sbatch
```

Or submit dependency-linked jobs after collection and validation:

```bash
bash slurm/08_all_analysis_dependency.sh
```

## Main outputs

```text
outputs/pa_news/
├── data/raw/html/
├── data/raw/images/objects/
├── data/processed/articles.jsonl
├── data/processed/images.jsonl
├── manifests/
└── analysis/
    ├── interim/
    │   ├── documents.csv
    │   ├── sentences.jsonl
    │   ├── entities.csv
    │   └── tokens.csv.gz
    └── results/
        ├── corpus_summary.json
        ├── term_frequencies.csv
        ├── keyness.csv
        ├── collocations.csv
        ├── topics/
        ├── political_discourse/
        ├── images/
        └── multimodal/
```

## Interpretation boundary

Automated NER, topics, NLI frames, OCR, captions, visual labels, objects and similarities are **model-assisted discovery outputs**. They are not validated claims about ideology, intent, truthfulness, identity, affiliation or real-world organisational relationships. Use the annotation templates in `analysis/`, inspect concordances and images, and independently code a documented sample before reporting substantive findings.

The image pipeline intentionally excludes face recognition and demographic or sensitive-attribute inference. Raw HTML, full text and images should remain access-controlled until rights, data-protection and ethics reviews permit wider distribution.

## Repairing zero-word article extraction

The current NationBuilder theme separates the display `<h1>` from the article-content container and repeats the title inside the content area. Repository versions created before 13 July 2026 may therefore report:

```text
ValueError: extracted body is too short (0 words); selectors need review
```

The repaired parser no longer assumes that the first `<h1>` owns the article body. It scores likely content containers, recognises repeated title headings, supports text stored in `<div>`/`<br>` structures, and excludes captions, reactions, comments and footer material.

Raw HTML was saved before the failed parsing step. Reuse it rather than downloading every article page again:

```bash
export CRAWLER_CONTACT_EMAIL="YOUR_INSTITUTIONAL_EMAIL"

sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL",LIMIT_ARTICLES=2 \
  slurm/01b_reparse_saved_html.sbatch
```

Inspect the first two JSONL records, then submit the full recovery job:

```bash
head -n 1 outputs/pa_news/data/processed/articles.jsonl | python -m json.tool
sed -n '2p' outputs/pa_news/data/processed/articles.jsonl | python -m json.tool

sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL" \
  slurm/01b_reparse_saved_html.sbatch
```

The `reparse` command does not request article HTML. It reads `outputs/pa_news/data/raw/html`, recovers request metadata from `manifests/requests.jsonl`, and contacts the network only for article images unless `--skip-images` is supplied.

## Verified PA NationBuilder HTML structure

The current collector first targets the site-specific article subtree:

```css
main#content div#intro.intro > div.content
```

The rule was verified offline against three saved live captures covering both the normal and wide blog-post templates. Hero images are collected from `og:image`; inline images are collected from the article subtree. Plain text after an image in the same centred paragraph is retained as an image caption and removed from the linguistic body. See `HTML_VERIFICATION_2026-07-13.md`.

Before reparsing all saved pages, audit the local HTML without contacting the website:

```bash
sbatch slurm/01a_verify_saved_html.sbatch
cat outputs/pa_news/manifests/html_extraction_audit.json
```

Then recover the corpus from saved HTML:

```bash
sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL" \
  slurm/01b_reparse_saved_html.sbatch
```
