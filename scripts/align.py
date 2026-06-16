#!/usr/bin/env python3
"""Symbolic Alignment Tool — verify project state via declarative symbols.

Symbols define project truth as typed properties and doc references.
Interlocks are edges between symbols that must stay consistent.
A Merkle-like hash tree locks the entire state for integrity checking.

Usage:
    python scripts/align.py init     Create starter manifest and lock
    python scripts/align.py lock     Regenerate manifest.lock from manifest.json
    python scripts/align.py check    Verify alignment (exit 0=ok, 1=broken, 2=stale)
    python scripts/align.py verify   Semantic diff between locked and current state
    python scripts/align.py status   Human-readable alignment report

All subcommands accept --project-dir to override project-root discovery.
"""

import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        f"align.py requires Python 3.10 or later "
        f"(found {sys.version_info.major}.{sys.version_info.minor}).\n"
    )
    sys.exit(1)

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone

# Force UTF-8 on stdout/stderr so the unicode glyphs render on Windows pipes too.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# ─── Paths ────────────────────────────────────────────────────────────────────
#
# Paths inside the manifest (docs[*]) and the constants below are RELATIVE to
# the project root. The project root is resolved at runtime via:
#   1. --project-dir CLI flag
#   2. $CLAUDE_PROJECT_DIR env var (if it contains symbols/manifest.json)
#   3. Walking up from this file's location looking for symbols/manifest.json
#   4. Current working directory (fallback, used during `init`)
#
# Read paths from disk via paths() / doc_path_abs(). Write paths into the lock
# verbatim from the manifest so the lock stays portable across checkouts.

MANIFEST_REL = "symbols/manifest.json"
LOCK_REL = "symbols/manifest.lock"
DOCS_REL = "docs"

_PROJECT_ROOT: str = ""  # set by resolve_project_root()


