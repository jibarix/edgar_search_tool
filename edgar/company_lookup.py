"""
Company lookup functionality for finding SEC CIK numbers.
"""

import json
import re
import requests
from difflib import get_close_matches

from config.constants import COMPANY_TICKERS_URL, HTTP_HEADERS, ERROR_MESSAGES
from config.settings import API_REQUEST_TIMEOUT, API_RETRY_COUNT, API_RETRY_DELAY
from utils.cache import Cache
from utils.helpers import retry_request

# Initialize cache for company lookup
company_cache = Cache("company_lookup")


def format_cik(cik):
    """
    Format CIK to 10-digit format with leading zeros.
    
    Args:
        cik (str or int): The CIK number
        
    Returns:
        str: Formatted 10-digit CIK
    """
    return str(cik).zfill(10)


def get_company_tickers():
    """
    Retrieve the company tickers JSON file from SEC.
    
    Returns:
        dict: Company tickers data with CIK as keys
    """
    # Check cache first
    cached_data = company_cache.get("company_tickers")
    if cached_data:
        return cached_data
    
    # If not in cache, fetch from SEC
    try:
        response = retry_request(
            requests.get,
            COMPANY_TICKERS_URL,
            headers=HTTP_HEADERS,
            timeout=API_REQUEST_TIMEOUT,
            max_retries=API_RETRY_COUNT,
            retry_delay=API_RETRY_DELAY
        )
        response.raise_for_status()
        
        # Process the data
        data = response.json()
        
        # Transform data for easier lookup by company name
        companies_by_name = {}
        for _, company_info in data.items():
            cik = company_info["cik_str"]
            ticker = company_info["ticker"]
            title = company_info["title"].lower()
            
            # Create normalized company name for better matching
            normalized_title = re.sub(r'[^\w\s]', '', title)
            
            companies_by_name[normalized_title] = {
                "cik": format_cik(cik),
                "ticker": ticker,
                "name": company_info["title"]
            }
            
            # Also add by ticker for direct ticker lookups
            companies_by_name[ticker.lower()] = {
                "cik": format_cik(cik),
                "ticker": ticker,
                "name": company_info["title"]
            }
        
        # Cache the processed data
        company_cache.set("company_tickers", companies_by_name)
        
        return companies_by_name
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching company tickers: {e}")
        return {}


def search_company(query):
    """
    Search for a company by name or ticker.
    
    Args:
        query (str): Company name or ticker to search for
        
    Returns:
        list: List of matching companies with CIK, name and ticker
    """
    # Normalize the query
    query = query.lower().strip()
    normalized_query = re.sub(r'[^\w\s]', '', query)
    
    # Get company tickers data
    companies = get_company_tickers()
    
    # Check for exact match
    if query in companies:
        return [companies[query]]
    
    if normalized_query in companies:
        return [companies[normalized_query]]
    
    # Check for ticker match (case insensitive)
    ticker_matches = [
        company for name, company in companies.items()
        if company["ticker"].lower() == query
    ]
    if ticker_matches:
        return ticker_matches
    
    # If no exact match, use fuzzy matching to find similar names
    company_names = list(companies.keys())
    matches = get_close_matches(normalized_query, company_names, n=5, cutoff=0.6)
    
    # Return the matching companies
    return [companies[match] for match in matches if match in companies]


def get_cik_by_company_name(company_name):
    """
    Get a company's CIK by its name.
    
    Args:
        company_name (str): The company name to look up
        
    Returns:
        str or None: The CIK if found, None otherwise
    """
    matches = search_company(company_name)
    
    if not matches:
        print(ERROR_MESSAGES["COMPANY_NOT_FOUND"])
        return None
    
    # If only one match, return it
    if len(matches) == 1:
        return matches[0]["cik"]
    
    # If multiple matches, let the user choose
    print(f"Found {len(matches)} matches for '{company_name}':")
    for i, match in enumerate(matches, 1):
        print(f"{i}. {match['name']} (Ticker: {match['ticker']}, CIK: {match['cik']})")
    
    while True:
        try:
            choice = int(input("Enter the number of the correct company (0 to cancel): "))
            if choice == 0:
                return None
            if 1 <= choice <= len(matches):
                return matches[choice-1]["cik"]
            print("Invalid choice, please try again.")
        except ValueError:
            print("Please enter a valid number.")


if __name__ == "__main__":
    # Simple test of the module
    test_query = input("Enter a company name to search: ")
    matches = search_company(test_query)
    
    if matches:
        print(f"Found {len(matches)} matches:")
        for match in matches:
            print(f"Name: {match['name']}, Ticker: {match['ticker']}, CIK: {match['cik']}")
    else:
        print("No matches found.")