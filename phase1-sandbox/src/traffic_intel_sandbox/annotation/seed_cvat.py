"""C13 — Create CVAT tasks from the historical clip pack.

For each ``clip-NN-window.mp4`` in ``--clips-dir``, create a CVAT task with the
object-class label set from the taxonomy. Runs against a CVAT instance started
via ``make annotation-up`` (default http://localhost:8080).

This is a *best effort* seeder; CVAT REST API shape changes across releases.
If the call schema mismatches, the error is surfaced with the response body
so you can adjust without digging through docs.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
import yaml


def _cvat_auth() -> tuple[str, str]:
    user = os.environ.get("CVAT_USER", "admin")
    pw = os.environ.get("CVAT_PASSWORD", "change_me_locally")
    return user, pw


def _load_labels(taxonomy_path: Path) -> list[dict]:
    with taxonomy_path.open() as fh:
        tax = yaml.safe_load(fh)
    return [{"name": cls["name"], "color": _stable_color(cls["id"]), "attributes": []}
            for cls in tax["object_classes"]]


def _stable_color(class_id: int) -> str:
    palette = ["#E6194B", "#3CB44B", "#FFE119", "#4363D8",
               "#F58231", "#911EB4", "#42D4F4", "#F032E6"]
    return palette[class_id % len(palette)]


def create_task(
    host: str,
    session: requests.Session,
    name: str,
    labels: list[dict],
    clip_path: Path,
) -> int:
    # 1. Create empty task with labels
    resp = session.post(
        f"{host}/api/tasks",
        json={"name": name, "labels": labels, "mode": "interpolation"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"create task failed {resp.status_code}: {resp.text}")
    task_id = int(resp.json()["id"])

    # 2. Upload the clip as the task's data
    with clip_path.open("rb") as fh:
        resp = session.post(
            f"{host}/api/tasks/{task_id}/data",
            data={
                "image_quality": 75,
                "use_zip_chunks": "true",
                "use_cache": "true",
                "sorting_method": "lexicographical",
                "client_files[0]": clip_path.name,
            },
            files={"client_files[0]": (clip_path.name, fh, "video/mp4")},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"upload data failed {resp.status_code}: {resp.text}")

    return task_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed CVAT tasks from historical clips.")
    parser.add_argument("--clips-dir", type=Path, required=True, help="Historical pack root")
    parser.add_argument("--taxonomy", type=Path, required=True, help="taxonomy.yml path")
    parser.add_argument("--host", default=os.environ.get("CVAT_HOST", "http://localhost:8080"))
    parser.add_argument("--max-tasks", type=int, default=5,
                        help="Only seed the first N clips (avoid CVAT spam)")
    args = parser.parse_args(argv)

    if not args.clips_dir.exists():
        print(f"[seed] clips dir missing: {args.clips_dir}", file=sys.stderr)
        return 1

    labels = _load_labels(args.taxonomy)
    user, pw = _cvat_auth()
    session = requests.Session()
    session.auth = (user, pw)
    session.headers.update({"User-Agent": "traffic-intel-seeder/0.1"})

    clips = sorted(args.clips_dir.glob("*/clip-*.mp4"))[: args.max_tasks]
    if not clips:
        print(f"[seed] no clips in {args.clips_dir}", file=sys.stderr)
        return 1

    created = 0
    for clip in clips:
        name = f"{clip.parent.name}__{clip.stem}"
        try:
            task_id = create_task(args.host, session, name, labels, clip)
            print(f"[seed] created task #{task_id}  {name}", file=sys.stderr)
            created += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[seed] FAIL {name}: {exc}", file=sys.stderr)
            return 1

    print(f"[done] {created} CVAT task(s) created at {args.host}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
