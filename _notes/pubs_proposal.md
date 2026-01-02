Here’s a system that makes **Zotero your single source of truth**, makes updates “add paper → sync → regenerate site”, and turns OpenAlex into an **optional enrichment layer** (so “no match found” never blocks you again).

I’ll give you a concrete, step‑by‑step plan, plus two implementation variants depending on whether you want the pipeline to run **locally** (simplest) or in **GitHub Actions** (most automated).

---

## Core idea

### What’s going wrong today

Your Markdown file is acting like a database, and OpenAlex is acting like a validator/enricher. When OpenAlex can’t find something, you’re stuck because there’s nowhere “authoritative” to fix the record except by hand-editing the Markdown (or writing ever more matching logic).

### What to do instead

1. Put authoritative bibliographic metadata in **Zotero** (UI, search, DOI lookup, PDF metadata retrieval, etc.).
2. Export from Zotero in a predictable machine-readable format on every change.
3. Generate your website publications page(s) from that export.
4. Use OpenAlex only to add “nice-to-have” metadata (citations counts, OA flags, concepts, etc.) and cache it.

This way:

* **No OpenAlex match** = “no enrichment”, *not* “paper missing”.
* Updating your publications becomes **one action in a UI** (Zotero), not editing Markdown.

---

## Recommended pipeline (local-first)

### Step 1 — Make Zotero the authoritative database

Create a Zotero collection named something like:

* `My Publications` (top-level)

  * `Journal Articles`
  * `Conference Papers`
  * `Preprints`
  * `Book Chapters`
  * etc.

Use Zotero normally to add items (DOI, arXiv, publisher page via browser connector, “Retrieve Metadata for PDF”, manual entry for edge cases).

**Tip for “papers where no OpenAlex match”**: in this system you just add/fix them in Zotero like any other record. OpenAlex can be missing; your website will still be correct.

---

### Step 2 — Install Better BibTeX and set stable IDs

Install the Zotero plugin **Better BibTeX (BBT)**.

Why: it gives you better exports and, crucially, **stable citation keys** you can use as permanent IDs/slugs.

BBT supports “pinning” a key so it *won’t change* when you edit an item: you add `Citation Key: <yourkey>` as a line in the item’s **Extra** field. ([Retorque][1])

That pinned key becomes a fantastic stable identifier for:

* URL slugs (`/publications/<citekey>/`)
* manual overrides keyed by citekey
* deduplication

BBT also bundles a **Better CSL JSON** exporter that’s “pandoc-compatible CSL‑JSON” and includes citation keys. ([Retorque][2])

---

### Step 3 — Set up automatic export into your Jekyll repo

In Zotero, right‑click your `My Publications` collection → **Export Collection…**
Choose **“Better CSL JSON”** and check **“Keep updated”**.

Better BibTeX’s “Keep updated” registers the export and automatically re-exports whenever items change. ([Retorque][3])

Save it inside your website repo, e.g.:

```
site/
  _source_bibliography/
    publications.better-csl.json   # auto-generated, committed
```

This gives you the “easy update” property: edit Zotero → file updates automatically.

**Important note about tags:** CSL‑JSON is intentionally “for citing”, and doesn’t include Zotero tags. ([Zotero Forums][4])
That’s fine; you have two options for website-only fields (see Step 5).

---

### Step 4 — Add a small “website overrides” file

Create a file in your repo like:

```
_source_bibliography/
  overrides.yml
```

This is where you keep things Zotero isn’t great at storing (or doesn’t export in CSL‑JSON), e.g.:

* `featured: true`
* `pdf_url: ...`
* `code_url: ...`
* `data_url: ...`
* `talk_url: ...`
* `image: ...`
* `my_role: ...` (optional)
* custom grouping labels (optional)

Key it by the pinned citekey:

```yaml
# overrides.yml
Smith2024CoolPaper:
  featured: true
  pdf_url: /assets/papers/smith2024coolpaper.pdf
  code_url: https://github.com/me/coolpaper
  tags: [ml, interpretability]

Doe2022OldPaper:
  pdf_url: https://publisher.com/...
  notes: "Best paper award"
```

Why this matters: it keeps Zotero clean as bibliographic truth, and keeps “website presentation extras” in version-controlled text.

---

### Step 5 — Build script: Zotero export → Jekyll data

Write a script (Python is fine) that:

Input:

* `_source_bibliography/publications.better-csl.json` (auto-exported)
* `_source_bibliography/overrides.yml` (manual extras)
* optional cache files (OpenAlex enrichment)

Output:

* `_data/publications.json` (or `.yml`) for Jekyll to render
* optionally `_includes/publications.html` if you prefer pre-rendered HTML snippets

A good internal schema for `_data/publications.json`:

