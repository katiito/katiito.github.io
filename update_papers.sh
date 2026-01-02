#!/bin/bash
# Update papers.md from Zotero export with OpenAlex citation counts
#
# Usage: ./update_papers.sh
#
# This script:
# 1. Enriches papers_zotero.json with citation counts from OpenAlex
# 2. Generates papers.md from the enriched data

set -e

cd "$(dirname "$0")"

echo "=== Updating Papers Page ==="
echo

# Step 1: Enrich with OpenAlex citation counts
echo "Step 1: Enriching with OpenAlex citation counts..."
uv run --with requests python enrich_from_openalex.py
echo

# Step 2: Generate papers.md
echo "Step 2: Generating papers.md..."
uv run python generate_papers_md.py -i papers_enriched.json
echo

echo "=== Done! ==="
