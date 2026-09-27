#!/usr/bin/env python3
"""Visual QA helper. Not part of formal export."""

from pathlib import Path
import argparse
import sys


def render_pdf_pages(pdf_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import pypdfium2
    except ImportError as error:
        raise SystemExit(
            "pypdfium2 is required only for Visual QA rendering. "
            "Install it separately; formal PDF export does not use it."
        ) from error

    document = pypdfium2.PdfDocument(str(pdf_path))
    written = []
    for index, page in enumerate(document, start=1):
        bitmap = page.render(scale=2)
        image = bitmap.to_pil()
        target = output_dir / f"{pdf_path.stem}_page_{index}.png"
        image.save(target)
        written.append(target)
        page.close()
    document.close()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a quote PDF to PNG for visual QA.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    pdf_path = args.pdf
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    output_dir = args.output_dir or pdf_path.parent / f"{pdf_path.stem}_preview"
    paths = render_pdf_pages(pdf_path, output_dir)
    for path in paths:
        print(path)


if __name__ == "__main__":
    sys.exit(main())
