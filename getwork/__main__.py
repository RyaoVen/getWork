"""CLI 入口：`python -m getwork` 启动 stdio MCP server。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import DEFAULT_DATA_DIR, set_config_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="getwork")
    parser.add_argument("--config", default=None, help="companies.yaml 路径（默认 config/companies.yaml）")
    parser.add_argument("--data-dir", default=None, help="数据目录：sessions/output/logs（默认 data/）")
    args = parser.parse_args(argv)

    if args.config:
        set_config_path(args.config)

    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=str(data_dir / "logs" / "getwork.log"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from .server import server

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
