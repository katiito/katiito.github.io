#!/usr/bin/env python3
"""
Verify and update academic publications list using OpenAlex API with PubMed fallback.

This script supports a two-phase supervised workflow with enhanced matching:
  Phase 1 (--phase1): Multi-stage matching:
    - Stage 1: OpenAlex DOI lookup (high confidence)
    - Stage 1a: OpenAlex title + first author search (high confidence)
    - Stage 1b: PubMed fallback search → get DOI → verify in OpenAlex
    - Generate manual_review.md for remaining unmatched papers
  Phase 2 (--phase2): Read manual selections and generate final outputs

Usage:
  python verify_publications.py --phase1    # First pass - generates manual_review.md
  python verify_publications.py --phase2    # After review - generates final outputs
  python verify_publications.py             # Run both phases (legacy mode)
"""

import json
import re
import sys
import time
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

# Configuration
MAILTO = "katherine.atkins@ed.ac.uk"
API_BASE = "https://api.openalex.org/works"
PUBMED_SEARCH_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
INPUT_FILE = "papers.md"
OUTPUT_JSON = "publications.json"
OUTPUT_REPORT = "discrepancy_report.md"
OUTPUT_UPDATED = "papers_updated.md"
MANUAL_REVIEW_FILE = "manual_review.md"
PHASE1_CACHE = "phase1_cache.json"
ERROR_LOG = "api_errors.log"
REQUEST_DELAY = 0.5  # seconds between API requests
PUBMED_DELAY = 0.4  # PubMed allows ~3 requests/sec without API key
MAX_RETRIES = 3
MAX_CANDIDATES = 5  # Number of candidate matches to show for manual review

