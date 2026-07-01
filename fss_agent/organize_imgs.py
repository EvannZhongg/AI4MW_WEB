import argparse
import shutil
from pathlib import Path


CATEGORIES = ("chart", "image", "formula", "table")


def detect_category(filename: str) -> str | None:
    lower_name = filename.lower()
    for category in CATEGORIES:
        if category in lower_name:
            return category
    return None


def organize_imgs_dir(imgs_dir: Path) -> dict[str, int]:
    counts = {category: 0 for category in CATEGORIES}

    for category in CATEGORIES:
        (imgs_dir / category).mkdir(exist_ok=True)

    for item in imgs_dir.iterdir():
        if not item.is_file():
            continue

        category = detect_category(item.name)
        if category is None:
            continue

        target = imgs_dir / category / item.name
        if item.resolve() == target.resolve():
            continue

        shutil.move(str(item), str(target))
        counts[category] += 1

    return counts


def find_imgs_dirs(paths: list[Path]) -> list[Path]:
    imgs_dirs = []
    for path in paths:
        if path.is_dir() and path.name.lower() == "imgs":
            imgs_dirs.append(path)
            continue

        candidate = path / "imgs" if path.is_dir() else None
        if candidate and candidate.is_dir():
            imgs_dirs.append(candidate)

    return imgs_dirs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize image assets into chart/image/formula/table folders under each imgs directory."
    )
    parser.add_argument("paths", nargs="+", help="Paper directory paths or imgs directory paths")
    args = parser.parse_args()

    input_paths = [Path(raw_path) for raw_path in args.paths]
    imgs_dirs = find_imgs_dirs(input_paths)
    if not imgs_dirs:
        raise SystemExit("No imgs directories found.")

    for imgs_dir in imgs_dirs:
        counts = organize_imgs_dir(imgs_dir)
        print(f"{imgs_dir}: {counts}")


if __name__ == "__main__":
    main()
