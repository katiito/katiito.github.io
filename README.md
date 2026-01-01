# Katherine E. Atkins - Personal Website

This is a Jekyll-based academic website deployed via GitHub Pages.

**Live site:** https://katiito.com

## Quick Start: Publishing Changes

To publish updates to your website:

```bash
git add .
git commit -m "Description of your changes"
git push
```

GitHub Pages will automatically build and deploy your site. Changes typically appear within 1-2 minutes.

## Site Structure

```
.
├── index.md          # Homepage content (bio text)
├── cv.md             # CV/Resume page
├── papers.md         # Publications list
├── teaching.md       # Teaching & Supervision page
├── people.md         # Lab group members
├── blog.md           # Blog page
├── _data/
│   └── news.yml      # News items displayed on homepage
├── _layouts/
│   ├── homepage.html # Custom homepage layout
│   └── page.html     # Standard page layout
├── _includes/
│   └── footer.html   # Custom footer
├── assets/
│   └── main.scss     # Custom styles
├── _config.yml       # Jekyll configuration
├── CNAME             # Custom domain (katiito.com)
└── profile_pic.jpg   # Profile photo
```

## Editing Content

### Updating pages
Edit the `.md` files directly. They use Markdown format with YAML front matter at the top.

### Adding news items
Edit `_data/news.yml`. Add new entries at the top of the file:

```yaml
- date: 2024-01-15
  descrip: Your news item text here
```

### Updating profile photo
Replace `profile_pic.jpg` with a new image (keep the same filename and dimensions ~300x270px).

## Configuration

Site settings are in `_config.yml`:
- `title`: Site title
- `email`: Contact email
- `twitter_username`: Twitter handle
- `github_username`: GitHub handle

## Technical Details

- **Theme:** Minima (GitHub Pages default)
- **Jekyll version:** Managed by GitHub Pages
- **Branch:** `master` (deployed automatically)
- **Custom domain:** katiito.com (configured via CNAME file)

## Troubleshooting

### Build failures
Check the GitHub Actions tab in your repository for build logs if the site doesn't update.

### Changes not appearing
1. Wait 1-2 minutes for GitHub Pages to rebuild
2. Hard refresh your browser (Cmd+Shift+R on Mac)
3. Check the repository's Actions tab for build status

### Local development (optional)
If you want to preview changes locally before pushing:

```bash
bundle install
bundle exec jekyll serve
```

Then visit http://localhost:4000
