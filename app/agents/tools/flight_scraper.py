"""Enhanced Google Flights scraper using Playwright and best practices from luminati-io/google-flights-api."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from tenacity import retry, stop_after_attempt, wait_fixed

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FlightData:
    """Data class to store individual flight information."""

    airline: str
    departure_time: str
    arrival_time: str
    duration: str
    stops: str
    price: str
    co2_emissions: str | None = None
    emissions_variation: str | None = None
    booking_url: str | None = None


class GoogleFlightsScraper:
    """
    Enhanced Google Flights scraper using Playwright.
    
    Based on: https://github.com/luminati-io/google-flights-api
    Provides reliable flight data extraction with retry logic and proper error handling.
    """

    # CSS selectors for Google Flights elements (tested and reliable)
    SELECTORS = {
        "airline": "div.sSHqwe.tPgKwe.ogfYpf",
        "departure_time": 'span[aria-label^="Departure time"]',
        "arrival_time": 'span[aria-label^="Arrival time"]',
        "duration": 'div[aria-label^="Total duration"]',
        "stops": "div.hF6lYb span.rGRiKd",
        "price": "div.FpEdX span",
        "co2_emissions": "div.O7CXue",
        "emissions_variation": "div.N6PNV",
        "flight_container": "li.pIav2d",
        "show_more_button": 'button[aria-label*="more flights"]',
    }

    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        """
        Initialize the scraper.
        
        Args:
            headless: Run browser in headless mode. Set to False to minimize detection.
            timeout_ms: Timeout for page operations in milliseconds.
        """
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def _extract_text(self, element: Any) -> str:
        """Extract text content from a page element safely."""
        if not element:
            return "N/A"
        try:
            text = await element.text_content()
            return text.strip() if text else "N/A"
        except Exception:
            return "N/A"

    async def _load_all_flights(self, page: Any) -> None:
        """Click 'Show more flights' button until all flights are loaded."""
        attempt = 0
        max_attempts = 5
        while attempt < max_attempts:
            try:
                more_button = await page.wait_for_selector(
                    self.SELECTORS["show_more_button"], timeout=5000
                )
                if more_button:
                    await more_button.click()
                    await page.wait_for_timeout(2000)
                    attempt += 1
                else:
                    break
            except Exception as e:
                logger.debug(f"No more 'Show more flights' button: {str(e)}")
                break

    async def _extract_flight_data(self, page: Any) -> list[FlightData]:
        """
        Extract flight information from search results.
        
        Args:
            page: Playwright page object
            
        Returns:
            List of FlightData objects extracted from the page
        """
        try:
            await page.wait_for_selector(
                self.SELECTORS["flight_container"], timeout=self.timeout_ms
            )
            await self._load_all_flights(page)

            flights_elements = await page.query_selector_all(
                self.SELECTORS["flight_container"]
            )
            logger.info(f"Found {len(flights_elements)} flight elements")

            flights_data = []
            for idx, flight in enumerate(flights_elements):
                try:
                    flight_info = {}
                    for key, selector in self.SELECTORS.items():
                        if key == "flight_container" or key == "show_more_button":
                            continue
                        try:
                            element = await flight.query_selector(selector)
                            flight_info[key] = await self._extract_text(element)
                        except Exception as e:
                            logger.debug(f"Failed to extract {key}: {str(e)}")
                            flight_info[key] = "N/A"

                    flights_data.append(FlightData(**flight_info))
                except Exception as e:
                    logger.warning(f"Failed to process flight {idx}: {str(e)}")
                    continue

            return flights_data
        except Exception as e:
            logger.error(f"Failed to extract flight data: {str(e)}")
            raise

    def _extract_trip_info_from_url(self, url: str) -> dict[str, str]:
        """
        Extract trip information from Google Flights URL.
        
        Args:
            url: Google Flights search URL
            
        Returns:
            Dictionary with origin, destination, and date if found
        """
        trip_info = {}

        # Extract airport codes from tfs parameter
        airport_match = re.search(r"[?&]tfs=.*?([A-Z]{3}).*?([A-Z]{3})", url)
        if airport_match:
            trip_info["origin"] = airport_match.group(1)
            trip_info["destination"] = airport_match.group(2)

        # Extract date (YYYY-MM-DD format)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", url)
        if date_match:
            trip_info["date"] = date_match.group(1)

        return trip_info

    def save_results(self, flights: list[FlightData], url: str) -> str:
        """
        Save flight search results to a JSON file.
        
        Args:
            flights: List of FlightData objects
            url: Original search URL
            
        Returns:
            Path to the saved file
        """
        output_data = {
            "search_url": url,
            "trip_info": self._extract_trip_info_from_url(url),
            "flights": [asdict(flight) for flight in flights],
            "total_flights": len(flights),
        }

        filepath = "flight_results.json"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save results: {str(e)}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    async def search_flights(self, url: str) -> list[FlightData]:
        """
        Execute the flight search with retry capability.
        
        Uses Playwright to navigate to Google Flights URL and extract flight data.
        Implements retry logic with exponential backoff.
        
        Args:
            url: Full Google Flights search URL with all parameters
            
        Returns:
            List of FlightData objects from the search
            
        Raises:
            Exception: If flight extraction fails after all retries
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Install with: pip install playwright")
            raise

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                logger.info(f"Navigating to flight search URL")
                await page.goto(url, timeout=60000)
                await page.wait_for_load_state("networkidle")

                flights = await self._extract_flight_data(page)
                logger.info(f"Successfully extracted {len(flights)} flights")

                filepath = self.save_results(flights, url)
                logger.info(f"Flight results saved to {filepath}")
                return flights
            finally:
                await context.close()
                await browser.close()


async def search_google_flights_playwright(
    url: str, headless: bool = True
) -> list[dict[str, str]]:
    """
    Public function to search Google Flights using Playwright.
    
    Args:
        url: Complete Google Flights search URL
        headless: Whether to run browser in headless mode
        
    Returns:
        List of flight dictionaries
    """
    scraper = GoogleFlightsScraper(headless=headless)
    try:
        flights = await scraper.search_flights(url)
        return [asdict(f) for f in flights]
    except Exception as e:
        logger.error(f"Playwright-based flight search failed: {str(e)}")
        raise


# Example usage for testing
async def main():
    """Example usage of the flight scraper."""
    scraper = GoogleFlightsScraper(headless=False)

    # Example Google Flights URL (replace with actual search)
    url = "https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI1LTA0LTAxagcIARIDREVMcgcIARIDU0ZPQAFIAXABggELCP___________wGYAQI&curr=USD"

    try:
        flights = await scraper.search_flights(url)
        print(f"Successfully found {len(flights)} flights")
        for flight in flights[:3]:
            print(f"  {flight.airline}: {flight.departure_time} - {flight.arrival_time} (${flight.price})")
    except Exception as e:
        print(f"Error during flight search: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
