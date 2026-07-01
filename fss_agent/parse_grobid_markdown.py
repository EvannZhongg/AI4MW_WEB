import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path


HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$")
ROMAN_PREFIX_RE = re.compile(
    r"^(?P<roman>[IVXLCDM]+(?:\s+[IVXLCDM]+)*)\s*\.\s*(?P<rest>\S.*)?$",
    re.IGNORECASE,
)
INLINE_ABSTRACT_RE = re.compile(
    r"Abstract(?:\b|(?=[A-Z]))\s*[:\-—–]?\s*(.*?)(?=Keywords(?:\b|(?=[A-Z]))\s*[:\-—–]?|$)",
    re.IGNORECASE | re.DOTALL,
)
INLINE_KEYWORDS_RE = re.compile(
    r"Keywords(?:\b|(?=[A-Z]))\s*[:\-—–]?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
AFFILIATION_RE = re.compile(
    r"\b(Department|School|College|Centre|Center|University|Universidade|Institute|Laboratory|Laboratories|Academy|Faculty|Division|Research|State Key|Key Laboratory|National|China|India)\b",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(<\/[^>]+>)\s*(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def normalize_whitespace(text: str) -> str:
    text = unescape(text).strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def normalize_heading_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title.strip())
    title = re.sub(
        r"^(?P<roman>[IVXLCDM\s]+)\.(?P<rest>\S.*)$",
        lambda m: f"{m.group('roman')}. {m.group('rest')}",
        title,
    )
    match = ROMAN_PREFIX_RE.match(title)
    if match:
        roman = re.sub(r"\s+", "", match.group("roman")).upper()
        rest = re.sub(r"\s+", " ", (match.group("rest") or "")).strip()
        return f"{roman}. {rest}".strip()
    return title


def is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("<div") or stripped.startswith("</div"):
        return True
    if stripped.startswith("![]("):
        return True
    return False


def split_author_candidates(lines: list[str]) -> tuple[str, list[str]]:
    cleaned_lines = []
    extracted_names = []

    for line in lines:
        line = re.sub(r"\b(e-?mail|emails?)\b\s*:?", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\S+@\S+", "", line)
        line = normalize_whitespace(line)
        if not line:
            continue
        cleaned_lines.append(line)

        name_part = AFFILIATION_RE.split(line, maxsplit=1)[0]
        name_part = name_part.strip(" ,;")
        if not name_part:
            continue

        for piece in re.split(r",| and ", name_part):
            piece = normalize_whitespace(piece).strip(" ,;")
            if not piece:
                continue
            if len(piece.split()) > 6:
                continue
            extracted_names.append(piece)

    authors_raw = normalize_whitespace(" ".join(cleaned_lines))
    unique_names = []
    seen = set()
    for name in extracted_names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique_names.append(name)

    if not unique_names and authors_raw:
        unique_names = [authors_raw]

    return authors_raw, unique_names


def extract_front_matter(lines: list[str], first_heading_idx: int | None) -> tuple[str, str, list[str], list[dict]]:
    front_end = first_heading_idx if first_heading_idx is not None else len(lines)
    title = ""
    title_idx = None

    for idx in range(front_end):
        match = HEADING_RE.match(lines[idx])
        if match and len(match.group(1)) == 1:
            title = normalize_whitespace(match.group(2))
            title_idx = idx
            break

    if title_idx is None:
        for idx in range(front_end):
            stripped = lines[idx].strip()
            if stripped:
                title = normalize_whitespace(stripped.lstrip("#").strip())
                title_idx = idx
                break

    author_lines = []
    front_sections = []

    if title_idx is not None:
        raw_front = "\n".join(lines[title_idx + 1 : front_end]).strip()
    else:
        raw_front = "\n".join(lines[:front_end]).strip()

    if raw_front:
        abstract_match = INLINE_ABSTRACT_RE.search(raw_front)
        keywords_match = INLINE_KEYWORDS_RE.search(raw_front)

        author_part = raw_front
        if abstract_match:
            author_part = raw_front[: abstract_match.start()]
        elif keywords_match:
            author_part = raw_front[: keywords_match.start()]

        author_lines = [line.strip() for line in author_part.splitlines() if not is_noise_line(line)]

        if abstract_match:
            abstract_text = normalize_whitespace(abstract_match.group(1))
            if abstract_text:
                front_sections.append({"title": "Abstract", "text": abstract_text})

        if keywords_match:
            keywords_text = normalize_whitespace(keywords_match.group(1))
            if keywords_text:
                front_sections.append({"title": "Keywords", "text": keywords_text})

    authors_raw, authors = split_author_candidates(author_lines)
    return title, authors_raw, authors, front_sections


def parse_sections(lines: list[str], start_idx: int) -> list[dict]:
    sections = []
    current_title = None
    buffer: list[str] = []

    def flush() -> None:
        if current_title is None:
            return
        text = "\n".join(buffer).strip()
        sections.append({"title": current_title, "text": normalize_whitespace(text)})

    for line in lines[start_idx:]:
        match = HEADING_RE.match(line)
        if match:
            flush()
            current_title = normalize_heading_title(match.group(2))
            buffer = []
            continue
        if current_title is not None:
            buffer.append(line)

    flush()
    return sections


def parse_markdown_file(path: Path) -> dict:
    text = clean_text(path.read_text(encoding="utf-8"))
    lines = text.splitlines()

    heading_indexes = [idx for idx, line in enumerate(lines) if HEADING_RE.match(line)]
    first_body_heading_idx = None
    for idx in heading_indexes:
        match = HEADING_RE.match(lines[idx])
        if match and len(match.group(1)) >= 2:
            first_body_heading_idx = idx
            break

    title, authors_raw, authors, front_sections = extract_front_matter(lines, first_body_heading_idx)
    start_idx = first_body_heading_idx if first_body_heading_idx is not None else len(lines)
    sections = front_sections + parse_sections(lines, start_idx)

    return {
        "title": title,
        "authors_raw": authors_raw,
        "authors": authors,
        "sections": sections,
    }


def build_simple_payload(parsed: dict) -> dict:
    return {
        "title": parsed.get("title", ""),
        "authors": parsed.get("authors", []),
        "sections": [{"title": item["title"], "text": item["text"]} for item in parsed.get("sections", [])],
    }


def collect_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(input_path.rglob("*.md"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse paper markdown and output structured JSON.")
    parser.add_argument("input", help="Markdown file or directory")
    parser.add_argument("-o", "--output", help="Output JSON file path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON with indentation")
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Output a simplified JSON structure containing only title, authors, and sections[{title, text}]",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input path does not exist: {input_path}")

    files = collect_input_files(input_path)
    if not files:
        raise SystemExit(f"No markdown files found under: {input_path}")

    results = [parse_markdown_file(path) for path in files]
    payload = results[0] if input_path.is_file() and len(results) == 1 else results

    if args.simple:
        if isinstance(payload, list):
            payload = [build_simple_payload(item) for item in payload]
        else:
            payload = build_simple_payload(payload)

    dump_kwargs = {"ensure_ascii": False}
    if args.pretty:
        dump_kwargs["indent"] = 2

    output_text = json.dumps(payload, **dump_kwargs)
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.buffer.write(output_text.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
