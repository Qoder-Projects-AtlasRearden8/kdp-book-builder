# KDP Book Builder

Turn a folder of Markdown chapters into a paperback interior, a Kindle EPUB, and a correctly sized cover wrap — without learning InDesign first.

You write in plain text. The tool handles the parts that are easy to get subtly wrong: trim size, mirrored margins, a print-ready table of contents, page numbering, Kindle navigation, spine width, and bleed.

It runs entirely on your computer. It does not upload your book, contact KDP, or need an API key.

> **A note before we start:** this tool gives you strong, KDP-aware files, but KDP's current specifications are the final word. Use KDP's previewer and order a physical proof before you publish. Publishing requirements occasionally change.

## What you get

One command builds these files:

| File | What it is | Where it usually goes |
| --- | --- | --- |
| `<title>-interior.pdf` | Print interior with TOC, page numbers, and mirrored margins | KDP paperback interior |
| `<title>.epub` | Kindle ebook with cover, clickable contents, and chapter navigation | KDP ebook manuscript |
| `<title>-ebook-cover.jpg` | 1,600 × 2,560 JPEG cover, also embedded in the EPUB | KDP ebook cover, if it asks separately |
| `<title>-cover-wrap.pdf` | Full paperback cover at the exact width and height, including bleed and spine | KDP paperback cover |
| `<title>-cover-template.pdf` | The same cover shape with trim, safe-area, spine, and barcode guides | Your own layout reference |

The clean cover wrap uses your title, subtitle, description, colors, and optional image. The template is a measuring sheet with guides and the spine math printed on it. **Do not upload the template as your finished cover** — it is there to help you build or check your artwork.

## Start here: build the sample book

You need Python 3.10 or newer and a terminal.

### 1. Make a virtual environment

On macOS or Linux:

```bash
cd kdp-book-builder
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
cd kdp-book-builder
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

A virtual environment is just a folder for this project's Python packages. It keeps your computer tidy.

### 2. Install the tool

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `-e` means "editable": the command picks up changes you make to this folder. The `[dev]` part also installs the test tools.

### 3. Build the sample

```bash
kdp-book-builder build sample_book
```

You should see a summary and a new folder at `dist/the-friendly-ai-field-guide/` containing the five files above. Open the PDFs in any PDF reader. Open the EPUB in a Kindle previewer or an ebook app.

If the command is not found, run it this way:

```bash
python -m kdp_book_builder build sample_book
```

To choose a folder for the output yourself:

```bash
kdp-book-builder build sample_book --output ~/Desktop/my-book-build
```

## Make your own book

A book is just a folder with a `book.yaml` file and some Markdown files:

```text
my-book/
├── book.yaml
├── cover-art.jpg          # optional
└── chapters/
    ├── 01-start-here.md
    ├── 02-the-basics.md
    └── 03-next-steps.md
```

Then run:

```bash
kdp-book-builder build my-book
```

### Each chapter is one Markdown file

Start each chapter with exactly one level-one heading:

```markdown
# A Chapter Title

Your opening paragraph goes here.

## A section

Sections can have **bold**, *italic*, lists, tables, quotes, and code.

### A smaller section

Keep level-three headings for ideas inside a level-two section.
```

Chapters are sorted by filename in a natural order, so `02-middle.md` comes before `10-later.md`. If you want an exact order, list the files in `book.yaml`.

The chapter title becomes a heading. You do not need to number chapters yourself; the tool adds "Chapter 1", "Chapter 2", and so on.

### `book.yaml`, line by line

Only `title` and `author` are required. Everything else has a sensible default.

```yaml
title: My First Useful Book
subtitle: A calm guide to getting started   # optional
author: Your Name
publisher: Your Press Name                  # optional
language: en-US                             # default: en
edition: First edition                      # optional
copyright_year: 2026
copyright_holder: Your Name or Your LLC

isbn: ""            # optional for the interior; leave blank if KDP assigns one
trim: 6x9           # paper trim size; see trim-sizes
paper: cream        # white, cream, groundwood, standard-color, premium-color

description: >-
  The back-cover description. It also becomes the ebook description.
disclaimer: >-
  Optional legal or safety note printed on the copyright page.
keywords:
  - beginner guide
  - practical skills

chapters: chapters  # a folder, or a list such as [chapters/01.md, chapters/02.md]

margins:            # optional; all values are inches
  inside: 0.625
  outside: 0.625
  top: 0.75
  bottom: 0.75

cover:              # optional; the generated cover uses these values
  background: "#17324D"
  accent: "#E3B563"
  text: "#FFF9EF"
  tagline: A small book with useful steps.
  image: cover-art.jpg   # optional, inside the book folder, JPG or PNG
