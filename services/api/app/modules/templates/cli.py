"""Import an official model form from lex.uz from the command line.

    python -m app.modules.templates.cli preview 7220862
    python -m app.modules.templates.cli import 7220862 --annex 2 --target labor
    python -m app.modules.templates.cli import 7220862 --annex 2 --target labor --approve   # dev only
    python -m app.modules.templates.cli check

`--approve` (system approval without a second expert) is refused outside dev/test: in staging/prod the
draft must be approved in the CMS by another legal expert.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import init_engine, session_scope
from app.modules.templates import service


async def _run(args: argparse.Namespace) -> dict:
    if args.cmd == "preview":
        return await service.preview_document(args.doc_id)
    async with session_scope() as db:
        if args.cmd == "check":
            return await service.check_sources(db)
        tv = await service.import_from_lexuz(
            db,
            doc_id=args.doc_id,
            annex_number=args.annex,
            target_code=args.target,
            title=None,
            latin=not args.cyrillic,
            author=None,
        )
        out = {
            "template_version_id": str(tv.id),
            "code": tv.contract_type_code,
            "version": tv.version,
            "status": tv.status.value,
            "report": tv.report,
            "source": tv.source,
        }
        if args.approve:
            if not get_settings().is_dev:
                raise SystemExit("--approve is allowed only in dev/test; approve in the CMS instead")
            ctype = await service.approve(db, tv, None, system=True)
            out["approved"] = {"contract_type": ctype.code, "type_version": ctype.version}
        return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="templates")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preview")
    p.add_argument("doc_id")
    i = sub.add_parser("import")
    i.add_argument("doc_id")
    i.add_argument("--annex", type=int)
    i.add_argument("--target")
    i.add_argument("--cyrillic", action="store_true")
    i.add_argument("--approve", action="store_true")
    sub.add_parser("check")
    args = parser.parse_args()
    configure_logging("WARNING")
    init_engine()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(asyncio.run(_run(args)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
