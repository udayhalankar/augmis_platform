"""AUGMIS B1+B2 gateway HTML base-order correction (no auth/header changes)."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import sys
import textwrap

TARGET = Path("services/api/app/routes/instances.py")
EXPECTED_FUNCTION_SHA256 = "648f00c11a3a5da66d62f6d567f4c71f01344b21213c01f3d4b99ba71c274e19"
UPDATED_FUNCTION_SHA256 = "c3a60915ae63aa4757dd8bbca2447dcb9cda84233bf1b517d7d3eaf3433116a5"

BASE_BLOCK = r'''    if "<base " not in html.lower():

        html = re.sub(
            r"(?i)<head([^>]*)>",
            lambda match: (
                match.group(0)
                + (
                    '<base href="'
                    + gateway_base
                    + '">'
                )
            ),
            html,
            count=1,
        )

'''
RETURN_BLOCK = r'''    return html.encode(
        "utf-8"
    )'''


def extract_function(source: str) -> tuple[int, int, str]:
    start_marker = "def _rewrite_gateway_html("
    end_marker = "\nasync def _proxy_runtime_gateway_request("
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise ValueError("Gateway functions not found uniquely. Source review required.")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return start, end, source[start:end]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="AUGMIS repository root")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = Path(args.repo).resolve() / TARGET
    if not path.is_file():
        print(f"[BLOCKED] Source missing: {path}")
        return 2
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    try:
        source = raw.decode("utf-8").replace("\r\n", "\n")
        start, end, old_function = extract_function(source)
    except (UnicodeDecodeError, ValueError) as exc:
        print(f"[BLOCKED] {exc}")
        return 2
    if hashlib.sha256(old_function.encode("utf-8")).hexdigest() == UPDATED_FUNCTION_SHA256:
        print("[PASS] Gateway base-order correction already present.")
        return 0
    if hashlib.sha256(old_function.encode("utf-8")).hexdigest() != EXPECTED_FUNCTION_SHA256:
        print("[BLOCKED] Gateway HTML function changed since reviewed source; no files modified.")
        print("Please share current services/api/app/routes/instances.py for a targeted patch.")
        return 2
    if old_function.count(BASE_BLOCK) != 1 or old_function.count(RETURN_BLOCK) != 1:
        print("[BLOCKED] Expected gateway insertion points not unique; no files modified.")
        return 2
    new_function = old_function.replace(BASE_BLOCK, "", 1).replace(RETURN_BLOCK, BASE_BLOCK + RETURN_BLOCK, 1)
    updated_source = source[:start] + new_function + source[end:]
    compile(updated_source, str(path), "exec")
    print("[PASS] Compatible gateway HTML rewrite. No unrelated code changes required.")
    if args.check:
        print("[CHECK ONLY] No files changed.")
        return 0
    backup = path.with_name(path.name + ".before-b1b2-gateway.bak")
    if backup.exists():
        print(f"[BLOCKED] Backup already exists: {backup}. Preserve it and resolve manually.")
        return 2
    backup.write_bytes(raw)
    try:
        path.write_bytes(updated_source.replace("\n", newline).encode("utf-8"))
    except Exception:
        path.write_bytes(raw)
        raise
    print(f"[APPLIED] {path}")
    print(f"[BACKUP] {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