def resolve_project_root(cli_arg: str | None = None, for_init: bool = False) -> str:
    """Resolve the project root directory.

    Order of preference:
      1. --project-dir flag (absolute or relative to CWD)
      2. $CLAUDE_PROJECT_DIR env var, if it contains MANIFEST_REL
      3. Walk parents from this script's location looking for MANIFEST_REL
      4. CWD (always, for `init`; only as last resort otherwise)
    """
    if cli_arg:
        return os.path.abspath(cli_arg)

    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root and (
        for_init or os.path.isfile(os.path.join(env_root, MANIFEST_REL))
    ):
        return os.path.abspath(env_root)

    start = os.path.dirname(os.path.abspath(__file__))
    cur = start
    while True:
        if os.path.isfile(os.path.join(cur, MANIFEST_REL)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    return os.getcwd()


def paths() -> tuple[str, str, str]:
    """Return (manifest_abs, lock_abs, docs_dir_abs) for the resolved root."""
    return (
        os.path.join(_PROJECT_ROOT, MANIFEST_REL),
        os.path.join(_PROJECT_ROOT, LOCK_REL),
        os.path.join(_PROJECT_ROOT, DOCS_REL),
    )


def doc_path_abs(rel: str) -> str:
    """Resolve a manifest-declared doc path against the project root."""
    if os.path.isabs(rel):
        return rel
    return os.path.join(_PROJECT_ROOT, rel)


# ─── Color helpers ────────────────────────────────────────────────────────────

USE_COLOR = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def green(t):
    return _c("32", t)


def yellow(t):
    return _c("33", t)


def red(t):
    return _c("31", t)


def bold(t):
    return _c("1", t)


def dim(t):
    return _c("2", t)


# ─── Hashing helpers ─────────────────────────────────────────────────────────

def hash_bytes(data: bytes) -> str:
    """SHA-256, truncated to 16 hex chars."""
    return hashlib.sha256(data).hexdigest()[:16]


def hash_file(path: str) -> str | None:
    """Hash a file's contents streaming in 64KB chunks. Returns None if missing."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except FileNotFoundError:
        return None


def hash_properties(props: dict) -> str:
    """Deterministic hash of a properties dict."""
    canonical = json.dumps(props, sort_keys=True, separators=(",", ":"))
    return hash_bytes(canonical.encode())


def compute_leaf_hash(doc_hashes: list[str], prop_hash: str) -> str:
    """Leaf hash = hash(sorted doc hashes + prop hash)."""
    parts = sorted(doc_hashes) + [prop_hash]
    combined = "|".join(parts)
    return hash_bytes(combined.encode())


def compute_root_hash(leaf_hashes: list[str]) -> str:
    """Root hash = hash(sorted leaf hashes)."""
    combined = "|".join(sorted(leaf_hashes))
    return hash_bytes(combined.encode())


# ─── Interlock validation ────────────────────────────────────────────────────
#
# Two manifest syntaxes for the interlock value:
#
#   Short form (equality only, backward-compatible):
#     "interlocks": { "other.prop": "local_prop" }
#     → "this_symbol.local_prop must equal other.prop"
#
#   Long form (any operator):
#     "interlocks": {
#       "other.prop": {"op": "gte", "local": "local_prop"},
#       "feature_flags.list": {"op": "in", "local": "required_flag"},
#       "regime.classifier": {"op": "matches", "local": "expected_pattern"},
#       "secrets.token": {"op": "exists"}
#     }
#
# Operators:
#   eq      foreign == local                              (default for short form)
#   ne      foreign != local
#   gte     foreign >= local                              (numeric; TYPE_ERROR otherwise)
#   lte     foreign <= local                              (numeric)
#   in      foreign in local                              (local must be a list/tuple)
#   matches re.search(local_pattern, str(foreign))        (foreign coerced to str)
#   exists  foreign is present and not None               (local optional)

INTERLOCK_FORMAT_VERSION = 1
VALID_OPERATORS = frozenset({"eq", "ne", "gte", "lte", "in", "matches", "exists"})

# Pretty-printed operator symbols for lock interlock keys and status output.
_OP_SYMBOLS = {
    "eq": "==",
    "ne": "!=",
    "gte": ">=",
    "lte": "<=",
    "in": "∈",
    "matches": "=~",
    "exists": "exists",
}


def _interlock_result(sym, foreign_ref, local_prop, status, detail, op="eq") -> dict:
    return {
        "symbol": sym,
        "interlock": foreign_ref,
        "local_prop": local_prop,
        "op": op,
        "status": status,
        "detail": detail,
    }


def _parse_interlock_value(value):
    """Return (op, local_prop) from short-form string or long-form dict.

    Returns (None, None, error_detail) on malformed long-form."""
    if isinstance(value, str):
        return "eq", value, None
    if isinstance(value, dict):
        op = value.get("op", "eq")
        local = value.get("local")
        if op not in VALID_OPERATORS:
            return None, None, f"unknown op '{op}'; valid: {sorted(VALID_OPERATORS)}"
        # 'exists' is the only op where local is optional
        if op != "exists" and not local:
            return None, None, f"op '{op}' requires 'local' field"
        return op, local, None
    return None, None, f"interlock value must be string or object, got {type(value).__name__}"


def _apply_operator(op: str, foreign_val, local_val) -> tuple[str, str]:
    """Apply the operator; return (status, detail).

    status ∈ {"PASS", "FAIL", "TYPE_ERROR"}.
    """
    try:
        if op == "eq":
            return ("PASS" if foreign_val == local_val else "FAIL",
                    f"{foreign_val!r} {'==' if foreign_val == local_val else '!='} {local_val!r}")
        if op == "ne":
            return ("PASS" if foreign_val != local_val else "FAIL",
                    f"{foreign_val!r} {'!=' if foreign_val != local_val else '=='} {local_val!r}")
        if op in ("gte", "lte"):
            if not (isinstance(foreign_val, (int, float)) and isinstance(local_val, (int, float))):
                return ("TYPE_ERROR",
                        f"{op} requires numeric operands; got {type(foreign_val).__name__} and {type(local_val).__name__}")
            ok = foreign_val >= local_val if op == "gte" else foreign_val <= local_val
            sym = ">=" if op == "gte" else "<="
            return ("PASS" if ok else "FAIL", f"{foreign_val} {sym} {local_val}: {ok}")
        if op == "in":
            if not isinstance(local_val, (list, tuple)):
                return ("TYPE_ERROR",
                        f"'in' requires local property to be a list; got {type(local_val).__name__}")
            ok = foreign_val in local_val
            return ("PASS" if ok else "FAIL", f"{foreign_val!r} {'∈' if ok else '∉'} {list(local_val)!r}")
        if op == "matches":
            if not isinstance(local_val, str):
                return ("TYPE_ERROR",
                        f"'matches' requires local property to be a regex string; got {type(local_val).__name__}")
            try:
                pattern = re.compile(local_val)
            except re.error as e:
                return ("TYPE_ERROR", f"invalid regex {local_val!r}: {e}")
            ok = pattern.search(str(foreign_val)) is not None
            return ("PASS" if ok else "FAIL", f"re.search({local_val!r}, {foreign_val!r}): {ok}")
        if op == "exists":
            ok = foreign_val is not None
            return ("PASS" if ok else "FAIL", f"foreign value is {'present' if ok else 'None'}")
        # Should be unreachable thanks to VALID_OPERATORS gate
        return ("TYPE_ERROR", f"unhandled op '{op}'")
    except Exception as e:  # noqa: BLE001
        return ("TYPE_ERROR", f"operator {op} raised {type(e).__name__}: {e}")


def validate_interlocks(symbols: dict) -> list[dict]:
    """Check all interlock edges. Returns list of results."""
    results = []
    for sym_name, sym in symbols.items():
        for foreign_ref, raw_value in sym.get("interlocks", {}).items():
            op, local_prop, parse_err = _parse_interlock_value(raw_value)
            if parse_err:
                results.append(_interlock_result(
                    sym_name, foreign_ref, str(raw_value),
                    "INVALID_INTERLOCK", parse_err,
                ))
                continue

            # Parse "other_symbol.their_property"
            parts = foreign_ref.split(".", 1)
            if len(parts) != 2:
                results.append(_interlock_result(
                    sym_name, foreign_ref, local_prop or "",
                    "INVALID_REF", f"Cannot parse reference '{foreign_ref}'", op=op,
                ))
                continue

            other_sym, other_prop = parts

            if other_sym not in symbols:
                results.append(_interlock_result(
                    sym_name, foreign_ref, local_prop or "",
                    "MISSING_SYMBOL", f"Symbol '{other_sym}' not found", op=op,
                ))
                continue

            other_props = symbols[other_sym].get("properties", {})
            local_props = sym.get("properties", {})

            # 'exists' only inspects the foreign property; local can be absent.
            if op == "exists":
                foreign_val = other_props.get(other_prop)
                status, detail = _apply_operator(op, foreign_val, None)
                results.append(_interlock_result(
                    sym_name, foreign_ref, local_prop or "(none)",
                    status, detail, op=op,
                ))
                continue

            if other_prop not in other_props:
                results.append(_interlock_result(
                    sym_name, foreign_ref, local_prop,
                    "MISSING_PROPERTY", f"Property '{other_prop}' not found on '{other_sym}'", op=op,
                ))
                continue

            if local_prop not in local_props:
                results.append(_interlock_result(
                    sym_name, foreign_ref, local_prop,
                    "MISSING_PROPERTY", f"Local property '{local_prop}' not found on '{sym_name}'", op=op,
                ))
                continue

            foreign_val = other_props[other_prop]
            local_val = local_props[local_prop]

            status, detail = _apply_operator(op, foreign_val, local_val)
            results.append(_interlock_result(
                sym_name, foreign_ref, local_prop, status, detail, op=op,
            ))

    return results


# ─── Property type validation ───────────────────────────────────────────────
#
# A symbol may optionally declare `property_types` mapping each property name
# to a type spec. Validation runs at lock time and surfaces per-symbol issues
# distinct from interlock failures. If absent, properties remain untyped.
#
# Supported type specs:
#   "string"            isinstance(value, str)
#   "int"               isinstance(value, int) and not isinstance(value, bool)
#   "float"             isinstance(value, (int, float)) and not isinstance(value, bool)
#   "bool"              isinstance(value, bool)
#   "enum:a|b|c"        value in the named set
#   "semver"            str matching "MAJOR.MINOR.PATCH[-pre][+build]"

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def _check_type(value, type_spec: str) -> tuple[bool, str]:
    """Return (ok, detail)."""
    if type_spec == "string":
        return (isinstance(value, str), f"expected string, got {type(value).__name__}")
    if type_spec == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
        return (ok, f"expected int, got {type(value).__name__}")
    if type_spec == "float":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return (ok, f"expected float|int, got {type(value).__name__}")
    if type_spec == "bool":
        return (isinstance(value, bool), f"expected bool, got {type(value).__name__}")
    if type_spec.startswith("enum:"):
        members = type_spec[len("enum:"):].split("|")
        return (value in members, f"expected one of {members}, got {value!r}")
    if type_spec == "semver":
        if not isinstance(value, str):
            return (False, f"expected semver string, got {type(value).__name__}")
        ok = _SEMVER_RE.match(value) is not None
        return (ok, f"value {value!r} is not a valid semver")
    return (False, f"unknown type spec '{type_spec}'")


def validate_property_types(symbols: dict) -> dict[str, dict[str, str]]:
    """Return {symbol_name: {prop_name: error_detail}} for type mismatches."""
    errors: dict[str, dict[str, str]] = {}
    for sym_name, sym in symbols.items():
        type_map = sym.get("property_types", {})
        if not isinstance(type_map, dict) or not type_map:
            continue
        props = sym.get("properties", {})
        for prop_name, type_spec in type_map.items():
            if not isinstance(type_spec, str):
                errors.setdefault(sym_name, {})[prop_name] = (
                    f"type spec must be a string, got {type(type_spec).__name__}"
                )
                continue
            if prop_name not in props:
                errors.setdefault(sym_name, {})[prop_name] = (
                    f"declared in property_types but missing from properties"
                )
                continue
            ok, detail = _check_type(props[prop_name], type_spec)
            if not ok:
                errors.setdefault(sym_name, {})[prop_name] = detail
    return errors


# ─── Build lock data ─────────────────────────────────────────────────────────

def build_means(sym_name: str, props: dict) -> str:
    """Generate a human-readable summary of what a symbol's hash represents."""
    if not props:
        return f"{sym_name}: no properties defined"
    parts = [f"{k}={v}" for k, v in sorted(props.items())]
    return f"{sym_name}: {', '.join(parts)}"


def build_lock(manifest: dict) -> dict:
    """Build the full lock structure from a manifest."""
    symbols = manifest.get("symbols", {})
    interlock_results = validate_interlocks(symbols)
    type_errors_by_sym = validate_property_types(symbols)

    # Index interlock results by symbol
    interlock_by_sym = {}
    for r in interlock_results:
        interlock_by_sym.setdefault(r["symbol"], []).append(r)

    lock_symbols = {}
    leaf_hashes = []
    all_aligned = True
    if type_errors_by_sym:
        all_aligned = False

    for sym_name in sorted(symbols.keys()):
        sym = symbols[sym_name]
        props = sym.get("properties", {})
        docs = sym.get("docs", [])

        # Hash docs (paths in manifest are relative to project root)
        doc_entries = {}
        doc_hashes = []
        for doc_path in sorted(docs):
            h = hash_file(doc_path_abs(doc_path))
            if h is None:
                doc_entries[doc_path] = {"hash": "0" * 16, "status": "MISSING"}
                all_aligned = False
            else:
                doc_entries[doc_path] = {"hash": h, "status": "current"}
                doc_hashes.append(h)

        # Compute leaf hash
        prop_hash = hash_properties(props)
        leaf = compute_leaf_hash(doc_hashes, prop_hash)
        leaf_hashes.append(leaf)

        # Interlocks for this symbol — key includes operator for clarity in the lock
        sym_interlocks = {}
        for r in interlock_by_sym.get(sym_name, []):
            op_symbol = _OP_SYMBOLS.get(r["op"], r["op"])
            key = f"{r['interlock']} {op_symbol} {r['local_prop']}"
            sym_interlocks[key] = r["status"]
            if r["status"] != "PASS":
                all_aligned = False

        sym_entry = {
            "hash": leaf,
            "means": build_means(sym_name, props),
            "properties": dict(sorted(props.items())),
            "docs": doc_entries,
            "interlocks": sym_interlocks,
        }
        if sym_name in type_errors_by_sym:
            sym_entry["type_errors"] = type_errors_by_sym[sym_name]
        lock_symbols[sym_name] = sym_entry

    root = compute_root_hash(leaf_hashes) if leaf_hashes else hash_bytes(b"empty")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "root": root,
        "generated": now,
        "status": "aligned" if all_aligned else "broken",
        "symbols": lock_symbols,
    }


