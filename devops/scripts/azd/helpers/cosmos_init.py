import argparse
import asyncio
import logging
import os
from typing import Mapping, Optional, Protocol, Sequence

from azure.identity import CredentialUnavailableError, DefaultAzureCredential
from pymongo import MongoClient
from pymongo.auth_oidc import OIDCCallback, OIDCCallbackContext, OIDCCallbackResult
from pymongo.errors import InvalidURI

try:
    from seed_data import SeedTask, list_datasets, load_seed_tasks
except ImportError:  # pragma: no cover
    from .seed_data import SeedTask, list_datasets, load_seed_tasks  # type: ignore

logger = logging.getLogger("cosmos_init")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class ManagerProtocol(Protocol):
    database: object
    collection: object

    def upsert_document(self, document: dict, query: Mapping[str, object]) -> None:
        ...


class AzureIdentityTokenCallback(OIDCCallback):
    """OIDC callback for Azure managed identity authentication."""
    
    def __init__(self, credential):
        self.credential = credential

    def fetch(self, context: OIDCCallbackContext) -> OIDCCallbackResult:
        token = self.credential.get_token(
            "https://ossrdbms-aad.database.windows.net/.default"
        ).token
        return OIDCCallbackResult(access_token=token)


class _ConnectionStringManager:
    """Lightweight manager that uses a Cosmos connection string."""

    def __init__(self, connection_string: str, database_name: str, collection_name: str) -> None:
        try:
            self._client = MongoClient(connection_string, tz_aware=True)
        except InvalidURI:
            # Fall back to managed identity if connection string is invalid
            credential = DefaultAzureCredential()
            auth_properties = {"OIDC_CALLBACK": AzureIdentityTokenCallback(credential)}
            
            # Extract cluster name from connection string if possible
            cluster_name = self._extract_cluster_name(connection_string)
            if cluster_name:
                mongo_uri = f"mongodb+srv://{cluster_name}.global.mongocluster.cosmos.azure.com/"
                self._client = MongoClient(
                    mongo_uri,
                    connectTimeoutMS=120000,
                    tls=True,
                    retryWrites=True,
                    authMechanism="MONGODB-OIDC",
                    authMechanismProperties=auth_properties,
                    tz_aware=True
                )
            else:
                raise
        
        self.database = self._client[database_name]
        self.collection = self.database[collection_name]
        address = next(iter(self._client.nodes), (None, None))
        self.cluster_host = address[0] or "connection-string"

    def _extract_cluster_name(self, connection_string: str) -> Optional[str]:
        """Extract cluster name from connection string for managed identity fallback."""
        # Look for cluster name pattern in connection string
        match = re.search(r'mongodb\+srv://([^.]+)\.global\.mongocluster\.cosmos\.azure\.com', connection_string)
        return match.group(1) if match else None

    def upsert_document(self, document: dict, query: Mapping[str, object]) -> None:
        self.collection.update_one(query, {"$set": document}, upsert=True)


class _ManagedIdentityManager:
    """Mongo manager that authenticates with Azure AD."""

    def __init__(self, cluster_name: str, database_name: str, collection_name: str) -> None:
        if not cluster_name:
            raise ValueError("AZURE_COSMOS_CLUSTER_NAME is required for managed identity authentication.")
        credential = DefaultAzureCredential()
        auth_properties = {"OIDC_CALLBACK": AzureIdentityTokenCallback(credential)}
        mongo_uri = f"mongodb+srv://{cluster_name}.global.mongocluster.cosmos.azure.com/"
        self._client = MongoClient(
            mongo_uri,
            connectTimeoutMS=120000,
            tls=True,
            retryWrites=True,
            authMechanism="MONGODB-OIDC",
            authMechanismProperties=auth_properties,
            tz_aware=True,
        )
        self.database = self._client[database_name]
        self.collection = self.database[collection_name]
        address = next(iter(self._client.nodes), (None, None))
        self.cluster_host = address[0] or cluster_name

    def upsert_document(self, document: dict, query: Mapping[str, object]) -> None:
        self.collection.update_one(query, {"$set": document}, upsert=True)


async def upsert_documents(
    manager: ManagerProtocol,
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
    connection_string = os.getenv("AZURE_COSMOS_CONNECTION_STRING")
    manager: ManagerProtocol
    if connection_string:
        if "AccountEndpoint=" in connection_string:
            logger.warning(
                "Provided connection string targets the SQL API; falling back to managed identity authentication."
            )
            manager = _ManagedIdentityManager(
                cluster_name=os.getenv("AZURE_COSMOS_CLUSTER_NAME", ""),
                database_name=task.database,
                collection_name=task.collection,
            )
        else:
            try:
                manager = _ConnectionStringManager(
                    connection_string=connection_string,
                    database_name=task.database,
                    collection_name=task.collection,
                )
            except InvalidURI as exc:
                logger.warning(
                    "Invalid Cosmos Mongo connection string detected; falling back to managed identity. error=%s",
                    exc,
                )
                manager = _ManagedIdentityManager(
                    cluster_name=os.getenv("AZURE_COSMOS_CLUSTER_NAME", ""),
                    database_name=task.database,
                    collection_name=task.collection,
                )
    else:
        try:
            manager = _ManagedIdentityManager(
                cluster_name=os.getenv("AZURE_COSMOS_CLUSTER_NAME", ""),
                database_name=task.database,
                collection_name=task.collection,
            )
        except (ValueError, CredentialUnavailableError) as exc:
            raise RuntimeError("Managed identity authentication unavailable for Cosmos seeding.") from exc
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
    if connection_string := os.getenv("AZURE_COSMOS_CONNECTION_STRING"):
        logger.info("Using connection-string authentication for Cosmos seeding.")
    else:
        logger.info("Using managed identity / AAD authentication for Cosmos seeding.")
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