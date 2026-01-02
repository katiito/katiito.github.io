# Archived Publications Workflow

This folder contains the original OpenAlex-based publication verification system, archived on 2026-01-02 when we migrated to a Zotero-based workflow.

## Why We Moved Away

The original system used a hand-maintained markdown file as the source of truth, with OpenAlex as a validator. This caused problems:

- Papers not in OpenAlex required manual intervention
- The markdown file was both source and output, making it fragile
- No easy way to add new papers without running the full verification pipeline

## New System

The new workflow uses **Zotero as the single source of truth**:

1. Manage publications in Zotero (with Better BibTeX)
2. Auto-export to `papers_zotero.json`
3. Optionally enrich with OpenAlex citation counts via `enrich_from_openalex.py`
4. Generate `papers.md` via `generate_papers_md.py`

## Files in This Archive

| File | Description |
|------|-------------|
| `verify_publications.py` | Multi-stage matching script (OpenAlex + PubMed fallback) |
| `publications.json` | CSL-JSON output with OpenAlex metadata |
| `phase1_cache.json` | Cached results from phase 1 matching |
| `manual_review.md` | Manual review file for unmatched papers |
| `papers_updated.md` | Generated markdown output |

## How to Use (If Needed)

If you need to run the old verification system:

```bash
# Phase 1: Match papers against OpenAlex/PubMed
python verify_publications.py --phase1

# Review manual_review.md and select matches

# Phase 2: Generate outputs
python verify_publications.py --phase2
```

Note: The script expects `papers.md` as input, which may no longer exist in the expected format.

## Contact

This system was built for Katherine Atkins' academic publications page.
