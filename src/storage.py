"""Storage append-only con hash-chain per predictions.jsonl / outcomes.jsonl,
più gestione dell'indice data/pending.json."""
from __future__ import annotations

import hashlib
import json
import os

from . import config

GENESIS = "GENESIS"


def _canonical_json(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_hash(record_without_hash: dict) -> str:
    return hashlib.sha256(_canonical_json(record_without_hash).encode("utf-8")).hexdigest()


def _last_hash(filepath: str) -> str:
    if not os.path.exists(filepath):
        return GENESIS
    last_hash = GENESIS
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            last_hash = json.loads(line)["record_hash"]
    return last_hash


def append_record(filepath: str, record: dict) -> dict:
    """Aggiunge un record alla catena hash e lo scrive come riga JSONL.
    Ritorna il record completo (con prev_hash/record_hash)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    record = dict(record)
    record["prev_hash"] = _last_hash(filepath)
    record["record_hash"] = _record_hash(record)
    with open(filepath, "a", encoding="utf-8") as fh:
        fh.write(_canonical_json(record) + "\n")
    return record


def verify_chain(filepath: str) -> tuple[bool, str | None]:
    """Ricalcola l'intera catena hash e verifica che sia intatta."""
    if not os.path.exists(filepath):
        return True, None
    expected_prev = GENESIS
    with open(filepath, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            stored_hash = record.get("record_hash")
            stored_prev = record.get("prev_hash")
            if stored_prev != expected_prev:
                return False, f"riga {lineno}: prev_hash atteso {expected_prev}, trovato {stored_prev}"
            check = dict(record)
            del check["record_hash"]
            if _record_hash(check) != stored_hash:
                return False, f"riga {lineno}: record_hash non corrisponde al contenuto"
            expected_prev = stored_hash
    return True, None


def read_all(filepath: str) -> list[dict]:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_pending() -> list[dict]:
    if not os.path.exists(config.PENDING_FILE):
        return []
    with open(config.PENDING_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_pending(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(config.PENDING_FILE), exist_ok=True)
    with open(config.PENDING_FILE, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, sort_keys=True)
        fh.write("\n")


def add_pending(entry: dict) -> None:
    entries = load_pending()
    entries.append(entry)
    save_pending(entries)


def remove_pending(prediction_id: str) -> None:
    entries = [e for e in load_pending() if e["id"] != prediction_id]
    save_pending(entries)
