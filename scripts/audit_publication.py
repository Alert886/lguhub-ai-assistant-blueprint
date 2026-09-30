"""Scan staged blobs, never echo matched secret contents. Not a full DLP system."""
import json
from pathlib import Path
import re
import subprocess
from assistant.pipeline import normalize

RULES = {
    "credential_format": re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "private_address": re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    "literal_secret": re.compile(r'''(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*["']?\s*[:=]\s*["'][A-Za-z0-9_./+\-=]{12,}["']'''),
}
ALLOWED_SUFFIX = {".py", ".md", ".json", ".jsonl", ".html", ".css", ".js", ".txt", ".yml", ".example"}
ALLOWED_DATA = {"data/synthetic.jsonl", "data/eval.jsonl"}


def git(*args):
    return subprocess.check_output(["git", *args])


def audit():
    paths = [p for p in git("ls-files", "-z").decode().split("\0") if p]
    errors = []
    if not paths:
        raise RuntimeError("没有暂存/追踪文件；请先暂存要发布的文件")
    for name in paths:
        path = Path(name)
        if path.suffix not in ALLOWED_SUFFIX and name != ".gitignore":
            errors.append((name, 0, "file_type"))
        if name.startswith(("build/", ".cache/", ".venv/")) or (name.startswith(".env") and name != ".env.example"):
            errors.append((name, 0, "forbidden_path"))
        if name.startswith("data/") and name not in ALLOWED_DATA:
            errors.append((name, 0, "unapproved_data"))
        content = git("show", ":" + name).decode("utf-8")
        for number, line in enumerate(content.splitlines(), 1):
            for label, pattern in RULES.items():
                if pattern.search(line):
                    errors.append((name, number, label))
        if name == "data/synthetic.jsonl":
            for line in content.splitlines():
                normalize(json.loads(line))
        if name.endswith(".jsonl") and name not in ALLOWED_DATA:
            errors.append((name, 0, "unapproved_jsonl"))
    print(json.dumps({"files_scanned": len(paths), "findings": errors, "scope": "git index blobs"}, indent=2))
    return not errors


if __name__ == "__main__":
    raise SystemExit(0 if audit() else 1)
