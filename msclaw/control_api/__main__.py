"""Control API entry point."""

import logging
import uvicorn
from msclaw.shared.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run(
        "msclaw.control_api.app:app",
        host="0.0.0.0",
        port=cfg.control_api_port,
        log_level="info",
    )
