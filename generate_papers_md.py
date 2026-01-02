#!/usr/bin/env python3
"""
Generate papers.md from CSL-JSON publications data.

This standalone script reads a CSL-JSON file (e.g., publications.json)
and generates a formatted markdown file for a publications page.

Usage:
  python generate_papers_md.py                    # Uses publications.json → papers.md
  python generate_papers_md.py -i custom.json     # Custom input
  python generate_papers_md.py -o output.md       # Custom output
  python generate_papers_md.py --help             # Show help
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# Default configuration
DEFAULT_CONFIG = {
    'highlight_author': 'Atkins',      # Author surname to bold
    'show_citations': True,            # Show citation counts
    'show_oa_links': True,             # Show Open Access links
    'max_authors': None,               # None = show all, or int for "et al."
    'preprint_types': ['manuscript'],  # CSL types to treat as preprints
    'header_note': '***In addition to the listed papers, I am also part of the Centre for Mathematical Modelling of Infectious Diseases COVID-19 Working Group, whose publications are listed [here](https://cmmid.github.io/topics/covid19/).***',
}

# Default file paths
DEFAULT_INPUT = 'papers_zotero.json'
DEFAULT_OUTPUT = 'papers.md'

# Preprint server patterns (for container-title matching)
PREPRINT_SERVERS = [
    'biorxiv',
    'medrxiv',
    'arxiv',
    'ssrn',
    'preprints',
    'research square',
    'wellcome open research',  # Often has preprint-style articles
]


def load_csl_json(filepath: str) -> list[dict]:
    """Load and parse a CSL-JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("CSL-JSON file should contain an array of publications")

    return data


def extract_entry_number(pub: dict) -> Optional[int]:
    """Extract entry number from the note field."""
    note = pub.get('note', '')
    match = re.search(r'Original entry:\s*\[(\d+)\]', note)
    if match:
        return int(match.group(1))
    return None


def is_preprint(pub: dict, config: dict) -> bool:
    """
    Determine if a publication is a preprint.

    Checks:
    1. CSL type field (manuscript, etc.)
    2. Container title for preprint server names
    3. DOI prefix patterns (10.1101 for biorxiv/medrxiv)
    """
    # Check type field
    pub_type = pub.get('type', '')
    preprint_types = config.get('preprint_types', ['manuscript'])
    if pub_type in preprint_types:
        return True

    # Check container title for preprint servers
    container = (pub.get('container-title') or '').lower()
    for server in PREPRINT_SERVERS:
        if server in container:
            return True

    # Check DOI prefix (10.1101 is bioRxiv/medRxiv)
    doi = pub.get('DOI', '')
    if doi.startswith('10.1101/'):
        return True

    return False


def get_year(pub: dict) -> Optional[int]:
    """Extract publication year from CSL-JSON issued field."""
    issued = pub.get('issued', {})
    date_parts = issued.get('date-parts', [[]])
    if date_parts and date_parts[0]:
        return date_parts[0][0]
    return None


def format_author_name(author: dict) -> str:
    """Format a single author from CSL-JSON format."""
    # Handle literal names (e.g., consortiums, working groups)
    if 'literal' in author:
        return author['literal']

    given = author.get('given', '')
    family = author.get('family', '')

    if given and family:
        return f"{given} {family}"
    elif family:
        return family
    elif given:
        return given
    return "Unknown"


def format_authors(authors: list[dict], highlight: str = 'Atkins', max_authors: int = None) -> str:
    """
    Format author list with optional highlighting and truncation.

    Args:
        authors: List of CSL-JSON author objects
        highlight: Surname to bold
        max_authors: Maximum authors before "et al." (None = show all)
    """
    if not authors:
        return "Unknown authors"

    formatted = []
    for author in authors:
        name = format_author_name(author)
        family = author.get('family', '')

        # Bold if matches highlight
        if highlight and highlight.lower() in family.lower():
            name = f"**{name}**"

        formatted.append(name)

    # Truncate if needed
    if max_authors and len(formatted) > max_authors:
        formatted = formatted[:max_authors] + ['et al.']

    return ', '.join(formatted)


def format_citation_details(pub: dict) -> str:
    """Format journal, volume, issue, pages."""
    parts = []

    journal = pub.get('container-title')
    if journal:
        parts.append(f"*{journal}*")

    volume = pub.get('volume')
    issue = pub.get('issue')
    page = pub.get('page')

    vol_str = ''
    if volume:
        vol_str = volume
        if issue:
            vol_str += f"({issue})"
        if page:
            vol_str += f":{page}"
        parts.append(vol_str)
    elif page:
        parts.append(page)

    return ' '.join(parts)