# ─── Subcommands ─────────────────────────────────────────────────────────────

def cmd_init(args):
    """Create starter manifest and lock."""
    manifest_path, lock_path, _ = paths()

    if os.path.exists(manifest_path) and not args.force:
        print(f"{manifest_path} already exists. Use --force to overwrite.")
        return 1

    os.makedirs(os.path.join(_PROJECT_ROOT, "symbols"), exist_ok=True)
    os.makedirs(os.path.join(_PROJECT_ROOT, "docs"), exist_ok=True)

    manifest = {
        "version": "1.0.0",
        "project": {
            "name": "my-project",
            "intent": "Describe what this project does",
        },
        "symbols": {
            "architecture": {
                "description": "Core system architecture and provider decisions",
                "docs": ["docs/architecture.md"],
                "properties": {
                    "provider": "akamai",
                    "schema_version": 3,
                },
                "interlocks": {},
            },
            "deployment": {
                "description": "Deployment targets and infrastructure requirements",
                "docs": ["docs/deployment.md"],
                "properties": {
                    "expects_provider": "akamai",
                    "expects_schema": 3,
                },
                "interlocks": {
                    "architecture.provider": "expects_provider",
                    "architecture.schema_version": "expects_schema",
                },
            },
        },
    }

    # Write manifest
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Created {manifest_path}")

    # Create placeholder docs
    for sym in manifest["symbols"].values():
        for doc_path in sym.get("docs", []):
            abs_doc = doc_path_abs(doc_path)
            os.makedirs(os.path.dirname(abs_doc), exist_ok=True)
            if not os.path.exists(abs_doc):
                with open(abs_doc, "w") as f:
                    title = os.path.splitext(os.path.basename(abs_doc))[0].replace("-", " ").title()
                    f.write(f"# {title}\n\nTODO: Document this.\n")
                print(f"Created {abs_doc}")

    # Generate lock
    lock = build_lock(manifest)
    with open(lock_path, "w") as f:
        json.dump(lock, f, indent=2)
        f.write("\n")
    print(f"Created {lock_path}")
    print(f"\nRoot hash: {lock['root']}")
    print(f"Status: {green('aligned') if lock['status'] == 'aligned' else red('broken')}")
    return 0