```json
{
  "id": "Smith2024CoolPaper",
  "title": "...",
  "year": 2024,
  "type": "article-journal",
  "authors": [{"family":"Smith","given":"A."}, ...],
  "venue": "Journal Name",
  "doi": "10....",
  "url": "...",
  "citation_html": "...",
  "links": {"pdf": "...", "code": "..."},
  "featured": true,
  "tags": ["ml","interpretability"],
  "openalex": {"id":"W...", "cited_by_count": 42}
}
```

Your Jekyll page then becomes a Liquid loop over that data.

---

### Step 6 — Choose how you generate the formatted citation string

You have three solid ways to get “replicate a known citation style with customization”:

#### Option A (robust + standard): CSL file + citeproc/Pandoc

* Pick an existing CSL style as your baseline (APA, Nature, IEEE, etc.) from the Zotero style ecosystem. ([Zotero][5])
* If you want to customize it, Zotero recommends starting from the right style and editing it, using the **CSL Visual Editor** and the **Zotero CSL Editor** for instant previews. ([Zotero][6])
* Better BibTeX explicitly recommends using **CSL exports (not BibTeX)** with Pandoc because BibTeX↔CSL conversion is lossy and casing heuristics can bite you. ([Retorque][7])

A practical pattern is:

* keep `style.csl` in `assets/csl/my-style.csl`
* run a formatting step in your build script that produces `citation_html` for each entry

Then you can *post-process* to add website-specific features:

* bold your name
* append “PDF / Code / Data” buttons
* add “Accepted”, “Best Paper”, etc.

#### Option B (very simple): ask Zotero Web API to format bibliography/citations

The Zotero Web API can return:

* CSL‑JSON (`format=csljson`)
* formatted bibliography XHTML (`format=bib`)
* formatted citations (`include=citation`)
  …and you can specify the CSL style by name (from Zotero Style Repo) or by URL to your custom CSL file. It also has `linkwrap=1` to make DOIs/URLs clickable. ([Zotero][8])

This can be great if you’d rather not run citeproc yourself.

Tradeoff: you’ll need API access (API key if the library isn’t public), and you’ll be dependent on network during builds.

#### Option C: Jekyll Scholar plugin (works well, but build constraints)

`jekyll-scholar` formats bibliographies and provides citation features inside Jekyll. ([GitHub][9])
But it **cannot run in the default GitHub Pages build environment**; you must build locally and push compiled output or use GitHub Actions. ([GitHub][9])

I’d only choose this if you already want a Ruby/plugin-heavy build pipeline.

---

## OpenAlex enrichment that won’t break your workflow

### Step 7 — Redefine OpenAlex as “optional enrichment”

You can keep your OpenAlex step, but change its purpose:

* Don’t use OpenAlex to decide whether a paper “exists”
* Use it only to attach extras: `openalex_id`, `cited_by_count`, OA status, concepts, etc.

OpenAlex makes DOI lookups easy:

* You can fetch a single work by DOI via the Works endpoint using an external ID URL form. ([docs.openalex.org][10])
* You can fetch **many DOIs per request** using a DOI filter with `|` separators (OpenAlex docs show this batch pattern). ([docs.openalex.org][11])
* They ask you to include your email (`mailto=`) for best performance/polite pool. ([docs.openalex.org][12])

### Step 8 — Handle “no match found” cleanly

In the new design, you have a simple policy:

1. **If DOI present** and OpenAlex returns nothing:

   * verify DOI correctness (typos, prefix, whitespace)
   * try the published DOI if you only have a preprint DOI (OpenAlex distinguishes canonical DOI for the published work). ([docs.openalex.org][13])
   * if still absent: treat as “OpenAlex coverage gap”; continue.

2. **If DOI absent**:

   * don’t block; your Zotero record is still authoritative
   * optionally run an OpenAlex `search` query by title/year and produce a “candidate matches report” for manual review (but it’s a report, not a blocker). ([docs.openalex.org][14])

3. **If you really want OpenAlex IDs for everything**:

   * allow a manual override in `overrides.yml`:

     ```yaml
     SomeKey:
       openalex_id: "https://openalex.org/W123..."
     ```
   * the script uses this when auto-match fails.

This is exactly what your current script *tried* to do, but now failure is low-cost.

---

## Jekyll rendering and “pleasing formatting” tips

### Step 9 — Render from `_data/` rather than generating one big Markdown file

Instead of generating a monolithic Markdown list, put structured data in:

* `_data/publications.json`

Then create a page like `publications.md`:

```markdown
---
layout: page
title: Publications
permalink: /publications/
---

{% assign pubs = site.data.publications | sort: "sort_key" | reverse %}

{% comment %}Group by year{% endcomment %}
{% assign years = pubs | map: "year" | uniq %}
{% for y in years %}
## {{ y }}

<ul class="pubs">
{% for p in pubs %}
  {% if p.year == y %}
    {% include publication.html p=p %}
  {% endif %}
{% endfor %}
</ul>
{% endfor %}
```

And `_includes/publication.html` might output:

* the CSL-formatted string (`citation_html`)
* plus a neat row of links (PDF / DOI / Code / Data)
* plus badges (Featured, Award, etc.)

