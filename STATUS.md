# Status: KDP Book Builder

**Version:** 0.1.0  
**Date:** 2026-10-23  
**Copyright:** Copyright (c) 2026 Asdale Dynamics, LLC

## What was built

A local Python command-line tool that turns a folder of Markdown chapters into
KDP-ready files. One command produces:

| Output | Purpose |
| --- | --- |
| `<title>-interior.pdf` | Print interior: chosen trim size, mirrored margins, page numbers, generated TOC, chapter starts on fresh pages, embedded fonts, automatic blank-page padding |
| `<title>.epub` | EPUB 3 for Kindle: cover, title and copyright pages, navigation, chapters, images, and cross-chapter links |
| `<title>-ebook-cover.jpg` | 1,600 × 2,560 Kindle cover image, also embedded in the EPUB |
| `<title>-cover-wrap.pdf` | Full paperback wrap sized from the final padded page count and paper type, including 0.125 in bleed, spine, and barcode clear zone |
| `<title>-cover-template.pdf` | Measurement sheet with trim, safe-area, spine-fold, and barcode guides plus the spine math |

The project includes a sample book (`sample_book/`), a 109-test pytest suite,
packaging metadata, bundled open-license fonts, a plain-English README for
first-time self-publishers, and an MIT license.

### Source layout

```text
src/kdp_book_builder/
  book.py       book.yaml loading and validation
  markdown.py   Markdown to ReportLab markup and XHTML
  layout.py     trim sizes, paper thickness, gutter bands, spine and cover math
  pdf.py        print interior
  epub.py       Kindle EPUB
  cover.py      cover wrap, guide template, ebook cover
  cli.py        command-line interface
  fonts.py      bundled font registration
tests/          pytest suite with real PDF/EPUB builds and font checks
sample_book/    working sample: The Friendly AI Field Guide
```

## How to run it

Requirements: Python 3.10 or newer. No network access, API keys, or accounts
are used by the tool.

```bash
cd /workspace/qoder-lab/kdp-book-builder
python3 -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

kdp-book-builder build sample_book
```

Outputs are written to `dist/the-friendly-ai-field-guide/`.

Useful commands:

```bash
kdp-book-builder build my-book --format pdf
kdp-book-builder build my-book --format epub
kdp-book-builder build my-book --format cover
kdp-book-builder build my-book --trim 5.5x8.5 --paper white
kdp-book-builder trim-sizes
kdp-book-builder build --help
```

If the console command is not on `PATH`, use `python -m kdp_book_builder`.

A book folder contains `book.yaml`, an optional cover image, and a chapters
folder of Markdown files. Each chapter starts with exactly one `# Heading`.
See `README.md` for every setting and a worked example.

## Verification results

All checks below were run on the final source tree with the sample book.

| Check | Result |
| --- | --- |
| Test suite | **109 passed** in 1.69 s (`python -m pytest -q`) |
| Sample build | 24 pages: 15 content pages plus 9 blank pages added to meet KDP's 24-page minimum; warning reported clearly |
| Interior geometry | 6.0 × 9.0 in; cream paper; inside/outside 0.625 in, top/bottom 0.75 in |
| Interior structure | TOC with page numbers, 6 PDF outline entries, page numbers on the outside edge, mirrored layout |
| Cover math | 24 pages × 0.0025 in = 0.06 in spine; wrap 12.31 × 9.25 in |
| Cover rules | Barcode clear zone and template guides present; spine left clear because 24 pages is below KDP's 80-page spine-text threshold |
| Ebook cover | 1,600 × 2,560 JPEG |
| Font embedding | Regression tests confirm every font in the interior, wrap, and template is embedded |
| EPUB structure | 12 files, 7 spine items, 18 navigation links; uncompressed `mimetype` first; all XML well-formed; manifest, spine, nav, image, and link targets resolve |
| Official EPUB validation | EPUBCheck 5.3.0, EPUB 3.3 rules: **0 fatals / 0 errors / 0 warnings / 0 infos** |
| Clean wheel install | Wheel built, installed into a fresh virtual environment, `kdp-book-builder --version` returned `0.1.0`, and building the sample from outside the repository produced all five outputs |
| Secret scan | Grep for API keys, tokens, passwords, and private keys found only benign code identifiers and a test URL; no credentials in the repository |
| KDP spine-text rule | Confirmed against KDP help: spine text is only printed above 79 pages; implementation enforces a minimum of 80 pages |

### Verification environment

- Linux x64, Python 3.13.0 (project supports 3.10+)
- ReportLab, markdown-it-py, PyYAML, Pillow, pypdf
- EPUBCheck 5.3.0 with a temporary Java 17 runtime kept outside the repository

## Known gaps and limits

- **KDP specifications change.** The tool implements current trim, margin,
  bleed, spine, and spine-text rules, but KDP's previewer and current cover
  calculator remain the final authority. Order a physical proof before
  publishing.
- **No interior bleed option.** Interiors are no-bleed, which is the common
  choice for text books. Cover files include bleed.
- **No KDP upload or publishing.** The tool only writes local files. It never
  contacts KDP or any other service.
- **No automated back-cover layout beyond the generated design.** The clean
  wrap places the title, subtitle, description, colors, and optional image.
  Users replacing the art in a design program must rebuild or measure against
  the template themselves.
- **No PDF/X or printer preflight.** Fonts are embedded and images are handled,
  but the output is not certified PDF/X and has not been run through a
  commercial preflight tool.
- **Limited Markdown surface.** Footnotes and raw HTML are not passed through.
  Tables and images are supported; tables use a simple grid style. SVG is
  included in the EPUB but skipped in print with a warning.
- **Images are not automatically downsampled or converted.** Authors should
  supply 300 DPI PNG/JPEG assets at their printed size; warnings point out
  missing or unsupported images.
- **EPUB validation is optional.** EPUBCheck is not bundled and requires Java.
  It is exposed as the optional `validation` extra, not as a build dependency.
- **Only Linux was exercised in this run.** The CLI uses portable Python paths,
  but Windows and macOS were not tested here.
- **No ISBN assignment.** An ISBN can be printed if provided, but the tool does
  not issue or validate registrations.
- **The cover template is a measuring aid, not final artwork.** Upload the
  clean wrap, not the template.

## Privacy and licensing

Everything runs locally. The tool makes no network requests and stores no
personal data. Manuscripts never leave the user's folder.

- Code: MIT License, Copyright (c) 2026 Asdale Dynamics, LLC.
- Bundled Liberation fonts: SIL Open Font License, with the license included in
  `src/kdp_book_builder/assets/fonts/LICENSE.txt`.

Built by [Asdale Dynamics, LLC](https://dylanasdale.github.io), where AI is
explained like a friend would.