def format_entry(pub: dict, entry_num: int, config: dict) -> str:
    """Format a single publication entry as markdown."""
    lines = []

    # Authors and year
    authors_str = format_authors(
        pub.get('author', []),
        highlight=config.get('highlight_author'),
        max_authors=config.get('max_authors')
    )
    year = get_year(pub) or 'Unknown'

    lines.append(f"[{entry_num}] {authors_str} ({year})")

    # Title and citation details
    title = pub.get('title', 'Unknown title')
    # Clean up any HTML tags in title
    title = re.sub(r'<[^>]+>', '', title)

    citation = format_citation_details(pub)
    if citation:
        lines.append(f"**{title}** {citation}")
    else:
        lines.append(f"**{title}**")

    # DOI link
    doi = pub.get('DOI')
    if doi:
        lines.append(f"DOI: [{doi}](https://doi.org/{doi})")

    # Extra info (citations, OA link)
    extras = []

    if config.get('show_citations'):
        citations = pub.get('citation-count')
        if citations:
            extras.append(f"Citations: {citations}")

    if config.get('show_oa_links'):
        url = pub.get('URL')
        if url and 'doi.org' not in url:  # Don't duplicate DOI link
            extras.append(f"[Open Access]({url})")

    if extras:
        lines.append(' | '.join(extras))

    return '\n'.join(lines)


def group_publications(publications: list[dict], config: dict) -> tuple[list, dict]:
    """
    Group publications into preprints and by-year articles.

    Returns:
        (preprints_list, {year: [pubs]})
    """
    preprints = []
    by_year = {}

    # First pass: extract entry numbers and find max for auto-numbering
    max_entry = 0
    for pub in publications:
        entry_num = extract_entry_number(pub)
        pub['_entry_num'] = entry_num
        if entry_num and entry_num > max_entry:
            max_entry = entry_num

    # Second pass: assign entry numbers to papers without them and group
    next_entry = max_entry + 1
    for pub in publications:
        if pub['_entry_num'] is None:
            pub['_entry_num'] = next_entry
            next_entry += 1

        year = get_year(pub)

        if is_preprint(pub, config):
            preprints.append(pub)
        elif year:
            if year not in by_year:
                by_year[year] = []
            by_year[year].append(pub)

    return preprints, by_year


def generate_markdown(publications: list[dict], config: dict) -> str:
    """Generate the full markdown document."""
    output = [
        "---",
        "layout: page",
        "title: Papers",
        "permalink: /papers/",
        "---",
        "",
    ]

    # Header note
    header_note = config.get('header_note')
    if header_note:
        output.append(header_note)
        output.append("")

    # Group publications
    preprints, by_year = group_publications(publications, config)

    # Preprints section
    if preprints:
        output.append("### Preprints")
        output.append("")

        # Sort by entry number (descending)
        preprints.sort(key=lambda x: x.get('_entry_num', 0), reverse=True)

        for pub in preprints:
            entry_num = pub.get('_entry_num', 0)
            output.append(format_entry(pub, entry_num, config))
            output.append("")

    # Year sections (newest first)
    for year in sorted(by_year.keys(), reverse=True):
        output.append(f"### {year}")
        output.append("")

        # Sort by entry number within year (descending)
        pubs = by_year[year]
        pubs.sort(key=lambda x: x.get('_entry_num', 0), reverse=True)

        for pub in pubs:
            entry_num = pub.get('_entry_num', 0)
            output.append(format_entry(pub, entry_num, config))
            output.append("")

    return '\n'.join(output)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Generate papers.md from CSL-JSON publications data.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_papers_md.py
  python generate_papers_md.py -i my_pubs.json -o my_papers.md
  python generate_papers_md.py --no-citations
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
        help=f'Output markdown file (default: {DEFAULT_OUTPUT})'
    )
    parser.add_argument(
        '--highlight',
        default=DEFAULT_CONFIG['highlight_author'],
        help=f"Author surname to bold (default: {DEFAULT_CONFIG['highlight_author']})"
    )
    parser.add_argument(
        '--no-citations',
        action='store_true',
        help='Hide citation counts'
    )
    parser.add_argument(
        '--no-oa-links',
        action='store_true',
        help='Hide Open Access links'
    )
    parser.add_argument(
        '--max-authors',
        type=int,
        default=None,
        help='Maximum authors before "et al." (default: show all)'
    )

    args = parser.parse_args()

    # Check input file exists
    if not Path(args.input).exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Build config
    config = DEFAULT_CONFIG.copy()
    config['highlight_author'] = args.highlight
    config['show_citations'] = not args.no_citations
    config['show_oa_links'] = not args.no_oa_links
    config['max_authors'] = args.max_authors

    # Load and process
    print(f"Reading {args.input}...")
    publications = load_csl_json(args.input)
    print(f"  Found {len(publications)} publications")

    print(f"Generating markdown...")
    markdown = generate_markdown(publications, config)

    print(f"Writing {args.output}...")
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(markdown)

    print(f"Done! Generated {args.output}")


if __name__ == '__main__':
    main()