```

The sample's [`book.yaml`](sample_book/book.yaml) is a complete working example.

#### A few settings that matter

- **Trim size.** This is the finished width × height of the paper. `6x9` is comfortable for nonfiction and manuals. Run `kdp-book-builder trim-sizes` to see every option.
- **Paper type.** Cream is common for nonfiction; white looks brighter; color papers have different page limits. See `kdp-book-builder trim-sizes`.
- **Inside margin.** Also called the gutter. The tool picks a safe value based on the final page count and adds extra breathing room. You can override it, but KDP has minimums.
- **Outside, top, and bottom margins.** The defaults are 0.625 in outside and 0.75 in top/bottom. No-bleed interiors need at least 0.25 in on the outside edge.
- **ISBN.** Leaving it blank is fine for the interior if KDP gives you a free ISBN. Do not invent one. For the ebook, KDP may assign a different ISBN than your print edition.

## Common commands

Build everything (the default):

```bash
kdp-book-builder build my-book
```

Build only the print interior:

```bash
kdp-book-builder build my-book --format pdf
```

Build only the EPUB and its cover image:

```bash
kdp-book-builder build my-book --format epub
```

Build only the cover wrap and template:

```bash
kdp-book-builder build my-book --format cover
```

Try a different trim or paper without editing `book.yaml`:

```bash
kdp-book-builder build my-book --trim 5.5x8.5 --paper white
```

Override a margin temporarily:

```bash
kdp-book-builder build my-book --inside-margin 0.75 --outside-margin 0.5
```

List trim sizes, paper types, and the spine formula:

```bash
kdp-book-builder trim-sizes
```

Show all options:

```bash
kdp-book-builder build --help
```

## What the interior does

- Uses the trim size you choose and creates a **mirrored layout**: the inside margin sits next to the binding on both left- and right-hand pages.
- Puts page numbers on the outside edge, starting with the table of contents.
- Builds a real table of contents with dot leaders and page numbers after the PDF layout settles. Chapters and level-two headings are included.
- Adds a title page and a copyright page.
- Keeps chapters on fresh pages.
- Embeds fonts, so the printer does not have to substitute them.
- Automatically adds blank pages at the end when KDP requires a higher minimum or an even final page count. The warning tells you when it does this.
- Repairs the common "my table of contents page numbers changed after reflow" problem by making repeated layout passes until the numbers are stable.

The text block uses 11.3 pt serif type with 16.7 pt leading. It is comfortable for long-form reading without making a 6 × 9 book unnecessarily thick.

### Page-count gotcha

KDP's minimum paperback length is 24 pages. If your manuscript lays out to 10 pages, the tool pads it to 24. That padding is intentional, and it affects the spine width. The cover is calculated from the **final padded page count**, which is why you should let one run build both the interior and the cover.

### Formatting support

The builder supports:

- Paragraphs, bold, italic, strikethrough, and inline code
- Level-two and level-three headings (these become sections and outline entries)
- Bulleted and numbered lists, including nesting
- Blockquotes
- Tables
- Fenced code blocks
- Images on their own line, with the alt text used as a caption in print
- Web links (`http`, `https`, and `mailto`)

It does **not** pass raw HTML through. Raw HTML is converted to plain text or ignored, with a warning, because loose HTML is a common cause of broken ebook files. Use Markdown instead.

For print, use PNG or JPEG images. Aim for 300 DPI at the size they will print. SVG images are left out of the paper PDF with a warning; the EPUB can include them, but PNG or JPEG is safer for Kindle.

To include chapter links in an ebook, link to another chapter's Markdown file, for example `[next chapter](02-the-basics.md)`. The EPUB builder points that link at the right ebook chapter.

## The cover math, without the headache

KDP builds a cover from back to front:

```text
total cover width  = 0.125 in bleed
                   + back cover trim width
                   + spine width
                   + front cover trim width
                   + 0.125 in bleed
