# Implementation notes

- The live index observed on 12 July 2026 used `/news?page=N` and exposed pagination through page 181.
- News article URLs are not under a common `/news/` path; therefore discovery is restricted to headline links (`h3 a` and article-card variants) on the allowlisted news index rather than all same-domain links.
- Article extraction begins at the page `<h1>`, retains paragraph/list/blockquote/subheading blocks, and stops before reaction, sign-in, newsletter and footer markers.
- Images are selected only from the chosen article root. Lazy-loading attributes and the largest `srcset` candidate are supported.
- Explicit `<figcaption>` and caption-class siblings are captured. `alt` and `title` are retained as separate accessibility/HTML metadata.
- Unexpected image hosts are skipped and recorded so that the allowlist is extended only after manual review.
