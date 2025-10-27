import argparse
import asyncio
import logging
import os
from typing import Optional, Sequence

try:
    from seed_data import SeedTask, list_datasets, load_seed_tasks
except ImportError:  # pragma: no cover
    from .seed_data import SeedTask, list_datasets, load_seed_tasks  # type: ignore

from src.cosmosdb.manager import CosmosDBMongoCoreManager

logger = logging.getLogger("cosmos_init")
logging.basicConfig(level=logging.INFO, format="%(message)s")


async def upsert_documents(
    manager: CosmosDBMongoCoreManager,
    documents: Sequence[dict],
    id_field: str,
    dataset: str,
) -> None:
    """Upsert each document in the provided iterable.

    Args:
        manager: Cosmos manager targeting the destination container.
        documents: Documents to upsert.
        id_field: Identifier field used for the upsert query.
        dataset: Logical dataset name for logging context.

    Latency:
        Dominated by individual Cosmos DB round-trips per document.
    """
    for doc in documents:
        await asyncio.to_thread(
            manager.upsert_document,
            document=doc,
            query={id_field: doc[id_field]},
        )
        logger.info(
            "Upserted dataset=%s %s.%s %s=%s",
            dataset,
            manager.database.name,
            manager.collection.name,
            id_field,
            doc[id_field],
        )


async def process_task(task: SeedTask) -> None:
    """Execute a SeedTask against Cosmos DB.

    Args:
        task: SeedTask containing destination metadata and documents.

    Latency:
        Linear in the number of documents within the task.
    """
    manager = CosmosDBMongoCoreManager(database_name=task.database, collection_name=task.collection)
    logger.info(
        "Seeding dataset=%s collection=%s documents=%s",
        task.dataset,
        task.collection,
        len(task.documents),
    )
    await upsert_documents(manager, task.documents, task.id_field, dataset=task.dataset)


async def main(args: argparse.Namespace) -> None:
    """Seed Cosmos DB with the requested datasets.

    Args:
        args: Parsed CLI arguments.

    Latency:
        Proportional to the total number of documents across datasets.
    """
    available = list_datasets()
    scenario = os.getenv("SCENARIO")
    if args.datasets:
        dataset_names: Sequence[str] = tuple(dict.fromkeys(args.datasets))
    elif args.all_datasets:
        dataset_names = available
    elif scenario:
        resolved = _resolve_scenario_dataset(scenario, available)
        if resolved:
            logger.info("Resolved SCENARIO=%s to dataset=%s", scenario, resolved)
            dataset_names = (resolved,)
        else:
            logger.warning("SCENARIO=%s not recognized; defaulting to all datasets", scenario)
            dataset_names = available
    else:
        dataset_names = available
    tasks = load_seed_tasks(dataset_names, {"include_duplicates": args.include_duplicates})
    for task in tasks:
        await process_task(task)


def _resolve_scenario_dataset(scenario: str, available: Sequence[str]) -> Optional[str]:
    """Translate SCENARIO into a registered dataset name."""
    normalized = scenario.strip().lower().replace("-", "_")
    alias_map = {name.lower(): name for name in available}
    alias_map.update({"finance": "financial"})
    dataset = alias_map.get(normalized)
    if dataset in available:
        return dataset
    return None


def parse_args() -> argparse.Namespace:
    """Parse CLI flags.

    Returns:
        argparse.Namespace containing parsed arguments.

    Latency:
        Negligible.
    """
    parser = argparse.ArgumentParser(description="Initialize Cosmos DB with sample datasets.")
    parser.add_argument(
        "--dataset",
        dest="datasets",
        action="append",
        choices=list_datasets(),
        help="Dataset(s) to seed; may be supplied multiple times.",
    )
    parser.add_argument(
        "--all-datasets",
        action="store_true",
        help="Seed every registered dataset.",
    )
    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="List available dataset names and exit.",
    )
    parser.add_argument(
        "--include-duplicates",
        action="store_true",
        help="Include duplicate records where the dataset supports them.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.list_datasets:
        for name in list_datasets():
            print(name)
        raise SystemExit(0)
    asyncio.run(main(args=args))
    logger.info("Cosmos DB initialization completed.")