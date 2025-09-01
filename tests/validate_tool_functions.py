#!/usr/bin/env python3
"""
Comprehensive Tool Function & Schema Validation Script

This script validates that all tool functions are properly defined and
match their corresponding schemas in the tool registry.
"""

import sys
import inspect
from typing import Dict, Any, List
import importlib.util

# Add paths
sys.path.append("apps/rtagent/backend/src")
sys.path.append("src")


def load_module_from_path(module_name: str, file_path: str):
    """Load a module from a file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyze_function_signature(func):
    """Analyze function signature and return parameter details."""
    sig = inspect.signature(func)
    return {
        "name": func.__name__,
        "parameters": list(sig.parameters.keys()),
        "has_args_param": "args" in sig.parameters,
        "is_async": inspect.iscoroutinefunction(func),
        "docstring": func.__doc__ or "No docstring",
    }


def validate_tool_registry():
    """Validate tool registry consistency."""
    print("=" * 70)
    print("🔍 TOOL FUNCTION & SCHEMA VALIDATION ANALYSIS")
    print("=" * 70)

    try:
        # Import schemas
        from agents.tool_store.schemas import (
            record_fnol_schema,
            authenticate_caller_schema,
            escalate_emergency_schema,
            handoff_general_schema,
            handoff_claim_schema,
            find_information_schema,
            escalate_human_schema,
        )

        # Import tool registry
        from agents.tool_store.tool_registry import (
            function_mapping,
            available_tools,
            TOOL_REGISTRY,
        )

        print("✅ Successfully imported all schemas and tool registry")

    except Exception as e:
        print(f"❌ Import error: {e}")
        return False

    # Schema definitions
    schemas = {
        "record_fnol": record_fnol_schema,
        "authenticate_caller": authenticate_caller_schema,
        "escalate_emergency": escalate_emergency_schema,
        "handoff_general_agent": handoff_general_schema,
        "handoff_claim_agent": handoff_claim_schema,
        "find_information_for_policy": find_information_schema,
        "escalate_human": escalate_human_schema,
    }

    print(f"\n📋 Found {len(schemas)} schema definitions")
    print(f"📋 Found {len(function_mapping)} functions in mapping")
    print(f"📋 Found {len(available_tools)} tools in available_tools")
    print(f"📋 Found {len(TOOL_REGISTRY)} tools in TOOL_REGISTRY")

    all_valid = True

    print("\n" + "=" * 70)
    print("🔍 DETAILED FUNCTION ANALYSIS")
    print("=" * 70)

    for func_name, func in function_mapping.items():
        print(f"\n📝 Function: {func_name}")
        print("-" * 50)

        # Analyze function signature
        func_info = analyze_function_signature(func)
        print(f"   ✓ Async function: {func_info['is_async']}")
        print(f"   ✓ Parameters: {func_info['parameters']}")
        print(f"   ✓ Uses args pattern: {func_info['has_args_param']}")

        # Check if schema exists
        if func_name in schemas:
            schema = schemas[func_name]
            print(f"   ✅ Schema found: {schema['name']}")

            # Validate schema structure
            required_schema_keys = ["name", "description", "parameters"]
            missing_keys = [key for key in required_schema_keys if key not in schema]
            if missing_keys:
                print(f"   ❌ Schema missing keys: {missing_keys}")
                all_valid = False
            else:
                print(f"   ✅ Schema structure valid")

            # Check parameter structure
            if "parameters" in schema:
                params = schema["parameters"]
                if "properties" in params:
                    schema_props = list(params["properties"].keys())
                    print(f"   ✓ Schema parameters: {schema_props}")

                    # Check required fields
                    if "required" in params:
                        required_fields = params["required"]
                        print(f"   ✓ Required fields: {required_fields}")
                    else:
                        print(f"   ⚠️  No required fields specified")
                else:
                    print(f"   ❌ Schema missing 'properties'")
                    all_valid = False
        else:
            print(f"   ❌ No schema found for {func_name}")
            all_valid = False

        # Check if function is in available_tools
        tool_found = any(
            tool["function"]["name"] == func_name for tool in available_tools
        )
        if tool_found:
            print(f"   ✅ Function in available_tools")
        else:
            print(f"   ❌ Function NOT in available_tools")
            all_valid = False

        # Check if function is in TOOL_REGISTRY
        if func_name in TOOL_REGISTRY:
            print(f"   ✅ Function in TOOL_REGISTRY")
        else:
            print(f"   ❌ Function NOT in TOOL_REGISTRY")
            all_valid = False

    print("\n" + "=" * 70)
    print("🔍 SCHEMA CONSISTENCY CHECK")
    print("=" * 70)

    # Check for orphaned schemas
    orphaned_schemas = [
        name for name in schemas.keys() if name not in function_mapping.keys()
    ]
    if orphaned_schemas:
        print(f"⚠️  Orphaned schemas (no function): {orphaned_schemas}")
    else:
        print("✅ No orphaned schemas found")

    # Check for missing schemas
    missing_schemas = [
        name for name in function_mapping.keys() if name not in schemas.keys()
    ]
    if missing_schemas:
        print(f"❌ Functions missing schemas: {missing_schemas}")
        all_valid = False
    else:
        print("✅ All functions have schemas")

    print("\n" + "=" * 70)
    print("🔍 REGISTRY CONSISTENCY CHECK")
    print("=" * 70)

    # Check available_tools consistency
    available_tool_names = [tool["function"]["name"] for tool in available_tools]
    print(f"Available tools: {available_tool_names}")

    # Check TOOL_REGISTRY consistency
    registry_names = list(TOOL_REGISTRY.keys())
    print(f"Registry tools: {registry_names}")

    # Cross-check consistency
    if set(available_tool_names) == set(registry_names):
        print("✅ available_tools and TOOL_REGISTRY are consistent")
    else:
        print("❌ available_tools and TOOL_REGISTRY are inconsistent")
        all_valid = False

    if set(function_mapping.keys()) == set(available_tool_names):
        print("✅ function_mapping and available_tools are consistent")
    else:
        print("❌ function_mapping and available_tools are inconsistent")
        print(f"   function_mapping: {set(function_mapping.keys())}")
        print(f"   available_tools: {set(available_tool_names)}")
        all_valid = False

    print("\n" + "=" * 70)
    if all_valid:
        print("🎯 RESULT: ALL TOOL FUNCTIONS AND SCHEMAS ARE WELL-DEFINED! ✅")
        print("✅ All functions have proper schemas")
        print("✅ All schemas are well-structured")
        print("✅ All registries are consistent")
        print("✅ Ready for production deployment")
    else:
        print("❌ RESULT: ISSUES FOUND - REQUIRES ATTENTION")
        print("⚠️  Some functions or schemas need fixes")
    print("=" * 70)

    return all_valid


if __name__ == "__main__":
    validate_tool_registry()