# Set up logging
logging.basicConfig(
    filename=ERROR_LOG,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_doi_from_url(url: str) -> Optional[str]:
    """Extract DOI from various URL formats."""
    if not url:
        return None

    # Direct DOI patterns - must start with 10.
    patterns = [
        r'doi\.org/(10\.\d{4,}/[^\s\]\)]+)',
        r'doi:\s*(10\.\d{4,}/[^\s\]\)]+)',
        r'DOI:\s*(10\.\d{4,}/[^\s\]\)]+)',
        # medRxiv/bioRxiv
        r'medrxiv\.org/content/(10\.\d{4,}/[^\s\]\)v]+)',
        r'biorxiv\.org/content/(10\.\d{4,}/[^\s\]\)v]+)',
        # PNAS - direct DOI in URL
        r'pnas\.org/doi/(?:abs/|full/)?(10\.\d{4,}/[^\s\]\)]+)',
        # Science
        r'science\.org/doi/(10\.\d{4,}/[^\s\]\)]+)',
        # BMC
        r'biomedcentral\.com/articles/(10\.\d{4,}/[^\s\]\)]+)',
        # Wellcome Open Research
        r'wellcomeopenres\.org/(10\.\d{4,}/[^\s\]\)]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            doi = match.group(1)
            # Clean up trailing punctuation and asterisks
            doi = re.sub(r'[)\].,;*]+$', '', doi)
            # Validate it looks like a DOI
            if doi.startswith('10.') and '/' in doi:
                return doi

    # For Nature articles, construct DOI
    nature_match = re.search(r'nature\.com/articles/(s\d+-\d+-\d+-\w+)', url, re.IGNORECASE)
    if nature_match:
        return f"10.1038/{nature_match.group(1)}"

    return None


def parse_markdown_publications(filepath: str) -> list[dict]:
    """Parse the markdown file and extract publication entries."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    publications = []
    current_section = None

    # Split into lines for processing
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Check for section headers (### Year or ### Preprints)
        if line.startswith('### '):
            current_section = line[4:].strip()
            i += 1
            continue

        # Check for publication entry (starts with [number])
        entry_match = re.match(r'\[(\d+)\]\s*(.+)', line)
        if entry_match:
            entry_num = int(entry_match.group(1))
            entry_content = entry_match.group(2)

            # Collect multi-line entries
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith('[') and not lines[i].strip().startswith('###') and not lines[i].strip().startswith('—'):
                entry_content += ' ' + lines[i].strip()
                i += 1

            # Parse the entry
            pub = parse_entry(entry_num, entry_content, current_section)
            if pub:
                publications.append(pub)
            continue

        i += 1

    return publications


def parse_entry(entry_num: int, content: str, section: str) -> dict:
    """Parse a single publication entry."""
    pub = {
        'entry_num': entry_num,
        'section': section,
        'raw_content': content,
        'authors': None,
        'year': None,
        'title': None,
        'journal': None,
        'doi': None,
        'url': None,
        'volume': None,
        'issue': None,
        'pages': None,
    }

    # Extract year from section or content
    if section and section != 'Preprints':
        pub['year'] = int(section)
    else:
        year_match = re.search(r'\((\d{4})\)', content)
        if year_match:
            pub['year'] = int(year_match.group(1))

    # Extract URL/link
    url_match = re.search(r'\[(?:online here|medRxiv link|Open access link|link)\]\((https?://[^\)]+)\)', content, re.IGNORECASE)
    if url_match:
        pub['url'] = url_match.group(1)
        pub['doi'] = extract_doi_from_url(pub['url'])

    # Also check for DOI pattern directly in text
    if not pub['doi']:
        doi_match = re.search(r'(?:doi:|DOI:?)\s*(10\.\d{4,}/[^\s\]]+)', content, re.IGNORECASE)
        if doi_match:
            pub['doi'] = doi_match.group(1).rstrip('.,;)')

    # Extract title (usually in **bold**, but sometimes not)
    # Find ALL bold text sections and pick the one that's the title (not author name)
    bold_matches = re.findall(r'\*\*([^*]+)\*\*', content)
    for title_candidate in bold_matches:
        title_candidate = title_candidate.strip()
        # Skip author name patterns (Atkins KE, Atkins KE*, etc.)
        if re.match(r'^Atkins\s*KE\*?$', title_candidate, re.IGNORECASE):
            continue
        # Skip if it's too short to be a title
        if len(title_candidate) < 10:
            continue
        pub['title'] = title_candidate
        break

    # If no bold title found, try to extract title after year
    if not pub['title']:
        # Pattern: Authors (Year) Title *Journal* or Title Journal
        after_year_match = re.search(r'\(\d{4}\)\s*(.+?)(?:\*[^*]+\*|\s+\d+\s*\(|\s+doi:|\s+DOI:|\[online|\s*$)', content, re.IGNORECASE)
        if after_year_match:
            title = after_year_match.group(1).strip()
            # Clean up the title - remove trailing journal indicators
            title = re.sub(r'\s*(BMC|PLoS|PNAS|Science|Nature|Lancet|Vaccine|Value in Health|Epidemics).*$', '', title, flags=re.IGNORECASE)
            title = title.rstrip('.')
            if len(title) > 10:  # Ensure we got something meaningful
                pub['title'] = title

    # Extract journal (usually in *italics*)
    journal_match = re.search(r'\*([^*]+)\*(?!\*)', content)
    if journal_match:
        journal = journal_match.group(1).strip()
        # Clean up journal name
        if not journal.startswith('http'):
            pub['journal'] = journal

    # Extract authors (everything before the year in parentheses)
    authors_match = re.match(r'^(.+?)\s*\(\d{4}\)', content)
    if authors_match:
        pub['authors'] = authors_match.group(1).strip()

    # Extract volume/issue/pages if present
    vol_match = re.search(r'(\d+)\s*\((\d+)\)\s*:\s*(\d+[-–]\d+|\w+)', content)
    if vol_match:
        pub['volume'] = vol_match.group(1)
        pub['issue'] = vol_match.group(2)
        pub['pages'] = vol_match.group(3)

    return pub


def query_openalex_by_doi(doi: str) -> Optional[dict]:
    """Query OpenAlex API using DOI."""
    # Clean the DOI
    doi = doi.strip().rstrip('.')

    url = f"{API_BASE}/https://doi.org/{doi}?mailto={MAILTO}"

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.info(f"DOI not found: {doi}")
                return None
            elif response.status_code == 429:
                wait_time = (attempt + 1) * 2
                logger.warning(f"Rate limited, waiting {wait_time}s")
                time.sleep(wait_time)
            else:
                logger.error(f"API error for DOI {doi}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Request error for DOI {doi}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)

    return None


def query_openalex_by_title(title: str) -> Optional[dict]:
    """Query OpenAlex API using title search."""
    # Clean and encode title
    title_clean = re.sub(r'[^\w\s]', ' ', title)
    title_clean = ' '.join(title_clean.split())

    url = f"{API_BASE}?filter=title.search:{quote(title_clean)}&mailto={MAILTO}"

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                if results:
                    # Return first result (best match)
                    return results[0]
                return None
            elif response.status_code == 429:
                wait_time = (attempt + 1) * 2
                logger.warning(f"Rate limited, waiting {wait_time}s")
                time.sleep(wait_time)
            else:
                logger.error(f"API error for title search: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Request error for title search: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)

    return None


def query_openalex_candidates(title: str, year: int = None, max_results: int = MAX_CANDIDATES) -> list[dict]:
    """Query OpenAlex API and return multiple candidate matches."""
    if not title:
        return []

    title_clean = re.sub(r'[^\w\s]', ' ', title)
    title_clean = ' '.join(title_clean.split())

    url = f"{API_BASE}?filter=title.search:{quote(title_clean)}&per-page={max_results}&mailto={MAILTO}"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            # Extract metadata for each candidate
            candidates = []
            for work in results[:max_results]:
                candidates.append(extract_openalex_metadata(work))
            return candidates
        return []
    except Exception as e:
        logger.error(f"Error searching for candidates: {e}")
        return []


def search_published_version(title: str) -> Optional[dict]:
    """Search for a published version of a preprint by title."""
    if not title:
        return None
    title_clean = re.sub(r'[^\w\s]', ' ', title)
    title_clean = ' '.join(title_clean.split())

    url = f"{API_BASE}?filter=title.search:{quote(title_clean)},type:article&mailto={MAILTO}"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            for result in results:
                if result.get('type') == 'article':
                    return result
        return None
    except Exception as e:
        logger.error(f"Error searching for published version: {e}")
        return None


def extract_first_author_surname(authors_str: str) -> Optional[str]:
    """Extract the first author's surname from an author string."""
    if not authors_str:
        return None

    # Clean up the string
    authors_str = authors_str.strip()

    # Remove any leading asterisks or special chars
    authors_str = re.sub(r'^\*+', '', authors_str)

    # Get first author (before first comma or 'and')
    first_author = re.split(r',|\s+and\s+', authors_str)[0].strip()

    # Remove bold markers
    first_author = re.sub(r'\*\*([^*]+)\*\*', r'\1', first_author)

    # Extract surname - usually the first word before initials
    # Pattern: "Surname AB" or "Surname A" or just "Surname"
    match = re.match(r'^([A-Z][a-zA-Z\-\']+)', first_author)
    if match:
        return match.group(1)

    return None


def query_openalex_by_author_title(first_author: str, title: str, year: int = None) -> Optional[dict]:
    """Query OpenAlex using first author surname and title keywords."""
    if not first_author or not title:
        return None

    # Clean title - get first few significant words
    title_clean = re.sub(r'[^\w\s]', ' ', title)
    title_words = [w for w in title_clean.split() if len(w) > 3][:5]  # First 5 significant words
    title_query = ' '.join(title_words)

    # Build filter
    filters = [
        f"author.search:{quote(first_author)}",
        f"title.search:{quote(title_query)}"
    ]
    if year:
        filters.append(f"publication_year:{year}")

    url = f"{API_BASE}?filter={','.join(filters)}&mailto={MAILTO}"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            if results:
                return results[0]
        return None
    except Exception as e:
        logger.error(f"Error in author+title search: {e}")
        return None


def search_pubmed(title: str, first_author: str = None, year: int = None) -> Optional[str]:
    """Search PubMed and return PMID if found."""
    if not title:
        return None

    # Build search query
    # Clean title for search
    title_clean = re.sub(r'[^\w\s]', ' ', title)
    title_words = [w for w in title_clean.split() if len(w) > 3][:8]

    query_parts = [' '.join(title_words) + '[Title]']
    if first_author:
        query_parts.append(f"{first_author}[Author]")
    if year:
        query_parts.append(f"{year}[PDAT]")

    query = ' AND '.join(query_parts)

    params = {
        'db': 'pubmed',
        'term': query,
        'retmax': 5,
        'retmode': 'json'
    }

    try:
        response = requests.get(PUBMED_SEARCH_BASE, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            id_list = data.get('esearchresult', {}).get('idlist', [])
            if id_list:
                return id_list[0]  # Return first PMID
        return None
    except Exception as e:
        logger.error(f"Error searching PubMed: {e}")
        return None


def get_doi_from_pubmed(pmid: str) -> Optional[str]:
    """Fetch article details from PubMed and extract DOI."""
    if not pmid:
        return None

    params = {
        'db': 'pubmed',
        'id': pmid,
        'retmode': 'xml'
    }

    try:
        response = requests.get(PUBMED_FETCH_BASE, params=params, timeout=30)
        if response.status_code == 200:
            # Parse XML to find DOI
            # Look for <ArticleId IdType="doi">...</ArticleId>
            doi_match = re.search(r'<ArticleId IdType="doi">([^<]+)</ArticleId>', response.text)
            if doi_match:
                return doi_match.group(1)
        return None
    except Exception as e:
        logger.error(f"Error fetching from PubMed: {e}")
        return None


def extract_openalex_metadata(work: dict) -> dict:
    """Extract relevant metadata from OpenAlex work object."""
    metadata = {
        'openalex_id': work.get('id'),
        'title': work.get('title'),
        'publication_year': work.get('publication_year'),
        'type': work.get('type'),
        'doi': work.get('doi', '').replace('https://doi.org/', '') if work.get('doi') else None,
        'cited_by_count': work.get('cited_by_count', 0),
        'authors': [],
        'journal': None,
        'volume': None,
        'issue': None,
        'first_page': None,
        'last_page': None,
        'oa_url': None,
        'is_oa': work.get('open_access', {}).get('is_oa', False),
    }

    # Extract authors
    for authorship in work.get('authorships', []):
        author = authorship.get('author', {})
        name = author.get('display_name', '')
        if name:
            metadata['authors'].append(name)

    # Extract journal/source
    primary_location = work.get('primary_location', {})
    if primary_location:
        source = primary_location.get('source', {})
        if source:
            metadata['journal'] = source.get('display_name')

    # Extract biblio info
    biblio = work.get('biblio', {})
    if biblio:
        metadata['volume'] = biblio.get('volume')
        metadata['issue'] = biblio.get('issue')
        metadata['first_page'] = biblio.get('first_page')
        metadata['last_page'] = biblio.get('last_page')

    # Extract OA URL
    best_oa = work.get('best_oa_location', {})
    if best_oa:
        metadata['oa_url'] = best_oa.get('pdf_url') or best_oa.get('landing_page_url')

    return metadata


def normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    if not title:
        return ""
    # Remove punctuation, lowercase, and extra spaces
    normalized = re.sub(r'[^\w\s]', '', title.lower())
    return ' '.join(normalized.split())


def compare_titles(title1: str, title2: str) -> float:
    """Compare two titles and return similarity score (0-1)."""
    if not title1 or not title2:
        return 0.0

    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)

    if norm1 == norm2:
        return 1.0

    # Check for substring match
    if norm1 in norm2 or norm2 in norm1:
        return 0.9

    # Word overlap
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def format_authors_for_csl(authors: list[str]) -> list[dict]:
    """Format author names for CSL-JSON."""
    csl_authors = []
    for name in authors:
        # Try to split into family and given names
        parts = name.strip().split()
        if len(parts) >= 2:
            # Assume last word is family name
            family = parts[-1]
            given = ' '.join(parts[:-1])
            csl_authors.append({'family': family, 'given': given})
        else:
            csl_authors.append({'family': name, 'given': ''})
    return csl_authors


def create_csl_json(publications: list[dict]) -> list[dict]:
    """Create CSL-JSON format from publications data."""
    csl_items = []

    for pub in publications:
        openalex = pub.get('openalex', {})

        # Generate ID
        first_author = openalex.get('authors', ['unknown'])[0].split()[-1].lower() if openalex.get('authors') else 'unknown'
        year = openalex.get('publication_year') or pub.get('year') or 'unknown'
        title_word = (openalex.get('title') or pub.get('title') or 'untitled').split()[0].lower()[:10]
        item_id = f"{first_author}{year}{title_word}"

        # Determine type
        pub_type = openalex.get('type', 'article')
        csl_type = 'article-journal' if pub_type == 'article' else 'manuscript' if pub_type == 'preprint' else 'article-journal'

        item = {
            'id': item_id,
            'type': csl_type,
            'title': openalex.get('title') or pub.get('title'),
            'author': format_authors_for_csl(openalex.get('authors', [])),
            'issued': {'date-parts': [[openalex.get('publication_year') or pub.get('year')]]},
            'container-title': openalex.get('journal') or pub.get('journal'),
        }

        # Add optional fields
        if openalex.get('doi'):
            item['DOI'] = openalex['doi']
        if openalex.get('volume'):
            item['volume'] = openalex['volume']
        if openalex.get('issue'):
            item['issue'] = openalex['issue']
        if openalex.get('first_page'):
            if openalex.get('last_page'):
                item['page'] = f"{openalex['first_page']}-{openalex['last_page']}"
            else:
                item['page'] = openalex['first_page']
        if openalex.get('oa_url'):
            item['URL'] = openalex['oa_url']
        if openalex.get('cited_by_count'):
            item['citation-count'] = openalex['cited_by_count']

        # Keep original entry number for reference
        item['note'] = f"Original entry: [{pub['entry_num']}]"

        csl_items.append(item)

    return csl_items


def generate_discrepancy_report(publications: list[dict]) -> str:
    """Generate markdown discrepancy report."""
    report = ["# Publication Verification Report\n"]
    report.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Summary statistics
    total = len(publications)
    no_issues = 0
    minor_discrepancies = 0
    needs_review = 0
    not_found = 0
    preprints_published = 0

    detailed_sections = []

    for pub in publications:
        openalex = pub.get('openalex', {})
        match_confidence = pub.get('match_confidence', 'Not Found')

        if not openalex:
            not_found += 1
        elif match_confidence == 'High':
            no_issues += 1
        elif match_confidence == 'Medium':
            minor_discrepancies += 1
        else:
            needs_review += 1

        if pub.get('preprint_now_published'):
            preprints_published += 1

        # Detailed entry
        entry = [f"\n### Paper {pub['entry_num']}: {(pub.get('title') or 'Unknown')[:60]}...\n"]
        entry.append(f"**Match confidence:** {match_confidence}\n")

        if pub.get('preprint_now_published'):
            entry.append("**Note:** 🆕 Preprint now has a published version!\n")

        if openalex:
            entry.append("\n| Field | Original | OpenAlex | Match |")
            entry.append("|-------|----------|----------|-------|")

            # Title comparison
            orig_title = (pub.get('title') or 'N/A')[:50]
            oa_title = (openalex.get('title') or 'N/A')[:50]
            title_match = '✓' if compare_titles(pub.get('title') or '', openalex.get('title') or '') > 0.8 else '✗'
            entry.append(f"| Title | {orig_title}... | {oa_title}... | {title_match} |")

            # Year comparison
            orig_year = pub.get('year') or 'N/A'
            oa_year = openalex.get('publication_year') or 'N/A'
            year_match = '✓' if str(orig_year) == str(oa_year) else '✗'
            entry.append(f"| Year | {orig_year} | {oa_year} | {year_match} |")

            # Journal comparison
            orig_journal = (pub.get('journal') or 'N/A')[:30]
            oa_journal = (openalex.get('journal') or 'N/A')[:30]
            journal_match = '✓' if orig_journal.lower() in (openalex.get('journal') or '').lower() or (openalex.get('journal') or '').lower() in orig_journal.lower() else '~'
            entry.append(f"| Journal | {orig_journal} | {oa_journal} | {journal_match} |")

            # DOI comparison
            orig_doi = pub.get('doi') or 'N/A'
            oa_doi = openalex.get('doi') or 'N/A'
            doi_match = '✓' if orig_doi == oa_doi else ('~' if oa_doi != 'N/A' else '✗')
            entry.append(f"| DOI | {orig_doi} | {oa_doi} | {doi_match} |")

            # Additional data
            entry.append(f"\n**Additional data from OpenAlex:**")
            entry.append(f"- Citations: {openalex.get('cited_by_count', 0)}")
            entry.append(f"- Type: {openalex.get('type', 'unknown')}")
            if openalex.get('oa_url'):
                entry.append(f"- Open Access: [link]({openalex['oa_url']})")
            if openalex.get('volume'):
                entry.append(f"- Volume: {openalex['volume']}, Issue: {openalex.get('issue', 'N/A')}, Pages: {openalex.get('first_page', 'N/A')}-{openalex.get('last_page', 'N/A')}")
        else:
            entry.append("\n**Not found in OpenAlex database.**")
            entry.append(f"\nOriginal entry: {pub.get('raw_content', 'N/A')[:200]}...")

        detailed_sections.append('\n'.join(entry))

    # Add summary
    report.append("## Summary\n")
    report.append(f"- **Total papers:** {total}")
    report.append(f"- **No issues (high confidence match):** {no_issues}")
    report.append(f"- **Minor discrepancies:** {minor_discrepancies}")
    report.append(f"- **Needs manual review:** {needs_review}")
    report.append(f"- **Not found in OpenAlex:** {not_found}")
    report.append(f"- **Preprints now published:** {preprints_published}")
    report.append("\n---\n")
    report.append("## Detailed Comparison\n")
    report.extend(detailed_sections)

    return '\n'.join(report)


def format_authors_for_markdown(authors: list[str], highlight_name: str = "Atkins") -> str:
    """Format authors for markdown output, highlighting specified name."""
    formatted = []
    for author in authors:
        if highlight_name.lower() in author.lower():
            formatted.append(f"**{author}**")
        else:
            formatted.append(author)
    return ', '.join(formatted)


def generate_updated_markdown(publications: list[dict]) -> str:
    """Generate updated markdown publications file."""
    output = [
        "---",
        "layout: page",
        "title: Papers",
        "permalink: /papers/",
        "---",
        "",
        "***In addition to the listed papers, I am also part of the Centre for Mathematical Modelling of Infectious Diseases COVID-19 Working Group, whose publications are listed [here](https://cmmid.github.io/topics/covid19/).***",
        "",
    ]

    # Group by year
    by_year = {}
    preprints = []

    for pub in publications:
        openalex = pub.get('openalex', {})
        year = openalex.get('publication_year') or pub.get('year')
        pub_type = openalex.get('type', '')

        # Check if it's a preprint that hasn't been published
        if pub.get('section') == 'Preprints' and not pub.get('preprint_now_published'):
            preprints.append(pub)
        elif year:
            if year not in by_year:
                by_year[year] = []
            by_year[year].append(pub)

    # Add preprints section if any
    if preprints:
        output.append("### Preprints\n")
        for pub in sorted(preprints, key=lambda x: x['entry_num'], reverse=True):
            output.append(format_publication_entry(pub))
            output.append("")

    # Add publications by year (newest first)
    for year in sorted(by_year.keys(), reverse=True):
        output.append(f"### {year}\n")
        for pub in sorted(by_year[year], key=lambda x: x['entry_num'], reverse=True):
            output.append(format_publication_entry(pub))
            output.append("")

    return '\n'.join(output)


def format_publication_entry(pub: dict) -> str:
    """Format a single publication entry for markdown output."""
    openalex = pub.get('openalex', {})

    entry_num = pub['entry_num']

    # Use OpenAlex data if available, fallback to original
    authors = openalex.get('authors', [])
    if authors:
        authors_str = format_authors_for_markdown(authors)
    else:
        authors_str = pub.get('authors', 'Unknown authors')
        # Bold Atkins in original
        authors_str = re.sub(r'(\*?\*?Atkins\s*KE\*?\*?)', '**Atkins KE**', authors_str)

    title = openalex.get('title') or pub.get('title') or 'Unknown title'
    year = openalex.get('publication_year') or pub.get('year') or 'Unknown'
    journal = openalex.get('journal') or pub.get('journal') or ''

    # Build citation info
    citation_parts = []
    if journal:
        citation_parts.append(f"*{journal}*")
    if openalex.get('volume'):
        vol_str = openalex['volume']
        if openalex.get('issue'):
            vol_str += f"({openalex['issue']})"
        if openalex.get('first_page'):
            pages = openalex['first_page']
            if openalex.get('last_page'):
                pages += f"-{openalex['last_page']}"
            vol_str += f":{pages}"
        citation_parts.append(vol_str)

    citation = ' '.join(citation_parts) if citation_parts else ''

    # Build the entry
    lines = [f"[{entry_num}] {authors_str} ({year})"]
    lines.append(f"**{title}**")

    if citation:
        lines[1] += f" {citation}"

    # Add DOI link
    doi = openalex.get('doi') or pub.get('doi')
    if doi:
        lines.append(f"DOI: [{doi}](https://doi.org/{doi})")
    elif pub.get('url'):
        lines.append(f"[Link]({pub['url']})")

    # Add extra info on a new line
    extras = []
    if openalex.get('cited_by_count'):
        extras.append(f"Citations: {openalex['cited_by_count']}")
    if openalex.get('oa_url') and openalex.get('is_oa'):
        extras.append(f"[Open Access]({openalex['oa_url']})")

    if extras:
        lines.append(' | '.join(extras))

    return '\n'.join(lines)


def generate_manual_review(publications: list[dict]) -> str:
    """Generate markdown file for manual review of uncertain matches."""
    output = [
        "# Manual Review Required",
        "",
        "Please review the entries below and make your selections.",
        "",
        "## Instructions",
        "- Change `- [ ]` to `- [x]` to select an option",
        "- Select **only one** option per paper (or 'None of these')",
        "- If you select 'Enter DOI manually', fill in the DOI field below it",
        "- Save this file when done, then run: `python verify_publications.py --phase2`",
        "",
        "---",
        "",
    ]

    needs_review = [p for p in publications if p.get('needs_review')]

    if not needs_review:
        output.append("**No papers need manual review!** All papers were matched with high confidence.")
        return '\n'.join(output)

    output.append(f"**{len(needs_review)} papers need your review:**\n")

    for pub in needs_review:
        entry_num = pub['entry_num']
        title = pub.get('title') or 'Unknown title'
        year = pub.get('year') or 'Unknown'
        authors = pub.get('authors') or 'Unknown authors'
        candidates = pub.get('candidates', [])

        output.append(f"### Paper {entry_num}: {title[:60]}{'...' if len(title) > 60 else ''}")
        output.append("")
        output.append(f"**Original entry:**")
        output.append(f"> {authors} ({year})")
        output.append(f"> {title}")
        if pub.get('journal'):
            output.append(f"> *{pub['journal']}*")
        if pub.get('url'):
            output.append(f"> [Original link]({pub['url']})")
        output.append("")

        # Show candidates
        if candidates:
            output.append("**Select one option:**")
            output.append("")
            for i, cand in enumerate(candidates, 1):
                cand_title = cand.get('title') or 'Unknown'
                cand_year = cand.get('publication_year') or '?'
                cand_journal = cand.get('journal') or 'Unknown venue'
                cand_doi = cand.get('doi') or 'No DOI'
                cand_authors = ', '.join(cand.get('authors', [])[:3])
                if len(cand.get('authors', [])) > 3:
                    cand_authors += ' et al.'

                # Calculate similarity for display
                similarity = compare_titles(title, cand_title)

                output.append(f"- [ ] **Option {i}:** ({similarity:.0%} match)")
                output.append(f"      - Title: {cand_title}")
                output.append(f"      - Authors: {cand_authors}")
                output.append(f"      - Year: {cand_year} | Journal: {cand_journal}")
                output.append(f"      - DOI: `{cand_doi}`")
                output.append("")
        else:
            output.append("**No candidate matches found in OpenAlex.**")
            output.append("")

        # Always show manual DOI option and "None" option
        output.append("- [ ] **Enter DOI manually:**")
        output.append("      - DOI: `[ENTER DOI HERE]`")
        output.append("")
        output.append("- [ ] **None of these** (keep original entry unchanged)")
        output.append("")
        output.append("---")
        output.append("")

    return '\n'.join(output)


def parse_manual_review(filepath: str) -> dict:
    """Parse the manual review file and extract user selections."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    selections = {}
    current_entry = None

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]

        # Find paper header
        paper_match = re.match(r'### Paper (\d+):', line)
        if paper_match:
            current_entry = int(paper_match.group(1))
            i += 1
            continue

        if current_entry is not None:
            # Check for selected option
            if line.strip().startswith('- [x]') or line.strip().startswith('- [X]'):
                selection_text = line.strip()[5:].strip()

                if 'Option' in selection_text:
                    # Extract option number
                    opt_match = re.search(r'Option (\d+)', selection_text)
                    if opt_match:
                        selections[current_entry] = {
                            'type': 'option',
                            'option_num': int(opt_match.group(1))
                        }

                elif 'Enter DOI manually' in selection_text:
                    # Look for DOI in following lines
                    j = i + 1
                    while j < len(lines) and j < i + 5:
                        doi_match = re.search(r'DOI:\s*`([^`]+)`', lines[j])
                        if doi_match:
                            doi = doi_match.group(1).strip()
                            if doi and doi != '[ENTER DOI HERE]' and doi.startswith('10.'):
                                selections[current_entry] = {
                                    'type': 'manual_doi',
                                    'doi': doi
                                }
                            break
                        j += 1

                elif 'None of these' in selection_text:
                    selections[current_entry] = {
                        'type': 'none',
                    }

        i += 1

    return selections


def run_phase1():
    """Phase 1: Multi-stage matching with OpenAlex and PubMed fallback."""
    print("=" * 60)
    print("Publication Verification Tool - Phase 1 (Enhanced)")
    print("=" * 60)

    # Parse existing publications
    print(f"\n📖 Reading {INPUT_FILE}...")
    publications = parse_markdown_publications(INPUT_FILE)
    print(f"   Found {len(publications)} publications")

    # Statistics tracking
    stats = {
        'doi_match': 0,
        'author_title_match': 0,
        'pubmed_match': 0,
        'title_match': 0,
        'needs_review': 0
    }

    # Query OpenAlex for each publication with multi-stage matching
    print(f"\n🔍 Multi-stage matching...")
    print(f"   Stage 1: DOI lookup")
    print(f"   Stage 1a: Author + Title search")
    print(f"   Stage 1b: PubMed fallback → DOI → OpenAlex")
    print(f"   Stage 1c: Title-only search (candidates for review)")
    print()

    for i, pub in enumerate(publications):
        print(f"   [{i+1}/{len(publications)}] Entry {pub['entry_num']}: ", end='', flush=True)

        openalex_data = None
        match_confidence = 'Not Found'
        match_method = None
        pub['needs_review'] = False

        # Extract first author for later use
        first_author = extract_first_author_surname(pub.get('authors', ''))

        # ==========================================
        # STAGE 1: Try DOI first (highest confidence)
        # ==========================================
        if pub.get('doi'):
            openalex_data = query_openalex_by_doi(pub['doi'])
            if openalex_data:
                match_confidence = 'High'
                match_method = 'DOI'
                stats['doi_match'] += 1
                print(f"DOI match ✓")
            time.sleep(REQUEST_DELAY)

        # ==========================================
        # STAGE 1a: OpenAlex author + title search
        # ==========================================
        if not openalex_data and first_author and pub.get('title'):
            print(f"author+title... ", end='', flush=True)
            openalex_data = query_openalex_by_author_title(
                first_author,
                pub['title'],
                pub.get('year')
            )
            if openalex_data:
                # Verify it's a good match
                oa_title = openalex_data.get('title', '')
                similarity = compare_titles(pub['title'], oa_title)
                if similarity > 0.8:
                    match_confidence = 'High'
                    match_method = 'Author+Title'
                    stats['author_title_match'] += 1
                    print(f"match ({similarity:.0%}) ✓")
                else:
                    openalex_data = None  # Not a good enough match
            time.sleep(REQUEST_DELAY)

        # ==========================================
        # STAGE 1b: PubMed fallback search
        # ==========================================
        if not openalex_data and pub.get('title'):
            print(f"PubMed... ", end='', flush=True)
            pmid = search_pubmed(pub['title'], first_author, pub.get('year'))
            time.sleep(PUBMED_DELAY)

            if pmid:
                # Get DOI from PubMed
                pubmed_doi = get_doi_from_pubmed(pmid)
                time.sleep(PUBMED_DELAY)

                if pubmed_doi:
                    # Verify in OpenAlex
                    openalex_data = query_openalex_by_doi(pubmed_doi)
                    if openalex_data:
                        match_confidence = 'High'
                        match_method = 'PubMed→DOI'
                        stats['pubmed_match'] += 1
                        print(f"found DOI via PubMed ✓")
                        # Store the DOI we found
                        pub['doi'] = pubmed_doi
                    time.sleep(REQUEST_DELAY)

        # ==========================================
        # STAGE 1c: Title-only search (for candidates)
        # ==========================================
        if not openalex_data and pub.get('title'):
            print(f"title search... ", end='', flush=True)
            candidates = query_openalex_candidates(pub['title'], pub.get('year'))
            pub['candidates'] = candidates
            time.sleep(REQUEST_DELAY)

            if candidates:
                # Check if top candidate is a very good match
                top = candidates[0]
                similarity = compare_titles(pub['title'], top.get('title', ''))
                oa_year = top.get('publication_year')
                orig_year = pub.get('year')

                year_matches = True
                if orig_year and oa_year:
                    year_matches = abs(int(orig_year) - int(oa_year)) <= 1

                if similarity > 0.9 and year_matches:
                    # Auto-accept very high matches
                    match_confidence = 'High'
                    match_method = 'Title'
                    openalex_data = top
                    stats['title_match'] += 1
                    print(f"auto-accept ({similarity:.0%}) ✓")
                else:
                    # Needs manual review
                    pub['needs_review'] = True
                    stats['needs_review'] += 1
                    print(f"{len(candidates)} candidates, review needed ⚠️")
            else:
                pub['needs_review'] = True
                pub['candidates'] = []
                stats['needs_review'] += 1
                print("no matches found ⚠️")
        elif not openalex_data:
            pub['needs_review'] = True
            pub['candidates'] = []
            stats['needs_review'] += 1
            title_preview = (pub.get('title') or 'None')[:30]
            print(f"no title to search ⚠️")

        # Store match data
        if openalex_data and not pub.get('needs_review'):
            if isinstance(openalex_data, dict) and 'openalex_id' in openalex_data:
                # Already extracted metadata
                pub['openalex'] = openalex_data
            else:
                pub['openalex'] = extract_openalex_metadata(openalex_data)
            pub['match_confidence'] = match_confidence
            pub['match_method'] = match_method

            # Check for published version of preprints
            if pub.get('section') == 'Preprints' or pub['openalex'].get('type') == 'preprint':
                time.sleep(REQUEST_DELAY)
                published = search_published_version(pub.get('title', ''))
                if published and published.get('id') != openalex_data.get('id'):
                    print(f"      ↳ Found published version!")
                    pub['openalex'] = extract_openalex_metadata(published)
                    pub['preprint_now_published'] = True
        else:
            pub['match_confidence'] = 'Needs Review' if pub.get('needs_review') else 'Not Found'

    # Save cache for phase 2
    print(f"\n💾 Saving cache to {PHASE1_CACHE}...")
    cache_data = []
    for pub in publications:
        # Make a serializable copy
        pub_copy = {k: v for k, v in pub.items()}
        cache_data.append(pub_copy)

    with open(PHASE1_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)

    # Generate manual review file
    needs_review_count = sum(1 for p in publications if p.get('needs_review'))

    if needs_review_count > 0:
        print(f"\n📝 Generating {MANUAL_REVIEW_FILE}...")
        review_md = generate_manual_review(publications)
        with open(MANUAL_REVIEW_FILE, 'w', encoding='utf-8') as f:
            f.write(review_md)
        print(f"   {needs_review_count} papers need your review")

    # Print summary
    print("\n" + "=" * 60)
    print("Phase 1 Summary")
    print("=" * 60)

    print(f"\n  Matching breakdown:")
    print(f"    Stage 1  - DOI lookup:        {stats['doi_match']}")
    print(f"    Stage 1a - Author+Title:      {stats['author_title_match']}")
    print(f"    Stage 1b - PubMed→DOI:        {stats['pubmed_match']}")
    print(f"    Stage 1c - Title auto-accept: {stats['title_match']}")
    print(f"    ─────────────────────────────────")
    total_matched = stats['doi_match'] + stats['author_title_match'] + stats['pubmed_match'] + stats['title_match']
    print(f"    Total matched:                {total_matched}")
    print(f"    Needs manual review:          {stats['needs_review']}")

    if stats['needs_review'] > 0:
        print(f"\n📋 Next steps:")
        print(f"   1. Open {MANUAL_REVIEW_FILE} and make your selections")
        print(f"   2. Run: python verify_publications.py --phase2")
    else:
        print(f"\n✅ All papers matched! You can run --phase2 to generate outputs.")


def run_phase2():
    """Phase 2: Read manual selections and generate final outputs."""
    print("=" * 60)
    print("Publication Verification Tool - Phase 2")
    print("=" * 60)

    # Load cache from phase 1
    if not Path(PHASE1_CACHE).exists():
        print(f"\n❌ Error: {PHASE1_CACHE} not found. Run --phase1 first.")
        sys.exit(1)

    print(f"\n📂 Loading cache from {PHASE1_CACHE}...")
    with open(PHASE1_CACHE, 'r', encoding='utf-8') as f:
        publications = json.load(f)
    print(f"   Loaded {len(publications)} publications")

    # Parse manual review if it exists
    selections = {}
    if Path(MANUAL_REVIEW_FILE).exists():
        print(f"\n📖 Reading selections from {MANUAL_REVIEW_FILE}...")
        selections = parse_manual_review(MANUAL_REVIEW_FILE)
        print(f"   Found {len(selections)} selections")

    # Apply selections
    print(f"\n🔄 Applying selections...")
    for pub in publications:
        entry_num = pub['entry_num']

        if entry_num in selections:
            sel = selections[entry_num]

            if sel['type'] == 'option':
                # Use selected candidate
                opt_idx = sel['option_num'] - 1
                candidates = pub.get('candidates', [])
                if 0 <= opt_idx < len(candidates):
                    pub['openalex'] = candidates[opt_idx]
                    pub['match_confidence'] = 'Manual'
                    pub['needs_review'] = False
                    print(f"   Paper {entry_num}: Selected option {sel['option_num']}")

            elif sel['type'] == 'manual_doi':
                # Fetch by manual DOI
                print(f"   Paper {entry_num}: Looking up DOI {sel['doi']}... ", end='', flush=True)
                openalex_data = query_openalex_by_doi(sel['doi'])
                if openalex_data:
                    pub['openalex'] = extract_openalex_metadata(openalex_data)
                    pub['match_confidence'] = 'Manual'
                    pub['needs_review'] = False
                    print("Found ✓")
                else:
                    print("Not found in OpenAlex ✗")
                    pub['match_confidence'] = 'Not Found'
                time.sleep(REQUEST_DELAY)

            elif sel['type'] == 'none':
                # Keep original
                pub['openalex'] = {}
                pub['match_confidence'] = 'Original'
                pub['needs_review'] = False
                print(f"   Paper {entry_num}: Keeping original")

        elif pub.get('needs_review') and not pub.get('openalex'):
            # No selection made for this paper - keep original
            pub['openalex'] = {}
            pub['match_confidence'] = 'Original'

    # Generate outputs
    print(f"\n📄 Generating {OUTPUT_JSON}...")
    csl_data = create_csl_json(publications)
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(csl_data, f, indent=2, ensure_ascii=False)
    print(f"   Saved {len(csl_data)} entries")

    print(f"\n📊 Generating {OUTPUT_REPORT}...")
    report = generate_discrepancy_report(publications)
    with open(OUTPUT_REPORT, 'w', encoding='utf-8') as f:
        f.write(report)
    print("   Done")

    print(f"\n✏️  Generating {OUTPUT_UPDATED}...")
    updated_md = generate_updated_markdown(publications)
    with open(OUTPUT_UPDATED, 'w', encoding='utf-8') as f:
        f.write(updated_md)
    print("   Done")

    # Print summary
    print("\n" + "=" * 60)
    print("Final Summary")
    print("=" * 60)

    high = sum(1 for p in publications if p.get('match_confidence') == 'High')
    manual = sum(1 for p in publications if p.get('match_confidence') == 'Manual')
    original = sum(1 for p in publications if p.get('match_confidence') == 'Original')
    not_found = sum(1 for p in publications if p.get('match_confidence') == 'Not Found')

    print(f"  Auto-matched (high confidence): {high}")
    print(f"  Manually selected:              {manual}")
    print(f"  Kept original:                  {original}")
    print(f"  Not found:                      {not_found}")
    print(f"\nOutput files:")
    print(f"  - {OUTPUT_JSON}")
    print(f"  - {OUTPUT_REPORT}")
    print(f"  - {OUTPUT_UPDATED}")
    print("\n✅ Complete!")


def main():
    """Main entry point with argument handling."""
    if len(sys.argv) > 1:
        if sys.argv[1] == '--phase1':
            run_phase1()
        elif sys.argv[1] == '--phase2':
            run_phase2()
        elif sys.argv[1] == '--help':
            print(__doc__)
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use --phase1, --phase2, or --help")
            sys.exit(1)
    else:
        # Legacy mode: run both phases with prompt
        print("Running in interactive mode...")
        print("For supervised workflow, use: --phase1 then --phase2")
        print()
        run_phase1()


if __name__ == '__main__':
    main()