This gives you:

* consistent formatting
* easy per-paper customization (via overrides)
* easy future reuse (e.g., generate CVs later)

### Step 10 — Styling strategies that look good

Once you have accurate metadata, the “good looking” part usually comes from:

1. **Typography & spacing**

   * Use CSS for line spacing and hanging indents (classic bibliography look).
   * Make link buttons small and consistent.

2. **Groupings**

   * By year (most common)
   * Or by type (Journal / Conference / Preprint) with year within type

3. **Author emphasis**

   * Post-process to bold your name variants (e.g., `A. Smith`, `Alex Smith`) in `citation_html`.
   * CSL generally can’t do “bold a specific author” easily; it’s simpler as a post-processing step.

4. **Venue emphasis**

   * Some styles italicize journals and bold volume; CSL can handle it if the style does.

5. **Add “selected publications”**

   * Use `featured: true` in overrides and render a “Selected” section above the full list.

---

## “Cloud build” variant (even less manual work)

If your site deploys from GitHub and you want to avoid committing exported JSON, you can:

1. Keep Zotero as source of truth and sync it.
2. In GitHub Actions:

   * fetch items from the Zotero Web API (private library needs an API key) ([Zotero][8])
   * request both `data` and formatted `bib`/`citation` in the response (the API supports multiple “include” formats) ([Zotero][8])
   * generate `_data/publications.json`
   * build/deploy Jekyll

Pros:

* Update is “edit Zotero + sync” (and trigger workflow)
  Cons:
* API key management, network dependency

---

## One-time migration from your existing Markdown

You don’t need to perfect this on day 1. A pragmatic migration plan:

1. **Parse your existing Markdown** to extract:

   * DOI if present
   * title
   * year (if present)

2. **Bulk-create Zotero items**

   * For DOI items: import via DOI (Zotero’s identifier lookup) or create RIS/BibTeX/CSL‑JSON and import
   * For “no DOI / no OpenAlex match”: create as manual Zotero entries and tag as `needs-review`

3. Once Zotero contains everything, stop editing the Markdown list by hand.

4. The website list is generated from Zotero exports going forward.

---

## Summary of the workflow you’ll end up with

**One-time setup**

* Zotero collection for your publications
* Better BibTeX installed
* Auto-export “Better CSL JSON” with “Keep updated” enabled ([Retorque][3])
* Repo contains build script + overrides + CSL style file

**Each time you publish a new paper**

1. Add it in Zotero (DOI/arXiv/publisher page/PDF metadata)
2. (Optional) pin citekey for a stable slug ([Retorque][1])
3. Export file updates automatically ([Retorque][3])
4. Run build script → commits updated `_data/publications.json`
5. Push → site updates

OpenAlex enrichment runs quietly and caches results; “no match” just means “no extra metrics”.

---

If you want, I can also sketch:

* a concrete directory layout for your Jekyll repo,
* a minimal `build_publications.py` structure (including OpenAlex batching and caching using the documented DOI filter pattern ([docs.openalex.org][11])),
* and two example CSL customization scenarios (e.g., “Nature-like but with full author list + DOI always shown”).

[1]: https://retorque.re/zotero-better-bibtex/exporting/ "Exporting items :: Better BibTeX for Zotero"
[2]: https://retorque.re/zotero-better-bibtex/index.print.html "Better BibTeX for Zotero"
[3]: https://retorque.re/zotero-better-bibtex/exporting/auto/ "Automatic export :: Better BibTeX for Zotero"
[4]: https://forums.zotero.org/discussion/114048/tags-export-in-json "Tags export in Json - Zotero Forums"
[5]: https://www.zotero.org/support/styles "
	styles [Zotero Documentation]
"
[6]: https://www.zotero.org/support/dev/citation_styles/style_editing_step-by-step "
	dev:citation_styles:style_editing_step-by-step [Zotero Documentation]
"
[7]: https://retorque.re/zotero-better-bibtex/exporting/pandoc/index.html "Markdown/Pandoc :: Better BibTeX for Zotero"
[8]: https://www.zotero.org/support/dev/web_api/v3/basics "
	dev:web_api:v3:basics [Zotero Documentation]
"
[9]: https://github.com/inukshuk/jekyll-scholar "GitHub - inukshuk/jekyll-scholar: jekyll extensions for the blogging scholar"
[10]: https://docs.openalex.org/api-entities/works/get-a-single-work?utm_source=chatgpt.com "Get a single work"
[11]: https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/filter-entity-lists?utm_source=chatgpt.com "Filter entity lists"
[12]: https://docs.openalex.org/how-to-use-the-api/api-overview?utm_source=chatgpt.com "API Overview"
[13]: https://docs.openalex.org/api-entities/works/work-object?utm_source=chatgpt.com "Work object"
[14]: https://docs.openalex.org/api-entities/works/search-works?utm_source=chatgpt.com "Search works"
