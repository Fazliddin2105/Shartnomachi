"""python -m app.modules.laws.cli sync|check|show <code> <number>|search <words>"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.integrations import lexuz
from app.modules.laws import corpus


async def _sync(codes: list[str]) -> None:
    for i, code in enumerate(codes):
        if i:
            await asyncio.sleep(2)  # polite: one document at a time
        print(json.dumps(await corpus.import_source(code), ensure_ascii=False))


async def _check(codes: list[str]) -> int:
    changed = 0
    for code in codes:
        src = corpus.SOURCES[code]
        doc = await lexuz.fetch(src["doc_id"], lang="uz")
        try:
            local = corpus.load(code)
        except Exception:
            local = {}
        same = local.get("content_sha256") == doc.content_hash()
        changed += not same
        print(
            json.dumps(
                {
                    "code": code,
                    "local_edition": local.get("edition_date"),
                    "lexuz_edition": doc.edition_date.isoformat() if doc.edition_date else None,
                    "lost_force": doc.lost_force,
                    "up_to_date": same,
                },
                ensure_ascii=False,
            )
        )
        await asyncio.sleep(2)
    return changed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "check"):
        s = sub.add_parser(name)
        s.add_argument("codes", nargs="*", default=list(corpus.SOURCES))
    s = sub.add_parser("show")
    s.add_argument("code")
    s.add_argument("number")
    s = sub.add_parser("search")
    s.add_argument("words", nargs="+")
    s.add_argument("--codes", nargs="*")
    a = p.parse_args()
    if a.cmd == "sync":
        asyncio.run(_sync(a.codes))
    elif a.cmd == "check":
        sys.exit(1 if asyncio.run(_check(a.codes)) else 0)
    elif a.cmd == "show":
        print(json.dumps(corpus.article(a.code, a.number), ensure_ascii=False, indent=1))
    else:
        for h in corpus.search(" ".join(a.words), codes=a.codes):
            print(f"{h['code']} {h['number']}-modda. {h['title']}  [{(h['chapter'] or '')[:60]}]")


if __name__ == "__main__":
    main()
