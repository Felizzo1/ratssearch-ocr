#!/usr/bin/env python3
"""
Lädt PDFs herunter, führt OCR durch und schreibt den extrahierten Text nach files/{id}.txt.

Eingabe: JSON-Liste von IDs (stdin oder --ids-file)
Aufruf:
  python3 find_missing.py | python3 ocr_batch.py [--max N]
  python3 ocr_batch.py --ids-file missing.json --max 500
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Dateien kleiner als dieser Schwellwert gelten nach OCR als "leer"
EMPTY_THRESHOLD = 50  # Bytes

# Commit alle N verarbeiteten IDs
COMMIT_BATCH_SIZE = 100

# Wenn weniger als diese Anzahl Minuten Action-Zeit verbleiben, sauber beenden
ACTION_TIMEOUT_MINUTES = 10

MIRROR_JSON_BASE = "https://raw.githubusercontent.com/offenesdresden/dresden-ratsinfo/master/files"

REPO_ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = REPO_ROOT / "files"
STATE_FILE = REPO_ROOT / "state" / "processed.json"


def load_state() -> dict:
    if STATE_FILE.is_file():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def action_time_ok(start: float, max_minutes: int = 330) -> bool:
    """Gibt False zurück wenn weniger als ACTION_TIMEOUT_MINUTES verbleiben."""
    elapsed_minutes = (time.time() - start) / 60
    return elapsed_minutes < (max_minutes - ACTION_TIMEOUT_MINUTES)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(requests.RequestException),
)
def download_pdf(file_id: str, dest: Path) -> None:
    """Lädt PDF herunter. Nutzt downloadUrl aus Mirror-JSON wenn verfügbar."""
    url = _resolve_download_url(file_id)
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)


def _resolve_download_url(file_id: str) -> str:
    """Liest downloadUrl aus Mirror-JSON; fällt auf konstruierten URL zurück."""
    json_url = f"{MIRROR_JSON_BASE}/{file_id}.json"
    try:
        resp = requests.get(json_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            url = data.get("downloadUrl", "")
            if url:
                return url
    except Exception:
        pass
    # Fallback: ID auf 8 Stellen mit führenden Nullen
    padded = file_id.zfill(8)
    return f"http://oparl.dresden.de/bodies/0001/downloadfiles/{padded}.pdf"


def run_ocrmypdf(input_pdf: Path, output_pdf: Path) -> None:
    subprocess.run(
        [
            "ocrmypdf",
            "-l", "deu",
            "--skip-text",          # Seiten mit vorhandener Textschicht nicht neu OCR-en
            "--output-type", "pdf",
            "--jobs", "2",
            str(input_pdf),
            str(output_pdf),
        ],
        check=True,
        capture_output=True,
    )


def pdf_to_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(pdf_path), "-"],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def git_commit(message: str) -> None:
    subprocess.run(["git", "-C", str(REPO_ROOT), "add", "files/", "state/"], check=True)
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--cached", "--quiet"]
    )
    if result.returncode == 0:
        return  # Nichts zu committen
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "commit", "-m", message],
        check=True,
    )


def process_id(file_id: str, state: dict, tmpdir: Path) -> str:
    """
    Verarbeitet eine einzelne ID. Gibt Status zurück: 'ok', 'empty', 'error'.
    Schreibt ggf. files/{id}.txt und aktualisiert state dict in-place.
    """
    input_pdf = tmpdir / f"{file_id}_in.pdf"
    output_pdf = tmpdir / f"{file_id}_ocr.pdf"

    try:
        download_pdf(file_id, input_pdf)
        run_ocrmypdf(input_pdf, output_pdf)
        text = pdf_to_text(output_pdf)

        if len(text.encode("utf-8")) >= EMPTY_THRESHOLD:
            FILES_DIR.mkdir(parents=True, exist_ok=True)
            out_txt = FILES_DIR / f"{file_id}.txt"
            out_txt.write_text(text, encoding="utf-8")
            state[file_id] = {"status": "ok", "ts": _now()}
            return "ok"
        else:
            state[file_id] = {"status": "empty", "ts": _now()}
            return "empty"

    except Exception as exc:
        state[file_id] = {"status": "error", "error": str(exc)[:200], "ts": _now()}
        print(f"  FEHLER bei {file_id}: {exc}", file=sys.stderr)
        return "error"
    finally:
        for p in (input_pdf, output_pdf):
            if p.exists():
                p.unlink()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids-file", help="JSON-Datei mit ID-Liste (sonst stdin)")
    parser.add_argument("--max", type=int, default=None, help="Maximale Anzahl IDs")
    parser.add_argument("--max-action-minutes", type=int, default=330,
                        help="Maximale Action-Laufzeit in Minuten (Default: 330 = 5.5h)")
    args = parser.parse_args()

    if args.ids_file:
        with open(args.ids_file, encoding="utf-8") as f:
            ids = json.load(f)
    else:
        ids = json.load(sys.stdin)

    if args.max:
        ids = ids[: args.max]

    if not ids:
        print("Keine IDs zu verarbeiten.", file=sys.stderr)
        return

    print(f"Starte OCR-Batch: {len(ids):,} IDs", file=sys.stderr)

    state = load_state()
    start_time = time.time()

    stats = {"ok": 0, "empty": 0, "error": 0}
    batch_count = 0

    with tempfile.TemporaryDirectory(prefix="ocr_tmp_") as tmpdir:
        tmp = Path(tmpdir)
        for i, file_id in enumerate(ids, 1):
            if not action_time_ok(start_time, args.max_action_minutes):
                print(f"  Zeitlimit erreicht nach {i-1} IDs, committe und beende.", file=sys.stderr)
                break

            print(f"  [{i}/{len(ids)}] {file_id} ...", file=sys.stderr, end=" ")
            status = process_id(file_id, state, tmp)
            stats[status] += 1
            batch_count += 1
            print(status, file=sys.stderr)

            if batch_count >= COMMIT_BATCH_SIZE:
                save_state(state)
                git_commit(f"OCR batch: {COMMIT_BATCH_SIZE} documents")
                batch_count = 0

    # Finaler Commit für verbleibende Änderungen
    save_state(state)
    git_commit(f"OCR batch: final commit ({stats['ok']} ok, {stats['empty']} empty, {stats['error']} error)")

    print(
        f"\nFertig: {stats['ok']} ok, {stats['empty']} leer, {stats['error']} Fehler",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
