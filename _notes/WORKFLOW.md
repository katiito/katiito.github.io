# Publications Workflow

This document describes how to manage and update the publications page on your Jekyll website.

## Overview

**Zotero is the single source of truth** for your publications. The workflow is:

1. Manage publications in Zotero
2. Better BibTeX auto-exports to `papers_zotero.json`
3. Optionally enrich with citation counts from OpenAlex
4. Generate `papers.md` for the Jekyll site

## Prerequisites

- **Zotero** with **Better BibTeX** extension installed
- A Zotero collection configured for auto-export (Better CSL-JSON format)
- Python 3.9+ with the `requests` library

## Files

| File | Purpose |
|------|---------|
| `papers_zotero.json` | Auto-exported from Zotero (source of truth) |
| `papers_enriched.json` | Zotero data + OpenAlex citation counts |
| `papers.md` | Generated markdown for Jekyll |
| `openalex_cache.json` | Cached OpenAlex API responses |
| `generate_papers_md.py` | Script to generate papers.md |
| `enrich_from_openalex.py` | Script to add citation counts |

## Adding New Publications

1. **Add the paper to Zotero** in your publications collection
2. Better BibTeX will auto-update `papers_zotero.json`
3. Run the enrichment and generation scripts (see below)

### Entry Numbering

For legacy compatibility, add `Original entry: [N]` to the Zotero note field where N is the entry number. New papers without this will be auto-assigned the next available number.

## Updating the Papers Page

### Quick update (no new citation counts)

```bash
python generate_papers_md.py -i papers_zotero.json
```

### Full update with citation counts

```bash
# Step 1: Enrich with OpenAlex citation counts
python enrich_from_openalex.py

# Step 2: Generate the papers page
python generate_papers_md.py -i papers_enriched.json
```

### Force refresh citation counts

To ignore the cache and fetch fresh data from OpenAlex:

```bash
python enrich_from_openalex.py --refresh
```

## Script Options

### generate_papers_md.py

```
Usage: python generate_papers_md.py [OPTIONS]

Options:
  -i, --input FILE      Input CSL-JSON file (default: papers_zotero.json)
  -o, --output FILE     Output markdown file (default: papers.md)
  --highlight NAME      Author surname to bold (default: Atkins)
  --no-citations        Hide citation counts
  --no-oa-links         Hide Open Access links
  --max-authors N       Maximum authors before "et al."
```

### enrich_from_openalex.py

```
Usage: python enrich_from_openalex.py [OPTIONS]

Options:
  -i, --input FILE      Input CSL-JSON file (default: papers_zotero.json)
  -o, --output FILE     Output enriched JSON (default: papers_enriched.json)
  --cache FILE          Cache file path (default: openalex_cache.json)
  --refresh             Ignore cache and fetch fresh data
```

## Preprint Detection

Papers are automatically categorised as preprints if any of the following are true:
- CSL type is `manuscript`
- Container title contains: biorxiv, medrxiv, arxiv, ssrn, preprints, research square, wellcome open research
- DOI starts with `10.1101/` (bioRxiv/medRxiv prefix)

## Troubleshooting

### Paper not found in OpenAlex

Some papers may not be found via DOI lookup even if they exist in OpenAlex. In this case:

1. Search for the paper at https://openalex.org/works
2. Manually add `"citation-count": N` to the paper's entry in `papers_enriched.json`
3. Re-run `generate_papers_md.py -i papers_enriched.json`

### Wrong author highlighted

The script bolds any author whose family name contains "Atkins". This may incorrectly highlight names like "Atkinson". To fix, modify the `highlight_author` config in `generate_papers_md.py` to use exact matching if needed.

## Archived Workflow

The previous OpenAlex-based verification workflow is archived in the `archive/` folder with its own README explaining how it worked.

## Contact

Built for Katherine Atkins' academic publications page.
Email: katherine.atkins@ed.ac.uk
