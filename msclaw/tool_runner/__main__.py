"""Tool Runner entry point."""

import asyncio
import logging

from msclaw.tool_runner.service import start, shutdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def main():
    await start()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