```

The height is the trim height plus 0.125 in of bleed at the top and bottom.

The spine is the interesting part:

```text
spine width = final page count × paper thickness
```

The tool uses these paper thicknesses:

| Paper | Thickness per page |
| --- | --- |
| Black & white on white | 0.002252 in |
| Black & white on cream | 0.0025 in |
| Black & white on groundwood | 0.00235 in |
| Standard color | 0.002252 in |
| Premium color | 0.002347 in |

### Worked example

A 24-page book printed on cream paper:

```text
spine = 24 × 0.0025 in = 0.06 in
width = 0.125 + 6 + 0.06 + 6 + 0.125 = 12.31 in
height = 9 + 0.125 + 0.125 = 9.25 in
```

So the cover wrap is 12.31 × 9.25 in. The generated file is exactly that size. It includes 0.125 in bleed on all four sides, leaves a 2 × 1.2 in barcode area clear on the back cover, and does not add KDP's barcode for you.

**Spine text:** KDP does not allow spine text on books under 80 pages. The clean cover leaves the spine blank in that case. At 80 pages and above, room permitting, it adds the title and author (or whichever fits) and keeps away from the folds.

**Always confirm the spine width in KDP's cover calculator** using your final page count and current paper choice. The calculator is updated by KDP; this tool cannot guarantee tomorrow's specs.

### Using the template

Open `<title>-cover-template.pdf` when you want to place your own art. It includes:

- Magenta dashed trim line
- Cyan safe-area guides (0.25 in inside the trim)
- Amber spine folds
- A green dashed barcode clear zone
- The trim, page count, paper, spine width, and full-wrap dimensions
- A note explaining the 80-page spine-text rule

Keep important text inside the cyan guides, leave the barcode zone empty, and remove guide marks from your final artwork. The clean `<title>-cover-wrap.pdf` is a starting design without guide marks; use it as-is or replace the artwork in your design program.

## Publishing checklist

1. Run the build and read every warning. Warnings are there for a reason.
2. Open the interior PDF. Check the title page, copyright page, contents, a few chapter openings, page numbers, tables, and the final page.
3. Open the EPUB in a Kindle previewer, not just a browser. Check the cover, contents links, chapter order, images, and tables.
4. Compare `cover-template.pdf` dimensions with the current KDP cover calculator.
5. In KDP, upload the interior PDF, then the clean cover-wrap PDF, then the EPUB for the ebook edition.
6. Stop at the previewer. Look for clipped headers, missing glyphs, blank spreads, awkward page breaks, low-resolution images, and barcode overlap.
7. Order a physical proof. Screens are confident; paper is honest.

You do not need to publish the day you finish. A slow, verified upload is faster than a pretty file that has to be fixed twice.

## Troubleshooting

**"No book.yaml found"**  
Point the command at the folder that contains `book.yaml`, not the parent folder and not the `chapters` folder.

**"Each chapter must start with a single '# Chapter title' heading"**  
Each Markdown file needs exactly one level-one heading at the very top. Use `##` for sections below it.

**"Unknown trim size"**  
Run `kdp-book-builder trim-sizes`. Use the width × height form, such as `6x9`, not a name you invented.

**Margins are rejected**  
KDP has minimum inside margins that grow with the page count, and no-bleed interiors need at least 0.25 in on the outside edge. Remove your override and let the tool choose, then check the reported margins.

**A PDF chapter is missing from the contents**  
Rebuild once. If it continues, simplify very long headings or nested lists in that chapter and check the reported warnings.

**Images look soft**  
Aim for 300 DPI at the displayed size. A wide image on a 5 × 8 page prints smaller than it looks on screen; check the warnings.

**The EPUB gets rejected by a validator**  
The generated file is structurally checked by this project's tests, but ebook validators are strict and change often. Try a Kindle previewer first. Raw HTML, SVG, unusual filenames, or exotic links are common culprits; the build tries to warn about these.

**"Command not found: kdp-book-builder"**  
Your virtual environment may not be active. Activate it again, or use `python -m kdp_book_builder`.

## Development

Run the test suite:

```bash
python -m pytest
```

The tests build real PDFs and EPUBs in temporary folders. They do not need network access or any API keys.

If you have Java installed, you can also validate a generated EPUB with:

```bash
epubcheck dist/the-friendly-ai-field-guide/the-friendly-ai-field-guide.epub
```

`epubcheck` is optional and not needed to build a book.

The package source lives in `src/kdp_book_builder/`:

- `book.py` — reads and validates `book.yaml` and chapters
- `markdown.py` — Markdown-to-PDF and Markdown-to-XHTML rendering
- `layout.py` — trim sizes, paper, margins, spine, and cover math
- `pdf.py` — print interior
- `epub.py` — Kindle EPUB
- `cover.py` — cover wrap, measurement template, and ebook cover image
- `cli.py` — command-line interface

## Privacy, safety, and limits

Everything runs locally. The tool makes no network requests, contains no analytics, and asks for no account credentials. Your manuscript stays in your folder. It also does not send anything to KDP — you decide what to upload.

This is a file-building tool, not a publisher, lawyer, or ISBN service. It does not check copyright, plagiarism, medical accuracy, or KDP's content policies. You are responsible for the rights to your text and images and for verifying current KDP specifications.

## License

MIT License. See [`LICENSE`](LICENSE).

Bundled Liberation fonts are licensed separately under the SIL Open Font License; see [`src/kdp_book_builder/assets/fonts/LICENSE.txt`](src/kdp_book_builder/assets/fonts/LICENSE.txt).

Copyright (c) 2026 Asdale Dynamics, LLC.

Built by [Asdale Dynamics, LLC](https://dylanasdale.github.io), where AI is explained like a friend would.