def cmd_lock(args):
    """Regenerate manifest.lock from manifest.json.

    Exit codes:
      0 = lock written and alignment holds
      1 = lock written but alignment is broken (unless --allow-broken)
      2 = manifest missing or unreadable
    """
    manifest_path, lock_path, _ = paths()

    if not os.path.exists(manifest_path):
        print(red(f"Error: {manifest_path} not found. Run 'align.py init' first."))
        return 2

    with open(manifest_path) as f:
        manifest = json.load(f)

    lock = build_lock(manifest)
    with open(lock_path, "w") as f:
        json.dump(lock, f, indent=2)
        f.write("\n")

    print(f"Lock generated: {lock_path}")
    print(f"Root hash: {lock['root']}")
    print(f"Status: {green('aligned') if lock['status'] == 'aligned' else red(lock['status'])}")

    if lock["status"] != "aligned":
        if args.allow_broken:
            print(f"\n{yellow('Warning:')} Lock was generated but alignment is broken (--allow-broken).")
            print("Run 'align.py status' for details.")
            return 0
        print(f"\n{red('Error:')} Lock was generated but alignment is broken.")
        print("Run 'align.py status' for details. Pass --allow-broken to suppress this exit code.")
        return 1

    return 0


def cmd_check(args):
    """Verify alignment. Exit 0=aligned, 1=broken, 2=stale."""
    quiet = args.quiet
    manifest_path, lock_path, _ = paths()

    if not os.path.exists(manifest_path):
        if quiet:
            print("ALIGNMENT: manifest missing", file=sys.stderr)
        else:
            print(red(f"Error: {manifest_path} not found."))
        return 1

    if not os.path.exists(lock_path):
        if quiet:
            print("ALIGNMENT: lock missing", file=sys.stderr)
        else:
            print(red(f"Error: {lock_path} not found. Run 'align.py lock' first."))
        return 1

    with open(manifest_path) as f:
        manifest = json.load(f)
    with open(lock_path) as f:
        stored_lock = json.load(f)

    # Rebuild from current state
    current_lock = build_lock(manifest)

    # Compare root hashes
    issues = []

    if current_lock["root"] != stored_lock["root"]:
        issues.append("Root hash mismatch — lock is stale")

    # Check for broken interlocks, missing docs, and type errors
    for sym_name, sym_data in current_lock["symbols"].items():
        for interlock_key, status in sym_data.get("interlocks", {}).items():
            if status != "PASS":
                issues.append(f"Broken interlock in '{sym_name}': {interlock_key} → {status}")

        for doc_path, doc_data in sym_data.get("docs", {}).items():
            if doc_data["status"] == "MISSING":
                issues.append(f"Missing doc in '{sym_name}': {doc_path}")

        for prop_name, type_detail in sym_data.get("type_errors", {}).items():
            issues.append(f"Type error in '{sym_name}.{prop_name}': {type_detail}")

    # Determine exit code
    if not issues:
        if not quiet:
            print(green("Alignment: OK"))
        return 0

    has_broken = any(
        "Broken interlock" in i or "Missing doc" in i or "Type error" in i
        for i in issues
    )
    has_stale = any("stale" in i.lower() for i in issues)

    if quiet:
        if has_broken:
            print(f"ALIGNMENT: broken — {len(issues)} issue(s)", file=sys.stderr)
        elif has_stale:
            print("ALIGNMENT: stale lock — run 'align.py lock'", file=sys.stderr)
        return 1 if has_broken else 2

    print(red(f"Alignment: BROKEN — {len(issues)} issue(s)\n"))
    for issue in issues:
        print(f"  • {issue}")
    print(f"\nRun '{bold('python scripts/align.py status')}' for full details.")

    return 1 if has_broken else 2


