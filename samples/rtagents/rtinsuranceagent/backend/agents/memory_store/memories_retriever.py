# vector_manager.py
# -------------------------------------------------------
import datetime
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from bson import ObjectId  # if you need auto _id
from pymongo.errors import DuplicateKeyError, PyMongoError

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger("vector_cosmosdb_mongo")


class VectorCosmosDBMongoManager(CosmosDBMongoCoreManager):
    """
    Child class that adds:
    • ensure_index_from_yaml   – DiskANN + helper indexes
    • upsert_memory            – embed & upsert
    • semantic_search          – parameter-driven retrieval
    """

    def ensure_index_from_yaml(
        self, yaml_path: str | Path = "vector_index.yaml"
    ) -> bool:
        try:
            cfg = yaml.safe_load(Path(yaml_path).read_text())["index"]
            emb = cfg["emb_field"]

            diskann = {
                "name": cfg["name"],
                "key": {emb: "cosmosSearch"},
                "cosmosSearchOptions": {
                    "kind": "vector-diskann",
                    "dimensions": cfg["max_dim"],
                    "similarity": cfg["similarity"],
                    "maxDegree": cfg["maxDegree"],
                    "lBuild": cfg["lBuild"],
                },
            }

            helpers = []
            for h in cfg.get("helper_indexes", []):
                idx = {"name": h["name"], "key": h["key"]}
                if h.get("unique"):
                    idx["unique"] = True
                helpers.append(idx)

            self.database.command(
                {"createIndexes": self.collection.name, "indexes": [diskann, *helpers]}
            )
            logger.info("✅ Vector indexes ensured from YAML.")
            return True

        except PyMongoError as e:
            if getattr(e, "code", None) == 85:  # IndexOptionsConflict
                logger.warning("⚠️  Helper index already exists—skipped.")
                return True
            logger.error(f"Index creation failed: {e}")
            return False
        except Exception as e:
            logger.error(f"YAML load/parse error: {e}")
            return False

    async def upsert_memory(
        self,
        mem: Dict[str, Any],
        aoai_client,
        *,
        emb_field: str = "memoryVector",
        model: str = "text-embedding-3-small",
        max_dim: int = 1536,
    ) -> Optional[Any]:
        if "user_id" not in mem or "summary" not in mem:
            logger.error("Memory must include 'user_id' and 'summary'.")
            return None

        mem.setdefault("memory_id", uuid.uuid4().hex)
        mem.setdefault(
            "timestamp",
            datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )

        if emb_field not in mem:
            try:
                resp = await aoai_client.embeddings.create(
                    input=mem["summary"], model=model
                )
                vec = resp.data[0].embedding
                if len(vec) != max_dim:
                    raise ValueError(
                        f"Embedding dimension mismatch ({len(vec)} vs {max_dim})"
                    )
                mem[emb_field] = vec
            except Exception as e:
                logger.error(f"Embedding failed: {e}")
                return None

        query = {"user_id": mem["user_id"], "memory_id": mem["memory_id"]}
        return self.upsert_document(mem, query)

    async def semantic_search(
        self,
        *,
        query_text: str,
        user_id: str,
        aoai_client,
        emb_field: str = "memoryVector",
        top_k: int = 3,
        include_summary: bool = True,
        include_intent: bool = True,
        include_sentiment: bool = True,
        include_timestamp: bool = True,
        include_score: bool = True,
        sort_by_score: bool = True,
        sort_by_timestamp: bool = True,
        score_desc: bool = True,
        timestamp_desc: bool = True,
        model: str = "text-embedding-3-small",
    ) -> List[Dict[str, Any]]:
        try:
            emb_resp = aoai_client.embeddings(input=query_text, model=model)
            q_vec = emb_resp.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []

        proj = {"_id": 0}
        if include_summary:
            proj["summary"] = 1
        if include_intent:
            proj["intent"] = 1
        if include_sentiment:
            proj["sentiment"] = 1
        if include_timestamp:
            proj["timestamp"] = 1
        if include_score:
            proj["score"] = {"$meta": "searchScore"}

        sort = {}
        if sort_by_score and include_score:
            sort["score"] = -1 if score_desc else 1
        if sort_by_timestamp and include_timestamp:
            sort["timestamp"] = -1 if timestamp_desc else 1

        pipeline = [
            {
                "$search": {
                    "cosmosSearch": {
                        "path": emb_field,
                        "vector": q_vec,
                        "k": top_k,
                        "filter": {"user_id": {"$eq": user_id}},
                    }
                }
            },
            {"$project": proj},
        ]
        if sort:
            pipeline.append({"$sort": sort})

        try:
            results = list(self.collection.aggregate(pipeline))
            logger.info(f"Vector search returned {len(results)} docs.")
            return results
        except PyMongoError as e:
            logger.error(f"Vector search failed: {e}")
            return []
