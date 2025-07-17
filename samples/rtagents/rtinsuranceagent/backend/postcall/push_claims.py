from pathlib import Path
from typing import Any, Dict, Optional

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger("cosmos_claims")


def persist_claim_record(
    cosmos: CosmosDBMongoCoreManager,
    claim_dict: Dict[str, Any],
    report_path: Path,
) -> None:
    """
    Upsert a single FNOL claim into Cosmos DB (Mongo API).
    Uses claim_id as the document _id so re-submits overwrite.
    """
    doc = {**claim_dict, "_id": claim_dict["claim_id"], "report_path": str(report_path)}
    try:
        cosmos.upsert_document(document=doc, query={"_id": doc["_id"]})
        logger.info("☁️  Claim %s persisted to CosmosDB", doc["_id"])
    except Exception as e:  # pragma: no cover
        logger.error("Failed persisting claim %s: %s", doc["_id"], e, exc_info=True)


def fetch_claim_record(
    cosmos: CosmosDBMongoCoreManager,
    claim_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Retrieve a claim (and report path) by claim_id.
    Returns the stored document or None if not found.
    """
    try:
        doc = cosmos.read_document({"_id": claim_id})
        if doc:
            logger.info("📥  Retrieved claim %s from CosmosDB", claim_id)
        return doc
    except Exception as e:  # pragma: no cover
        logger.error("Failed to fetch claim %s: %s", claim_id, e, exc_info=True)
        return None
