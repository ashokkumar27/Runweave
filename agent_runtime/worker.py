import asyncio

from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client
from temporalio.worker import Worker

from .activities import ACTIVITIES
from .config import settings
from .dispatch import Dispatcher
from .runtime import get_store
from .telemetry import configure, configure_logging
from .workflow import RunWorkflow


async def connect():
    config = settings()
    # Startup retry is process coordination, not workflow code.
    for attempt in range(60):
        try:
            return await Client.connect(
                config.temporal_address, namespace=config.temporal_namespace, plugins=[PydanticAIPlugin()]
            )
        except Exception:
            if attempt == 59:
                raise RuntimeError("Temporal unavailable after startup budget") from None
            await asyncio.sleep(1)


async def main():
    configure_logging()
    config = settings()
    configure(config.otel_exporter_otlp_endpoint)
    client = await connect()
    store = get_store()
    dispatcher = Dispatcher(store, client, config.task_queue)
    try:
        async with Worker(
            client, task_queue=config.task_queue, workflows=[RunWorkflow], activities=ACTIVITIES
        ):
            await dispatcher.run()
    finally:
        await store.database.close()


if __name__ == "__main__":
    asyncio.run(main())
