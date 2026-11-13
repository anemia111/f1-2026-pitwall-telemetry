"""Build the static PS5 live connection page for GitHub Pages."""

import argparse
from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    target = parser.parse_args().output
    target.mkdir(parents=True, exist_ok=True)

    for filename in ("index.html", "pages.css"):
        copyfile(ROOT / "web" / "pages" / filename, target / filename)
    copyfile(ROOT / "web" / "src" / "style.css", target / "pitwall.css")
    copyfile(ROOT / "LICENSE", target / "LICENSE")
    (target / "README.md").write_text(
        "# APEX 2026 Pit Wall\n\nGitHub Pages entry point for the Windows PS5 live dashboard.\n",
        encoding="utf8",
    )
    (target / ".nojekyll").touch()


if __name__ == "__main__":
    main()