def _diff_dicts(stored: dict, current: dict) -> list[tuple[str, str, object, object]]:
    """Return [(change_kind, key, stored_val, current_val), ...].

    change_kind ∈ {'added', 'removed', 'changed'}.
    """
    out: list[tuple[str, str, object, object]] = []
    for k in sorted(set(stored) | set(current)):
        s_has, c_has = k in stored, k in current
        if c_has and not s_has:
            out.append(("added", k, None, current[k]))
        elif s_has and not c_has:
            out.append(("removed", k, stored[k], None))
        elif stored[k] != current[k]:
            out.append(("changed", k, stored[k], current[k]))
    return out


def cmd_verify(args):
    """Semantic diff between locked state and current state.

    Exit codes:
      0 = in sync (root hashes match)
      1 = drift includes broken interlocks, missing docs, or type errors
      2 = drift is consistent (everything still passes) but lock is stale
    """
    manifest_path, lock_path, _ = paths()

    if not os.path.exists(manifest_path):
        print(red(f"Error: {manifest_path} not found."))
        return 1
    if not os.path.exists(lock_path):
        print(red(f"Error: {lock_path} not found. Run 'align.py lock' first."))
        return 1

    with open(manifest_path) as f:
        manifest = json.load(f)
    with open(lock_path) as f:
        stored = json.load(f)

    current = build_lock(manifest)

    if current["root"] == stored["root"]:
        print(green("In sync — locked state matches current state."))
        return 0

    print(bold("═══ Semantic Drift Report ═══"))
    print(f"Locked at:  {stored.get('generated', '?')}")
    print(f"Locked root: {stored['root']}")
    print(f"Current root: {current['root']}")
    print()

    stored_syms = stored.get("symbols", {})
    current_syms = current.get("symbols", {})
    all_keys = sorted(set(stored_syms) | set(current_syms))

    has_broken = current["status"] != "aligned"
    drift_count = 0

    for sym_name in all_keys:
        s = stored_syms.get(sym_name)
        c = current_syms.get(sym_name)

        if c is None:
            print(red(f"── {sym_name} ── REMOVED"))
            print(f"  was: {s.get('means', '?')}")
            print()
            drift_count += 1
            continue
        if s is None:
            print(green(f"── {sym_name} ── ADDED"))
            print(f"  now: {c.get('means', '?')}")
            print()
            drift_count += 1
            continue

        if s.get("hash") == c.get("hash") and s.get("interlocks") == c.get("interlocks"):
            continue  # symbol unchanged

        drift_count += 1
        print(bold(f"── {sym_name} ──"))
        print(f"  was: {s.get('means', '?')}")
        print(f"  now: {c.get('means', '?')}")

        # Property-level diff
        prop_diff = _diff_dicts(s.get("properties", {}), c.get("properties", {}))
        if prop_diff:
            print(f"  Properties:")
            for kind, k, sv, cv in prop_diff:
                if kind == "added":
                    print(f"    {green('+')} {k} = {cv!r}")
                elif kind == "removed":
                    print(f"    {red('-')} {k} = {sv!r}")
                else:
                    print(f"    {yellow('~')} {k}: {sv!r} → {cv!r}")

        # Doc-level diff
        s_docs = {p: d.get("hash") for p, d in s.get("docs", {}).items()}
        c_docs = {p: d.get("hash") for p, d in c.get("docs", {}).items()}
        doc_diff = _diff_dicts(s_docs, c_docs)
        if doc_diff:
            print(f"  Docs:")
            for kind, k, sv, cv in doc_diff:
                if kind == "added":
                    print(f"    {green('+')} {k}")
                elif kind == "removed":
                    print(f"    {red('-')} {k}")
                else:
                    # Hash changed — content edited
                    if cv == "0" * 16:
                        print(f"    {red('✗')} {k} (now MISSING)")
                    else:
                        print(f"    {yellow('~')} {k} (content changed)")

        # Interlock status diff
        s_ilk = s.get("interlocks", {})
        c_ilk = c.get("interlocks", {})
        ilk_diff = _diff_dicts(s_ilk, c_ilk)
        if ilk_diff:
            print(f"  Interlocks:")
            for kind, k, sv, cv in ilk_diff:
                if kind == "added":
                    print(f"    {green('+')} {k} → {cv}")
                elif kind == "removed":
                    print(f"    {red('-')} {k} (was {sv})")
                else:
                    print(f"    {yellow('~')} {k}: {sv} → {cv}")

        # Type errors (current only — stored is from before drift)
        type_errors = c.get("type_errors", {})
        if type_errors:
            print(f"  Type errors:")
            for prop, detail in type_errors.items():
                print(f"    {red('✗')} {prop}: {detail}")

        print()

    if drift_count == 0:
        # Roots differ but no symbol-level changes — probably a generated-timestamp mismatch
        print(yellow("Roots differ but no symbol drift detected (likely a re-lock with no changes)."))

    if has_broken:
        print(red(bold("Drift is BROKEN — interlocks fail, docs missing, or type errors.")))
        print(f"Fix the root cause, then run '{bold('python scripts/align.py lock')}'.")
        return 1

    print(yellow(bold("Drift is consistent but lock is stale.")))
    print(f"Run '{bold('python scripts/align.py lock')}' to update the lock.")
    return 2


