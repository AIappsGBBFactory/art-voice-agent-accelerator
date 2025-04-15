import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Callable, Any, Awaitable, Dict, List, Union

logger = logging.getLogger(__name__)

class RealtimeEventHandler:
    """
    Manages registration and dispatching of asynchronous event handlers.
    """

    def __init__(self) -> None:
        self.event_handlers: Dict[str, List[Callable[[dict], Union[Any, Awaitable[Any]]]]] = defaultdict(list)

    def on(self, event_name: str, handler: Callable[[Any], Any]) -> None:
        """
        Register an event handler for a specific event.
        """
        self.event_handlers[event_name].append(handler)
        logger.debug(f"Handler registered for event: {event_name}")

    def clear_event_handlers(self) -> None:
        """
        Clear all registered event handlers.
        """
        self.event_handlers.clear()
        logger.info("All event handlers cleared.")

    def dispatch(self, event_name: str, event: dict) -> None:
        """
        Dispatch an event to all registered handlers.
        """
        handlers = self.event_handlers.get(event_name, []) + \
                   self.event_handlers.get("*", [])

        prefix = event_name.split(".", 1)[0] + ".*"
        handlers += self.event_handlers.get(prefix, [])

        logger.debug(f"Dispatching event: {event_name} to {len(handlers)} handler(s)")

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception as e:
                logger.exception(f"Error dispatching event '{event_name}' with handler {handler}: {e}")

    async def wait_for_next(self, event_name: str) -> dict:
        """
        Wait for the next occurrence of a specific event.
        """
        future = asyncio.Future()

        def handler(event):
            if not future.done():
                future.set_result(event)
                self.event_handlers[event_name].remove(handler)

        self.on(event_name, handler)
        logger.debug(f"Waiting for next event: {event_name}")
        return await future
