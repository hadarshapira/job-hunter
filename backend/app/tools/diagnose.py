"""Diagnose how a job link is imported.

    docker compose exec api python -m app.tools.diagnose <url> [--save name]

Prints which extractor handled it, the parsed fields and the quality issues.
--save writes the raw HTML to /tmp/<name>.html. Use it to build a synthetic test fixture
(don't commit real third-party pages; copy the structure with made-up content).
"""

import argparse
import asyncio
import json

import httpx

from app.services.importer import USER_AGENT, fetch_and_parse


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--save", help="save the raw page as /tmp/<name>.html")
    args = p.parse_args()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        job = await fetch_and_parse(args.url, client)
        if args.save:
            raw = await client.get(args.url)
            path = f"/tmp/{args.save}.html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw.text)
            print(f"saved {len(raw.text)} chars to {path}")

    print(json.dumps(
        {
            "extractor": job.extra.get("extractor"),
            "complete": job.complete,
            "issues": job.issues,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "work_mode": str(job.work_mode),
            "salary": job.salary,
            "posted_at": str(job.posted_at),
            "description_chars": len(job.description),
            "description_start": job.description[:300],
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    asyncio.run(main())