def cmd_status(args):
    """Human-readable alignment report."""
    manifest_path, lock_path, _ = paths()

    if not os.path.exists(manifest_path):
        print(red(f"Error: {manifest_path} not found. Run 'align.py init' first."))
        return 1

    with open(manifest_path) as f:
        manifest = json.load(f)

    project = manifest.get("project", {})
    symbols = manifest.get("symbols", {})

    print(bold("═══ Symbolic Alignment Status ═══"))
    print(f"Project: {project.get('name', 'unknown')}")
    print(f"Intent:  {project.get('intent', 'not specified')}")
    print(f"Root:    {_PROJECT_ROOT}")
    print()

    # Check if lock exists
    lock_exists = os.path.exists(lock_path)
    stored_lock = None
    if lock_exists:
        with open(lock_path) as f:
            stored_lock = json.load(f)
        print(f"Lock: {stored_lock['root']} (generated {stored_lock['generated']})")
    else:
        print(yellow("Lock: not generated — run 'align.py lock'"))

    # Rebuild current state
    current_lock = build_lock(manifest)

    stale = lock_exists and current_lock["root"] != stored_lock["root"]
    if stale:
        print(yellow(f"Current root: {current_lock['root']} — STALE, run 'align.py lock'"))
    elif lock_exists:
        print(green(f"Root: {current_lock['root']} — current"))

    print()

    # Per-symbol report
    interlock_results = validate_interlocks(symbols)
    interlock_by_sym = {}
    for r in interlock_results:
        interlock_by_sym.setdefault(r["symbol"], []).append(r)

    overall_ok = True

    for sym_name in sorted(symbols.keys()):
        sym = symbols[sym_name]
        props = sym.get("properties", {})
        docs = sym.get("docs", [])
        sym_ok = True

        print(bold(f"── {sym_name} ──"))
        print(f"  {dim(sym.get('description', 'no description'))}")

        # Docs
        if docs:
            print(f"  Docs:")
            for doc_path in sorted(docs):
                abs_doc = doc_path_abs(doc_path)
                if os.path.exists(abs_doc):
                    h = hash_file(abs_doc)
                    print(f"    {green('✓')} {doc_path} [{h}]")
                else:
                    print(f"    {red('✗')} {doc_path} [MISSING]")
                    sym_ok = False
        else:
            print(f"  Docs: {dim('none')}")

        # Properties (with type-check annotation if property_types declared)
        type_map = sym.get("property_types", {})
        type_errors = validate_property_types({sym_name: sym}).get(sym_name, {})
        if props:
            print(f"  Properties:")
            for k, v in sorted(props.items()):
                declared = type_map.get(k)
                if k in type_errors:
                    print(f"    {red('✗')} {k}: {v} → TYPE_ERROR: {type_errors[k]}")
                    sym_ok = False
                elif declared:
                    print(f"    {green('✓')} {k}: {v} ({declared})")
                else:
                    print(f"    {k}: {v}")

        # Interlocks
        sym_interlocks = interlock_by_sym.get(sym_name, [])
        if sym_interlocks:
            print(f"  Interlocks:")
            for r in sym_interlocks:
                op_sym = _OP_SYMBOLS.get(r.get("op", "eq"), r.get("op", "eq"))
                if r["status"] == "PASS":
                    print(f"    {green('✓')} {r['interlock']} {op_sym} {r['local_prop']} ({r['detail']})")
                else:
                    print(f"    {red('✗')} {r['interlock']} {op_sym} {r['local_prop']} → {r['status']} ({r['detail']})")
                    sym_ok = False
        else:
            print(f"  Interlocks: {dim('none')}")

        status_str = green("ALIGNED") if sym_ok else red("BROKEN")
        print(f"  Status: {status_str}")
        print()

        if not sym_ok:
            overall_ok = False

    # Summary
    if overall_ok and not stale:
        print(green(bold("All symbols aligned.")))
    elif stale and overall_ok:
        print(yellow(bold("Symbols consistent but lock is stale. Run 'align.py lock'.")))
    else:
        print(red(bold("Alignment broken. Fix issues above, then run 'align.py lock'.")))

    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Symbolic Alignment Tool — verify project state via declarative symbols.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--project-dir",
        help="Project root directory (default: auto-discover from $CLAUDE_PROJECT_DIR or by walking parents)",
    )
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Create starter manifest and lock")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing manifest")

    lock_p = sub.add_parser("lock", help="Regenerate manifest.lock from manifest.json")
    lock_p.add_argument(
        "--allow-broken",
        action="store_true",
        help="Exit 0 even if the regenerated lock is broken (default: exit 1)",
    )

    check_p = sub.add_parser("check", help="Verify alignment (exit 0=ok, 1=broken, 2=stale)")
    check_p.add_argument("--quiet", action="store_true", help="One-line output to stderr")

    sub.add_parser("verify", help="Semantic diff between locked and current state (exit 0=sync, 1=broken, 2=stale)")
    sub.add_parser("status", help="Human-readable alignment report")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Resolve project root once, store in module global
    global _PROJECT_ROOT
    _PROJECT_ROOT = resolve_project_root(
        cli_arg=args.project_dir,
        for_init=(args.command == "init"),
    )

    commands = {
        "init": cmd_init,
        "lock": cmd_lock,
        "check": cmd_check,
        "verify": cmd_verify,
        "status": cmd_status,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
