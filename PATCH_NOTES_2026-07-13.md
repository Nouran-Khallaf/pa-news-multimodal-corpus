# Parser repair: 13 July 2026

## Cause

The earlier parser assumed that the first page `<h1>` and article body shared one parent container. The current NationBuilder theme uses a display `<h1>` in a page-header area and a repeated article heading in a sibling content area. Consequently, `choose_article_root()` selected a header-only subtree and `extract_body_blocks()` returned zero words.

## Repair

- Scores all plausible article containers rather than following only the first `<h1>`.
- Considers every matching `<h1>`, `<h2>` and `<h3>` title.
- Handles the article heading and body being siblings of the display heading.
- Extracts semantic paragraphs, lists and blockquotes.
- Adds a controlled line-based fallback for bodies represented with `<div>` and `<br>`.
- Stops before reactions, sign-in forms, comments and site footer content.
- Keeps explicit figure captions out of article body text.
- Uses JSON-LD `articleBody` as a final fallback where available.
- Adds diagnostic descriptions of the highest-scoring roots when extraction still fails.
- Adds `reparse`, which processes saved raw HTML without refetching article pages.

## Recommended recovery command

```bash
sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL" \
  slurm/01b_reparse_saved_html.sbatch
```

For a two-article pilot that also collects their images:

```bash
sbatch --export=ALL,CRAWLER_CONTACT_EMAIL="$CRAWLER_CONTACT_EMAIL",LIMIT_ARTICLES=2 \
  slurm/01b_reparse_saved_html.sbatch
```

The pilot records are retained, and a later full reparse skips them.

## HTML-verified parser update

The collector now prioritises the exact NationBuilder article-body selector verified from three real captures:

```css
main#content div#intro.intro > div.content
```

Additional changes:

- collects the article hero image from `og:image` or the banner background;
- labels images as `hero` or `inline`;
- extracts captions stored as plain text in the image's parent paragraph;
- excludes image captions from the linguistic body;
- records `body_selector`, `source_location`, and `dom_index` provenance;
- adds an offline HTML audit command and Slurm job;
- preserves the older scored parser only as a fallback for historical templates.
