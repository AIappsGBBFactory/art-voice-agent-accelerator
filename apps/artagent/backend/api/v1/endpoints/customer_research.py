"""
Customer Research Endpoints
============================

REST endpoints for researching customers and auto-building voice-agent scenarios.

Endpoints:
    POST /api/v1/customer-research/research  - Research a company and get use-case proposals
    POST /api/v1/customer-research/build     - Build a selected use case into the session
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from utils.ml_logging import get_logger

logger = get_logger("v1.customer_research")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════


class ResearchRequest(BaseModel):
    """Request to research a company."""

    company_name: str = Field(
        ..., min_length=1, max_length=200, description="Company or brand name to research"
    )
    industry: str = Field(
        default="", max_length=100, description="Optional industry hint to guide research"
    )
    use_case_hint: str = Field(
        default="", max_length=500, description="Optional specific use case to generate"
    )


class ResearchResponse(BaseModel):
    """Response containing company info and use-case proposals."""

    status: str
    company_name: str
    company_summary: str
    industry: str
    use_cases: list[dict[str, Any]]
    response_time_ms: float


class BuildRequest(BaseModel):
    """Request to build a selected use case into a session."""

    session_id: str = Field(..., min_length=1, description="Target session ID")
    use_case: dict[str, Any] = Field(..., description="The full UseCaseSpec to build")


class BuildResponse(BaseModel):
    """Response after building a use case."""

    status: str
    session_id: str
    scenario_name: str
    agents_created: list[str]
    tools_created: list[str]
    response_time_ms: float


class ImportRequest(BaseModel):
    """Request to import a scenario from YAML content."""

    session_id: str = Field(..., min_length=1, description="Target session ID")
    yaml_content: str = Field(..., min_length=1, description="Raw YAML content to import")


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/research",
    response_model=ResearchResponse,
    summary="Research a Company",
    description="Research a company and generate voice-agent use-case proposals.",
    tags=["Customer Research"],
)
async def research_company(request: ResearchRequest) -> ResearchResponse:
    """
    Research a company using Azure OpenAI and return use-case proposals.

    Each use case includes complete specs for agents, tools, handoffs, and
    mock data — ready to be built into a live session.
    """
    start = time.time()

    try:
        from apps.artagent.backend.src.customer_research.service import research_customer

        result = await research_customer(
            request.company_name,
            industry=request.industry,
            use_case_hint=request.use_case_hint,
        )

        return ResearchResponse(
            status="success",
            company_name=result.company_name,
            company_summary=result.company_summary,
            industry=result.industry,
            use_cases=[uc.model_dump() for uc in result.use_cases],
            response_time_ms=round((time.time() - start) * 1000, 2),
        )

    except RuntimeError as exc:
        logger.error("Research failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected error in research: %s", exc)
        raise HTTPException(status_code=500, detail=f"Research failed: {exc}") from exc


@router.post(
    "/build",
    response_model=BuildResponse,
    summary="Build Use Case",
    description="Build a selected use case into agents, tools, and scenario for a session.",
    tags=["Customer Research"],
)
async def build_use_case_endpoint(request: BuildRequest) -> BuildResponse:
    """
    Build a use case into the target session.

    Creates mock tools, session agents, and a session scenario. The scenario
    is automatically set as active for the session.
    """
    start = time.time()

    try:
        from apps.artagent.backend.src.customer_research.builder import build_use_case
        from apps.artagent.backend.src.customer_research.models import UseCaseSpec

        use_case = UseCaseSpec.model_validate(request.use_case)
        result = await build_use_case(request.session_id, use_case)

        return BuildResponse(
            status=result.status,
            session_id=result.session_id,
            scenario_name=result.scenario_name,
            agents_created=result.agents_created,
            tools_created=result.tools_created,
            response_time_ms=round((time.time() - start) * 1000, 2),
        )

    except ValueError as exc:
        logger.error("Invalid use case spec: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid use case: {exc}") from exc
    except Exception as exc:
        logger.error("Build failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Build failed: {exc}") from exc


@router.post(
    "/import",
    response_model=BuildResponse,
    summary="Import Scenario from YAML",
    description="Parse a YAML scenario definition and build it into a session.",
    tags=["Customer Research"],
)
async def import_scenario_endpoint(request: ImportRequest) -> BuildResponse:
    """
    Import a scenario from YAML content.

    Parses the YAML into a UseCaseSpec and builds it exactly like the build endpoint.
    """
    start = time.time()

    try:
        import yaml as pyyaml

        from apps.artagent.backend.src.customer_research.builder import build_use_case
        from apps.artagent.backend.src.customer_research.models import UseCaseSpec

        raw = pyyaml.safe_load(request.yaml_content)
        if not isinstance(raw, dict):
            raise ValueError("YAML must parse to a mapping/object")

        use_case = UseCaseSpec.model_validate(raw)
        result = await build_use_case(request.session_id, use_case)

        return BuildResponse(
            status=result.status,
            session_id=result.session_id,
            scenario_name=result.scenario_name,
            agents_created=result.agents_created,
            tools_created=result.tools_created,
            response_time_ms=round((time.time() - start) * 1000, 2),
        )

    except pyyaml.YAMLError as exc:
        logger.error("YAML parse error: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc
    except ValueError as exc:
        logger.error("Invalid scenario spec: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid scenario: {exc}") from exc
    except Exception as exc:
        logger.error("Import failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc
