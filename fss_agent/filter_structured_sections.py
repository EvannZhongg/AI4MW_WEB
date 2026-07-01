import argparse
import json
import re
from pathlib import Path


DROP_EXACT = {
    "ABSTRACT",
    "KEYWORDS",
    "ACKNOWLEDGEMENT",
    "ACKNOWLEDGMENTS",
    "REFERENCES",
}

DROP_SUFFIX = {
    "INTRODUCTION",
    "CONCLUSION",
    "ACKNOWLEDGEMENT",
    "ACKNOWLEDGMENTS",
    "REFERENCES",
}


def normalize_title(title: str) -> str:
    normalized = title.strip().upper()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^[IVXLCDM]+\.\s*", "", normalized)
    return normalized


def should_drop(title: str) -> bool:
    normalized = normalize_title(title)
    if normalized in DROP_EXACT:
        return True
    for suffix in DROP_SUFFIX:
        if normalized.endswith(suffix):
            return True
    return False


def filter_file(path: Path) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sections = payload.get("sections", [])
    filtered_sections = [section for section in sections if not should_drop(section.get("title", ""))]
    payload["sections"] = filtered_sections
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(sections), len(filtered_sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter unwanted sections from structured_sections.json files.")
    parser.add_argument("paths", nargs="+", help="JSON file paths or paper directory paths")
    args = parser.parse_args()

    targets = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            path = path / "structured_sections.json"
        if not path.exists():
            raise SystemExit(f"Path does not exist: {path}")
        targets.append(path)

    for target in targets:
        before, after = filter_file(target)
        print(f"{target}: sections {before} -> {after}")


if __name__ == "__main__":
    main()
