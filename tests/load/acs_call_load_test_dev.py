#!/usr/bin/env python3
"""
ACS Call Load Test - Development Configuration
==============================================

Easy-to-use development configuration for ACS call load testing.
Starts with 1 call to +8165019907, easily scalable for production.
"""

import os
import asyncio
import argparse
from pathlib import Path
from typing import List

from acs_call_load_test import AcsCallLoadTester, AcsLoadTestConfig

def get_dev_config(scale_factor: int = 1, target_phones: List[str] = None) -> AcsLoadTestConfig:
    """Get development configuration with optional scaling."""
    
    base_calls = 1
    base_concurrent = 1
    base_duration = 15
    
    # Use provided phone numbers or try environment variable
    if not target_phones:
        env_phone = os.getenv("ACS_TARGET_PHONE_NUMBER")
        if env_phone:
            target_phones = [env_phone]
        else:
            target_phones = []  # Must be provided
    
    return AcsLoadTestConfig(
        total_calls=base_calls * scale_factor,
        concurrent_calls=min(base_concurrent * scale_factor, 5),  # Cap at 5 concurrent
        target_phone_numbers=target_phones,
        call_duration_seconds=base_duration,
        source_phone_number=os.getenv("ACS_SOURCE_PHONE_NUMBER", ""),
        acs_connection_string=os.getenv("ACS_CONNECTION_STRING", ""),
        callback_url=os.getenv("ACS_CALLBACK_URL", "https://your-domain.com/api/v1/acs/events")
    )

def get_staging_config(target_phones: List[str] = None) -> AcsLoadTestConfig:
    """Get staging environment configuration."""
    if not target_phones:
        env_phone = os.getenv("ACS_TARGET_PHONE_NUMBER")
        if env_phone:
            target_phones = [env_phone]
        else:
            target_phones = []  # Must be provided
    
    return AcsLoadTestConfig(
        total_calls=5,
        concurrent_calls=2,
        target_phone_numbers=target_phones,
        call_duration_seconds=30,
        source_phone_number=os.getenv("ACS_SOURCE_PHONE_NUMBER", ""),
        acs_connection_string=os.getenv("ACS_CONNECTION_STRING", ""),
        callback_url=os.getenv("ACS_CALLBACK_URL", "https://your-domain.com/api/v1/acs/events")
    )

def get_production_config(target_phones: List[str] = None) -> AcsLoadTestConfig:
    """Get production load test configuration."""
    if not target_phones:
        env_phone = os.getenv("ACS_TARGET_PHONE_NUMBER")
        if env_phone:
            target_phones = [env_phone]
        else:
            target_phones = []  # Must be provided
    
    return AcsLoadTestConfig(
        total_calls=20,
        concurrent_calls=5,
        target_phone_numbers=target_phones,
        call_duration_seconds=60,
        source_phone_number=os.getenv("ACS_SOURCE_PHONE_NUMBER", ""),
        acs_connection_string=os.getenv("ACS_CONNECTION_STRING", ""),
        callback_url=os.getenv("ACS_CALLBACK_URL", "https://your-domain.com/api/v1/acs/events")
    )

async def run_acs_load_test(environment: str = "dev", scale_factor: int = 1, target_phones: List[str] = None):
    """Run ACS load test with specified environment configuration."""
    
    if not target_phones:
        print("❌ No target phone numbers provided!")
        print("   Use --target-phones to specify phone numbers")
        print("   Example: --target-phones +8165019907 +1234567890")
        return
    
    print(f"🎯 Running ACS Call Load Test - {environment.upper()} Environment")
    print(f"Target Phones: {', '.join(target_phones)}")
    print("=" * 60)
    
    # Get configuration based on environment
    if environment == "dev":
        config = get_dev_config(scale_factor, target_phones)
        print(f"📱 Development Configuration (scale factor: {scale_factor})")
    elif environment == "staging":
        config = get_staging_config(target_phones)
        print(f"🏗️  Staging Configuration")
    elif environment == "prod":
        config = get_production_config(target_phones)
        print(f"🚀 Production Configuration")
    else:
        raise ValueError(f"Unknown environment: {environment}")
    
    print(f"   Total Calls: {config.total_calls}")
    print(f"   Concurrent: {config.concurrent_calls}")
    print(f"   Duration: {config.call_duration_seconds}s")
    print(f"   Source: {config.source_phone_number}")
    print()
    
    # Validate environment variables
    required_vars = ["ACS_SOURCE_PHONE_NUMBER", "ACS_CONNECTION_STRING"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   {var}")
        print("\nPlease set these environment variables:")
        print("   export ACS_SOURCE_PHONE_NUMBER='+1234567890'")
        print("   export ACS_CONNECTION_STRING='endpoint=https://...'")
        print("   export ACS_CALLBACK_URL='https://your-domain.com/api/v1/acs/events'")
        return
    
    # Run the test
    tester = AcsCallLoadTester(config)
    results = await tester.run_load_test()
    
    # Save results with environment and timestamp
    import time
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    results_dir = Path("tests/load/results")
    results_dir.mkdir(exist_ok=True)
    
    results_file = results_dir / f"acs_call_load_test_{environment}_{timestamp}.json"
    
    import json
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n💾 Results saved to: {results_file}")
    
    # Show scaling suggestions
    if environment == "dev" and results.get("success_rate_percent", 0) > 80:
        phones_str = " ".join(target_phones)
        print(f"\n🚀 Scaling Suggestions (success rate: {results.get('success_rate_percent', 0):.1f}%):")
        print(f"   python tests/load/acs_call_load_test_dev.py --environment staging --target-phones {phones_str}")
        print(f"   python tests/load/acs_call_load_test_dev.py --environment dev --scale 3 --target-phones {phones_str}")
        print(f"   python tests/load/acs_call_load_test_dev.py --environment prod --target-phones {phones_str}")

def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(description="ACS Call Load Testing - Development Ready")
    
    parser.add_argument(
        "--environment", 
        choices=["dev", "staging", "prod"], 
        default="dev",
        help="Test environment configuration (default: dev)"
    )
    
    parser.add_argument(
        "--scale", 
        type=int, 
        default=1,
        help="Scale factor for development testing (default: 1)"
    )
    
    parser.add_argument(
        "--target-phones", 
        nargs="+", 
        required=True,
        help="Target phone numbers to call (e.g., --target-phones +8165019907 +1234567890)"
    )
    
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="Show configuration without running tests"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print(f"🔍 DRY RUN - {args.environment.upper()} Configuration:")
        if args.environment == "dev":
            config = get_dev_config(args.scale, args.target_phones)
        elif args.environment == "staging":
            config = get_staging_config(args.target_phones)
        else:
            config = get_production_config(args.target_phones)
            
        print(f"   Target Phones: {', '.join(config.target_phone_numbers)}")
        print(f"   Total Calls: {config.total_calls}")
        print(f"   Concurrent: {config.concurrent_calls}")
        print(f"   Duration: {config.call_duration_seconds}s")
        return
    
    # Warning for non-dev environments
    if args.environment != "dev":
        print(f"⚠️  WARNING: Running {args.environment.upper()} configuration!")
        print("⚠️  This will make multiple phone calls and incur charges!")
        print("⚠️  Press Ctrl+C to cancel, or wait 5 seconds to continue...")
        
        try:
            import time
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n🛑 Test cancelled by user")
            return
    
    # Run the test
    asyncio.run(run_acs_load_test(args.environment, args.scale, args.target_phones))

if __name__ == "__main__":
    main()
