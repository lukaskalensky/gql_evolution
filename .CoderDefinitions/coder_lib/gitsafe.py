"""
Git checkpointy: před každým krokem agenta se uloží snapshot pracovního stromu (včetně nových
souborů) jako commit pod `refs/cmd_coder/...`. Nijak se nemění index, větev ani pracovní strom
uživatele. Příkaz `undo` pak vrátí soubory do stavu před posledním krokem.

Omezení: soubory ignorované přes .gitignore se do snapshotu nedostanou, takže je undo neobnoví.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from .common import CHECKPOINTS_FILE_NAME, STATE_DIR_NAME, state_file

GIT_TIMEOUT = 120
MAX_CHECKPOINTS = 30
_IDENTITY = {
    "GIT_AUTHOR_NAME": "cmd_coder",
    "GIT_AUTHOR_EMAIL": "cmd_coder@localhost",
    "GIT_COMMITTER_NAME": "cmd_coder",
    "GIT_COMMITTER_EMAIL": "cmd_coder@localhost",
}
# Adresáře, které do snapshotu nepatří (stav agenta a pracovní data knihovny)
_EXCLUDES = [f":(exclude){STATE_DIR_NAME}", ":(exclude).pydantic-ai-harness"]


class GitError(RuntimeError):
    pass


def _git(
    args: list[str],
    cwd: Path,
    env: Optional[dict[str, str]] = None,
    binary: bool = False,
) -> Any:
    full_env = dict(os.environ)
    full_env.update(_IDENTITY)
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=full_env,
            capture_output=True,
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise GitError("git není nainstalován") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args[:2])} překročil časový limit {GIT_TIMEOUT}s") from exc
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} selhal")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def repo_root(workspace: Path) -> Optional[Path]:
    """Kořen git repozitáře obsahujícího workspace, nebo None (není repo / chybí git)."""
    try:
        out = _git(["rev-parse", "--show-toplevel"], workspace).strip()
        return Path(out) if out else None
    except GitError:
        return None


def _has_head(workspace: Path) -> bool:
    try:
        _git(["rev-parse", "--verify", "-q", "HEAD"], workspace)
        return True
    except GitError:
        return False


def snapshot_tree(workspace: Path) -> str:
    """Uloží aktuální stav workspace jako git tree (přes dočasný index) a vrátí jeho sha."""
    with tempfile.TemporaryDirectory(prefix="cmd_coder_idx_") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if _has_head(workspace):
            _git(["read-tree", "HEAD"], workspace, env)
        _git(["add", "-A", "--", ".", *_EXCLUDES], workspace, env)
        return _git(["write-tree"], workspace, env).strip()


def _load(workspace: Path) -> list[dict[str, Any]]:
    path = state_file(workspace, CHECKPOINTS_FILE_NAME)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(workspace: Path, items: list[dict[str, Any]]) -> None:
    path = state_file(workspace, CHECKPOINTS_FILE_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def list_checkpoints(workspace: Path) -> list[dict[str, Any]]:
    return _load(workspace)


def create_checkpoint(workspace: Path, step: int, history_len: int, label: str = "") -> dict[str, Any]:
    """Vytvoří checkpoint stavu PŘED krokem `step`. Při chybě vyhazuje GitError."""
    tree = snapshot_tree(workspace)
    args = ["commit-tree", tree, "-m", f"cmd_coder checkpoint before step {step}"]
    if _has_head(workspace):
        args += ["-p", "HEAD"]
    commit = _git(args, workspace).strip()
    ref = f"refs/cmd_coder/step-{step}-{int(time.time())}"
    _git(["update-ref", ref, commit], workspace)

    items = _load(workspace)
    entry = {
        "step": step,
        "commit": commit,
        "tree": tree,
        "ref": ref,
        "history_len": history_len,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label[:120],
    }
    items.append(entry)
    # Starší checkpointy uvolníme, aby repozitář nenabývalo
    while len(items) > MAX_CHECKPOINTS:
        old = items.pop(0)
        try:
            _git(["update-ref", "-d", old["ref"]], workspace)
        except GitError:
            pass
    _save(workspace, items)
    return entry


def _raw_diff(workspace: Path, old_tree: str, new_tree: str) -> list[tuple[str, str, str, str, str]]:
    """Seznam změn mezi stromy: (stav, cesta, staré_sha, starý_mode, nový_mode)."""
    out = _git(["diff-tree", "-r", "--no-renames", "-z", old_tree, new_tree], workspace, binary=True)
    tokens = out.split(b"\0")
    changes = []
    i = 0
    while i + 1 < len(tokens) and tokens[i].startswith(b":"):
        meta = tokens[i][1:].decode().split()
        path = tokens[i + 1].decode("utf-8", "replace")
        old_mode, new_mode, old_sha, _new_sha, status = meta[0], meta[1], meta[2], meta[3], meta[4][0]
        changes.append((status, path, old_sha, old_mode, new_mode))
        i += 2
    return changes


def describe_changes(workspace: Path, checkpoint: dict[str, Any]) -> list[tuple[str, str]]:
    """Co by `undo` změnilo: [(akce, cesta)], akce = 'smazat' | 'obnovit'."""
    current = snapshot_tree(workspace)
    result = []
    for status, path, *_ in _raw_diff(workspace, checkpoint["tree"], current):
        result.append(("smazat" if status == "A" else "obnovit", path))
    return result


def restore_checkpoint(workspace: Path, checkpoint: dict[str, Any]) -> dict[str, int]:
    """Vrátí soubory do stavu checkpointu. Vrací počty {'restored': n, 'deleted': n}."""
    root = repo_root(workspace)
    if root is None:
        raise GitError("workspace není v git repozitáři")
    current = snapshot_tree(workspace)
    counts = {"restored": 0, "deleted": 0}

    for status, path, old_sha, old_mode, _new_mode in _raw_diff(workspace, checkpoint["tree"], current):
        target = root / path
        if status == "A":
            if target.is_symlink() or target.exists():
                target.unlink()
                counts["deleted"] += 1
                parent = target.parent
                # prázdné nadřazené adresáře uvnitř repozitáře uklidíme
                while parent != root and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            continue

        if old_mode == "160000":  # submodul
            continue
        blob = _git(["cat-file", "blob", old_sha], workspace, binary=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        if old_mode == "120000":
            os.symlink(blob.decode("utf-8", "replace"), target)
        else:
            target.write_bytes(blob)
            target.chmod(0o755 if old_mode == "100755" else 0o644)
        counts["restored"] += 1
    return counts


def drop_checkpoints_from(workspace: Path, checkpoint: dict[str, Any]) -> None:
    """Po úspěšném undo zapomene tento checkpoint i všechny novější."""
    items = _load(workspace)
    keep = []
    for item in items:
        if item["time"] < checkpoint["time"] or (item["time"] == checkpoint["time"] and item["step"] < checkpoint["step"]):
            keep.append(item)
        else:
            try:
                _git(["update-ref", "-d", item["ref"]], workspace)
            except GitError:
                pass
    _save(workspace, keep)
