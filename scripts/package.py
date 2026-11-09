"""Package tracked sources and compiled web assets into the Windows ZIP."""
import argparse
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("zip", type=Path)
    args = cli.parse_args()
    root = Path(__file__).resolve().parent.parent
    if not (root / "web/dist/index.html").is_file():
        raise SystemExit("Build the web app with npm run build first.")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf8").split("\0")
    args.zip.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.zip, "w", compression=ZIP_DEFLATED, compresslevel=6) as output:
        for name in filter(None, tracked):
            path = root / name
            if path.is_file():
                output.write(path, Path("APEX-2026-Pit-Wall") / name)
        for path in sorted((root / "web/dist").rglob("*")):
            if path.is_file():
                output.write(path, Path("APEX-2026-Pit-Wall") / path.relative_to(root))
    print(args.zip.resolve())


if __name__ == "__main__":
    main()
