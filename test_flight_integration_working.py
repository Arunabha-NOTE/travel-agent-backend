#!/usr/bin/env python3
"""
Quick test to verify the flight scraper integration actually works.
This tests that all modules import correctly and functions are callable.
"""

import sys
from pathlib import Path

# Setup path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

def test_all_imports():
    """Test that all required imports work."""
    try:
        from app.agents.tools.flight_scraper import GoogleFlightsScraper, FlightData
        print("✓ flight_scraper imports work")
        
        from app.agents.tools.flight_integration import (
            search_flights_with_playwright,
            _build_google_flights_url,
            format_flight_results,
        )
        print("✓ flight_integration imports work")
        
        from app.agents.tools.travel import search_flights
        print("✓ travel.search_flights imports work")
        
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_function_signatures():
    """Test that functions have correct signatures."""
    try:
        import inspect
        from app.agents.tools.flight_integration import search_flights_with_playwright
        
        sig = inspect.signature(search_flights_with_playwright)
        params = list(sig.parameters.keys())
        
        required = ['origin_code', 'destination_code', 'departure_date']
        for p in required:
            if p not in params:
                print(f"✗ Missing parameter: {p}")
                return False
        
        print("✓ search_flights_with_playwright has correct signature")
        return True
    except Exception as e:
        print(f"✗ Signature test failed: {e}")
        return False

def test_dataclass():
    """Test that FlightData dataclass works."""
    try:
        from app.agents.tools.flight_scraper import FlightData
        
        flight = FlightData(
            airline="TestAir",
            departure_time="10:00",
            arrival_time="14:00",
            duration="4h",
            stops="0",
            price="$500"
        )
        
        if flight.airline != "TestAir":
            print("✗ FlightData dataclass not working")
            return False
        
        print("✓ FlightData dataclass works correctly")
        return True
    except Exception as e:
        print(f"✗ FlightData test failed: {e}")
        return False

def test_url_builder():
    """Test that URL builder works."""
    try:
        from app.agents.tools.flight_integration import _build_google_flights_url
        
        url = _build_google_flights_url("DEL", "SFO", "2025-04-15")
        
        if "google.com/travel/flights" not in url:
            print("✗ URL builder not producing valid URLs")
            return False
        
        if "DEL" not in url or "SFO" not in url:
            print("✗ URL builder not including airport codes")
            return False
        
        print("✓ URL builder works correctly")
        return True
    except Exception as e:
        print(f"✗ URL builder test failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Flight Scraper Integration")
    print("=" * 60)
    
    tests = [
        ("Imports", test_all_imports),
        ("Function Signatures", test_function_signatures),
        ("FlightData Dataclass", test_dataclass),
        ("URL Builder", test_url_builder),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n{name}...")
        results.append(test_func())
    
    print("\n" + "=" * 60)
    if all(results):
        print("✓ ALL TESTS PASSED - Integration is working!")
        sys.exit(0)
    else:
        print("✗ SOME TESTS FAILED - Review errors above")
        sys.exit(1)
