#!/usr/bin/env python
"""Drona CLI: ingest course documents into an OKF bundle, then chat with them.

Uses the parent IIC-Please/.env for secrets (falls back to tutor/.env).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from drona.ingestion.docling_parser import DoclingParser
from drona.ingestion.validation import UploadRejected, validate_upload
from drona.knowledge.catalog import FileCatalog
from drona.knowledge.citations import CitationError, validate_answer
from drona.knowledge.okf_writer import OKFWriter
from drona.services.groq_client import ProviderError
from drona.services.groq_tutor import GroqTutor

TUTOR_DIR = Path(__file__).resolve().parent
PARENT_DIR = TUTOR_DIR.parent
SUPPORTED = {".pdf", ".docx"}
UPLOAD_MAX_BYTES = 25 * 1024 * 1024
UPLOAD_MAX_PAGES = 200
PARSER_TIMEOUT_SECONDS = 180.0
CONTEXT_MAX_CHARS = 14_000


def load_env() -> None:
    # Parent .env wins (it already holds GROQ_API_KEY); local .env is a fallback.
    for candidate in (PARENT_DIR / ".env", TUTOR_DIR / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            break


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def data_dir() -> Path:
    return Path(env("DATA_DIR", "./data")).resolve()


def data_okf() -> Path:
    return data_dir() / "okf"


def course_dirs() -> list[str]:
    root = data_okf()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.glob("*") if p.is_dir())


def ingest(path: Path) -> None:
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if f.is_file())
    parser = DoclingParser(PARSER_TIMEOUT_SECONDS)
    writer = OKFWriter(data_dir())
    for file in files:
        if file.suffix.lower() not in SUPPORTED:
            continue
        content = file.read_bytes()
        try:
            checked = validate_upload(
                file.name, content, max_bytes=UPLOAD_MAX_BYTES, max_pages=UPLOAD_MAX_PAGES
            )
            parsed = parser.parse(file, max_pages=UPLOAD_MAX_PAGES)
            writer.publish(checked, parsed.document_json, parsed.sections)
            print(f"ingested: {file.name} -> course {checked.course_id} ({len(parsed.sections)} sections)")
        except UploadRejected as exc:
            print(f"skipped {file.name}: {exc}", file=sys.stderr)
        except Exception as exc:  # parser timeout, bad document
            print(f"skipped {file.name}: {type(exc).__name__}: {exc}", file=sys.stderr)


def pick_course(course_id: str | None) -> str:
    courses = course_dirs()
    if not courses:
        print("No courses found. Run: tutor ingest <file-or-dir>", file=sys.stderr)
        sys.exit(1)
    if course_id:
        if course_id not in courses:
            print(f"Unknown course {course_id!r}. Available: {', '.join(courses)}", file=sys.stderr)
            sys.exit(1)
        return course_id
    if len(courses) == 1:
        return courses[0]
    print("Available courses:")
    for i, name in enumerate(courses, 1):
        print(f"  {i}. {name}")
    choice = input("Select a course number: ").strip()
    try:
        return courses[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice.", file=sys.stderr)
        sys.exit(1)


def print_answer(result, sources) -> None:
    print("\n" + result.text)
    if sources:
        print("\nSources:")
        for source in sources:
            pages = ", ".join(map(str, source.pages)) or "unknown"
            print(f"  [{source.source_id}] {source.source_file} — {source.title}, pages {pages}")
    print()


async def chat(course_id: str | None) -> None:
    api_key = env("GROQ_API_KEY")
    if not api_key:
        print("GROQ_API_KEY is not set (check parent .env)", file=sys.stderr)
        sys.exit(1)
    catalog = FileCatalog(data_okf(), max_context_chars=CONTEXT_MAX_CHARS)
    course = pick_course(course_id)
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as http:
        tutor = GroqTutor(
            http,
            api_key,
            env("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            env("GROQ_MODEL", "openai/gpt-oss-120b"),
            260,
            reasoning_effort="low",
        )
        print(f"Chatting with course {course}. Type a question; Ctrl-D to exit.")
        for line in sys.stdin:
            question = " ".join(line.split())
            if not question:
                continue
            context = catalog.build_context(course, question)
            try:
                raw = await tutor.answer(question, context, turn_id=question)
                answer, sources = validate_answer(raw, context)
                print_answer(answer, sources)
            except CitationError:
                print("\nThe answer cited an unknown source; please rephrase.\n")
            except ProviderError as exc:
                print(f"\nTutor unavailable: {exc}\n", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="tutor", description="Drona CLI file-grounded tutor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a PDF/DOCX file or a directory of them")
    p_ingest.add_argument("path", type=Path, help="File or directory to ingest")

    p_chat = sub.add_parser("chat", help="Chat with an ingested course")
    p_chat.add_argument("course_id", nargs="?", default=None, help="Course id (auto-pick if omitted)")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        ingest(args.path)
    else:
        asyncio.run(chat(args.course_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
