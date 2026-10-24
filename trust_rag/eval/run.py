"""CLI entrypoint: uv run python -m trust_rag.eval.run"""

import asyncio

from trust_rag.db.session import dispose_engine, init_engine
from trust_rag.eval.harness import run_eval
from trust_rag.settings import get_settings


async def main() -> None:
    init_engine(get_settings().database_url)
    try:
        metrics = await run_eval()
    finally:
        await dispose_engine()

    print("\n=== Eval summary ===")
    for metric, value in metrics.items():
        print(f"  {metric:24} {value}")


if __name__ == "__main__":
    asyncio.run(main())
