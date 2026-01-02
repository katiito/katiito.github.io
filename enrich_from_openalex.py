#!/usr/bin/env python3
"""
Enrich Zotero CSL-JSON with citation counts from OpenAlex.

This script reads a CSL-JSON file (typically exported from Zotero via Better BibTeX)
and adds citation counts by querying the OpenAlex API. Results are cached to avoid
repeated API calls.

Usage:
  python enrich_from_openalex.py                              # papers_zotero.json → papers_enriched.json
  python enrich_from_openalex.py -i input.json -o output.json # Custom paths
  python enrich_from_openalex.py --refresh                    # Ignore cache, fetch fresh data
"""

import argparse
import json
import time
from pathlib import Path
from typing import Optional

import requests

# Configuration
MAILTO = "katherine.atkins@ed.ac.uk"
OPENALEX_API = "https://api.openalex.org/works"
REQUEST_DELAY = 0.5  # seconds between API requests

# Default file paths
DEFAULT_INPUT = "papers_zotero.json"
DEFAULT_OUTPUT = "papers_enriched.json"
CACHE_FILE = "openalex_cache.json"


def load_cache(cache_path: str) -> dict:
    """Load cached OpenAlex data."""
    if Path(cache_path).exists():
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cache(cache: dict, cache_path: str):
    """Save cache to disk."""
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)


def query_openalex(doi: str) -> Optional[dict]:
    """Query OpenAlex for a work by DOI."""
    # Clean DOI - remove https://doi.org/ prefix if present
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

    url = f"{OPENALEX_API}/doi:{doi}?mailto={MAILTO}"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            print(f"    Warning: OpenAlex returned {response.status_code} for {doi}")
            return None
    except Exception as e:
        print(f"    Error querying OpenAlex for {doi}: {e}")
        return None


def enrich_publications(input_path: str, output_path: str, cache_path: str, refresh: bool = False):
    """Enrich publications with OpenAlex citation counts."""

    # Load input
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        publications = json.load(f)
    print(f"  Found {len(publications)} publications")

    # Load cache
    cache = {} if refresh else load_cache(cache_path)
    if cache:
        print(f"  Loaded {len(cache)} cached entries")

    # Stats
    stats = {
        'cached': 0,
        'fetched': 0,
        'not_found': 0,
        'no_doi': 0
    }

    print(f"\nEnriching with OpenAlex data...")

    for i, pub in enumerate(publications):
        doi = pub.get('DOI')
        title_preview = (pub.get('title') or 'Unknown')[:50]

        print(f"  [{i+1}/{len(publications)}] {title_preview}...", end=' ', flush=True)

        if not doi:
            print("no DOI")
            stats['no_doi'] += 1
            continue

        # Check cache first
        if doi in cache:
            data = cache[doi]
            if data:
                pub['citation-count'] = data.get('cited_by_count', 0)
                # Also add OA URL if available and not already present
                if not pub.get('URL') and data.get('open_access', {}).get('oa_url'):
                    pub['URL'] = data['open_access']['oa_url']
            print(f"cached ({pub.get('citation-count', 0)} citations)")
            stats['cached'] += 1
            continue

        # Query OpenAlex
        time.sleep(REQUEST_DELAY)
        result = query_openalex(doi)

        if result:
            # Cache the useful data
            cache[doi] = {
                'cited_by_count': result.get('cited_by_count', 0),
                'open_access': result.get('open_access', {}),
                'openalex_id': result.get('id')
            }

            pub['citation-count'] = result.get('cited_by_count', 0)

            # Add OA URL if not present
            if not pub.get('URL'):
                oa_url = result.get('open_access', {}).get('oa_url')
                if oa_url:
                    pub['URL'] = oa_url

            print(f"found ({pub['citation-count']} citations)")
            stats['fetched'] += 1
        else:
            cache[doi] = None  # Cache the miss
            print("not found in OpenAlex")
            stats['not_found'] += 1

    # Save cache
    save_cache(cache, cache_path)
    print(f"\nSaved cache to {cache_path}")

    # Save enriched output
    print(f"Writing {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(publications, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\nSummary:")
    print(f"  Cached hits:    {stats['cached']}")
    print(f"  Fresh fetches:  {stats['fetched']}")
    print(f"  Not in OpenAlex:{stats['not_found']}")
    print(f"  No DOI:         {stats['no_doi']}")
    print(f"\nDone! Enriched data saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Enrich Zotero CSL-JSON with OpenAlex citation counts.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python enrich_from_openalex.py
  python enrich_from_openalex.py -i my_pubs.json -o enriched.json
  python enrich_from_openalex.py --refresh  # Ignore cache
        """
    )

    parser.add_argument(
        '-i', '--input',
        default=DEFAULT_INPUT,
        help=f'Input CSL-JSON file (default: {DEFAULT_INPUT})'
    )
    parser.add_argument(
        '-o', '--output',
        default=DEFAULT_OUTPUT,
        help=f'Output enriched JSON file (default: {DEFAULT_OUTPUT})'
    )
    parser.add_argument(
        '--cache',
        default=CACHE_FILE,
        help=f'Cache file path (default: {CACHE_FILE})'
    )
    parser.add_argument(
        '--refresh',
        action='store_true',
        help='Ignore cache and fetch fresh data from OpenAlex'
    )

    args = parser.parse_args()

    # Check input exists
    if not Path(args.input).exists():
        print(f"Error: Input file not found: {args.input}")
        return 1

    enrich_publications(args.input, args.output, args.cache, args.refresh)
    return 0


if __name__ == '__main__':
    exit(main())
