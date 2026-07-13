# HTML extraction verification — 13 July 2026

The article extractor was revised after inspection of three saved, real PA news HTML captures representing both NationBuilder page templates:

- `page-pages-show-blog-post`
- `page-pages-show-blog-post-wide`

## Verified article structure

The stable article-body selector in all three captures is:

```css
main#content div#intro.intro > div.content
```

Metadata is stored outside that subtree:

- title: `meta[property="og:title"]`
- date: `.byline .lead`
- author: `.byline .linked-signup-name`
- tags: `main#content header a[href*="/tags/"]`
- hero image: `meta[property="og:image"]` with banner-background fallback

Inline article images occur within the body subtree. Some captions use a normal `figcaption`, but the live template can also store a caption as plain text in the same paragraph after an image, for example:

```html
<p style="text-align: center;"><img ...>Reaching out in Morley</p>
```

The revised parser stores that text as `figcaption` with `caption_source=inline_parent_text` and excludes it from the linguistic article body.

## Executed local verification

The offline verifier parsed all three supplied captures successfully:

| Measure | Result |
|---|---:|
| HTML captures | 3 |
| Verified selector present | 3 |
| Parsed successfully | 3 |
| Failed | 0 |
| Retained article words | 897 |
| Images identified | 13 |
| Hero images | 3 |
| Inline images | 10 |
| Explicit or inferred captions | 1 |

The per-file verification output is produced by `src/verify_saved_html.py`. Run it before reparsing the complete saved corpus.
