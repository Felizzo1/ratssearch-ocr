#!/usr/bin/env python3
"""
Findet IDs aus dem Mirror offenesdresden/dresden-ratsinfo, deren files/{id}.txt
leer ist (<EMPTY_THRESHOLD Bytes) und die wir noch nicht OCR-verarbeitet haben.

Ausgabe: JSON-Liste von IDs auf stdout.

Aufruf:
  python3 find_missing.py [--mirror-path PATH] [--state-path PATH]
"""

import json
import os
import subprocess
import sys
import argparse

# Dateien kleiner als dieser Schwellwert gelten als "leer" (kein extrahierbarer Text)
EMPTY_THRESHOLD = 50  # Bytes

MIRROR_REPO = "https://github.com/offenesdresden/dresden-ratsinfo.git"
DEFAULT_MIRROR_PATH = "/tmp/dresden-ratsinfo-sparse"
DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "processed.json")
DEFAULT_OCR_FILES_PATH = os.path.join(os.path.dirname(__file__), "..", "files")


def sparse_clone_or_update(mirror_path: str) -> None:
    """Sparse-klont den Mirror (nur Dateinamen, keine Blobs) oder aktualisiert ihn."""
    if os.path.isdir(os.path.join(mirror_path, ".git")):
        print("Mirror bereits vorhanden, aktualisiere...", file=sys.stderr)
        subprocess.run(
            ["git", "-C", mirror_path, "fetch", "--depth=1", "origin", "master"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", mirror_path, "reset", "--hard", "origin/master"],
            check=True,
        )
    else:
        print(f"Klone Mirror sparse nach {mirror_path} ...", file=sys.stderr)
        os.makedirs(mirror_path, exist_ok=True)
        subprocess.run(
            [
                "git", "clone",
                "--depth=1",
                "--filter=blob:none",
                "--sparse",
                "--no-checkout",
                MIRROR_REPO,
                mirror_path,
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", mirror_path, "sparse-checkout", "set", "files"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", mirror_path, "checkout"],
            check=True,
        )


def list_mirror_files(mirror_path: str) -> dict[str, int]:
    """Gibt {id: size_in_bytes} für alle files/{id}.txt im Mirror zurück."""
    result = subprocess.run(
        ["git", "-C", mirror_path, "ls-tree", "-r", "-l", "HEAD", "files/"],
        capture_output=True,
        text=True,
        check=True,
    )
    files: dict[str, int] = {}
    for line in result.stdout.splitlines():
        # Format: <mode> <type> <hash> <size>\t<path>
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        path = parts[1].strip()
        if not path.endswith(".txt"):
            continue
        meta = parts[0].split()
        size = int(meta[3]) if len(meta) >= 4 and meta[3].isdigit() else 0
        file_id = os.path.basename(path)[: -len(".txt")]
        files[file_id] = size
    return files


def load_processed(state_path: str) -> set[str]:
    """Lädt IDs die schon verarbeitet wurden (egal mit welchem Status)."""
    if not os.path.isfile(state_path):
        return set()
    with open(state_path, encoding="utf-8") as f:
        data = json.load(f)
    return set(data.keys())


def main() -> None:
    parser = argparse.ArgumentParser(description="Findet IDs mit leeren Mirror-Texten")
    parser.add_argument("--mirror-path", default=DEFAULT_MIRROR_PATH)
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    parser.add_argument("--ocr-files-path", default=DEFAULT_OCR_FILES_PATH)
    parser.add_argument("--no-clone", action="store_true", help="Mirror nicht neu klonen")
    args = parser.parse_args()

    mirror_path = os.path.abspath(args.mirror_path)
    state_path = os.path.abspath(args.state_path)
    ocr_files_path = os.path.abspath(args.ocr_files_path)

    if not args.no_clone:
        sparse_clone_or_update(mirror_path)

    print("Lese Dateiliste aus Mirror...", file=sys.stderr)
    mirror_files = list_mirror_files(mirror_path)
    print(f"  {len(mirror_files):,} .txt-Dateien im Mirror gefunden", file=sys.stderr)

    processed = load_processed(state_path)
    print(f"  {len(processed):,} bereits verarbeitete IDs geladen", file=sys.stderr)

    missing: list[str] = []
    for file_id, size in mirror_files.items():
        if size >= EMPTY_THRESHOLD:
            continue  # Mirror hat bereits guten Text
        if file_id in processed:
            continue  # schon verarbeitet (OCR-Text vorhanden oder als "empty" markiert)
        ocr_txt = os.path.join(ocr_files_path, f"{file_id}.txt")
        if os.path.isfile(ocr_txt) and os.path.getsize(ocr_txt) >= EMPTY_THRESHOLD:
            continue  # OCR-Datei bereits vorhanden
        missing.append(file_id)

    print(f"  {len(missing):,} IDs zur OCR-Verarbeitung gefunden", file=sys.stderr)
    print(json.dumps(missing, ensure_ascii=False))


if __name__ == "__main__":
    main()
