"""Offline source review and owned-deployment proxy scope preparation."""

import argparse
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / ".workbench"
SOURCES = WORKSPACE / "sources"
PRIVATE = WORKSPACE / "private"

SOURCE_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".rs", ".go"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", "vendor", "examples", "fixtures"}
MAX_FILE_BYTES = 1_000_000
MAX_RESULTS = 500
RULES = {
    "auth/session": re.compile(r"\b(?:authorize|authorization|hasPermission|canAccess|getSession|verifyToken)\b", re.I),
    "outbound-request": re.compile(r"\b(?:fetch|axios|http\.request|https\.request|reqwest|HttpClient)\s*\(?", re.I),
    "file/path": re.compile(r"\b(?:readFile|writeFile|createReadStream|path\.join|path\.resolve|openat)\s*\(", re.I),
    "process-exec": re.compile(r"\b(?:execFile|spawn|execSync|child_process|Command::new)\b", re.I),
    "shared-cache": re.compile(r"\b(?:cache\.get|cache\.set|unstable_cache|revalidateTag)\s*\(?", re.I),
}
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")


def init_workspace():
    os.umask(0o077)
    for directory in (WORKSPACE, SOURCES, PRIVATE):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ValueError(f"Символическая ссылка вместо каталога: {directory}")
        directory.chmod(0o700)


def scan_source(source):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Укажите обычный локальный каталог с исходниками")
    root = source.resolve()
    if SOURCES.resolve() not in root.parents:
        raise ValueError("Исходники должны лежать внутри .workbench/sources/")

    matches = []
    for directory, subdirs, filenames in os.walk(root, followlinks=False):
        subdirs[:] = sorted(
            name for name in subdirs
            if name not in SKIP_DIRS and not name.startswith(".")
            and not (Path(directory) / name).is_symlink()
        )
        for name in sorted(filenames):
            file = Path(directory) / name
            if file.is_symlink() or file.suffix not in SOURCE_SUFFIXES:
                continue
            if file.stat().st_size > MAX_FILE_BYTES:
                continue
            with file.open(encoding="utf-8", errors="replace") as content:
                for number, line in enumerate(content, 1):
                    for category, pattern in RULES.items():
                        if pattern.search(line):
                            matches.append((str(file.relative_to(root)), number, category))
                            if len(matches) == MAX_RESULTS:
                                return matches
    return matches


def validate_owned_host(host):
    if host != host.lower() or host.strip() != host or any(c in host for c in "*/:@?\\#"):
        raise ValueError(f"Требуется точный DNS-хост своего деплоя: {host!r}")
    suffix = next((part for part in (".vercel.app", ".vercel.live") if host.endswith(part)), None)
    if suffix is None or not host.removesuffix(suffix):
        raise ValueError(f"Допустимы только собственные поддомены vercel.app / vercel.live: {host!r}")
    if any(not HOST_LABEL.fullmatch(label) for label in host.split(".")):
        raise ValueError(f"Некорректное имя хоста: {host!r}")
    return host


def build_scope(hosts):
    includes = []
    for host in dict.fromkeys(validate_owned_host(host) for host in hosts):
        for protocol, port in (("http", "80"), ("https", "443")):
            includes.append({
                "enabled": True,
                "file": "^/.*",
                "host": f"^{re.escape(host)}$",
                "port": f"^{port}$",
                "protocol": protocol,
            })
    if not includes:
        raise ValueError("Укажите хотя бы один собственный домен через --owned")
    return {"target": {"scope": {"advanced_mode": True, "include": includes, "exclude": []}}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Локальный стенд Vercel Bug Bounty")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="создать приватные каталоги для исследования")
    scan = commands.add_parser("scan", help="искать точки для ручного анализа без сети")
    scan.add_argument("source", type=Path)
    scope = commands.add_parser("scope", help="создать точный Burp scope для своих деплоев")
    scope.add_argument("--owned", action="append", default=[], metavar="HOST")
    scope.add_argument("--confirm-owned", action="store_true", help="подтвердить своё владение каждым HOST")
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            init_workspace()
            print(f"Каталоги созданы: {SOURCES} и {PRIVATE}")
        elif args.command == "scan":
            matches = scan_source(args.source)
            for path, line, category in matches:
                print(f"{path}:{line}: {category}")
            print(f"Совпадений для ручного анализа: {len(matches)}"
                  + (" (лимит вывода)" if len(matches) == MAX_RESULTS else ""))
        elif args.command == "scope":
            if not args.confirm_owned:
                raise ValueError("Требуется --confirm-owned для всех перечисленных доменов")
            result = build_scope(args.owned)
            init_workspace()
            destination = PRIVATE / "burp-owned-scope.json"
            destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            destination.chmod(0o600)
            print(f"Профиль создан: {destination}")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Ошибка: {exc}\n")


if __name__ == "__main__":
    main()
