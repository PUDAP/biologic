"""
Send a batch of BioLogic queue commands from JSON.

Recommended usage: async context manager for automatic NATS cleanup.
"""
import json
import uuid
import asyncio
import logging
import os
from pathlib import Path
from puda import CommandService
from puda.models import CommandRequest, CommandResponseStatus, NATSMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

USER_ID = str(uuid.uuid4())
USERNAME = "zhao"
RUN_ID = str(uuid.uuid4())
COMMANDS_JSON_PATH = Path(__file__).parent / "biologic_commands.json"
NATS_SERVERS = "nats://100.86.162.126:4222,nats://100.86.162.126:4223,nats://100.86.162.126:4224"


def get_nats_servers() -> list[str]:
    nats_servers_env = os.getenv("NATS_SERVERS", NATS_SERVERS)
    return [s.strip() for s in nats_servers_env.split(",") if s.strip()]


def load_commands() -> list[dict]:
    with open(COMMANDS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


async def main():
    logger.info("Starting batch command tests with run_id: %s", RUN_ID)

    async with CommandService(servers=get_nats_servers()) as service:
        command_dicts = load_commands()
        requests = [CommandRequest(**cmd) for cmd in command_dicts]

        logger.info("Sending batch constructed from dicts (%d commands)...", len(requests))
        reply: NATSMessage = await service.send_queue_commands(
            requests=requests,
            run_id=RUN_ID,
            user_id=USER_ID,
            username=USERNAME,
        )

        if reply is None:
            logger.error("Batch commands failed or timed out")
            return

        if reply.response and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Batch commands completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
