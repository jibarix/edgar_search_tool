"""
Helper functions for the EDGAR Financial Tool.
"""

import time
import logging
from datetime import datetime, timedelta
import requests

# Set up logging
logger = logging.getLogger(__name__)


def retry_request(request_func, *args, max_retries=3, retry_delay=1, **kwargs):
    """
    Retry a request function with exponential backoff.
    
    Args:
        request_func: The request function to retry (e.g., requests.get)
        *args: Positional arguments for the request function
        max_retries (int): Maximum number of retry attempts
        retry_delay (int): Initial delay between retries in seconds
        **kwargs: Keyword arguments for the request function
        
    Returns:
        Response object from the request function
    
    Raises:
        requests.exceptions.RequestException: If all retries fail
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            response = request_func(*args, **kwargs)
            
            # Check if rate limited (HTTP 429)
            if response.status_code == 429:
                wait_time = int(response.headers.get('Retry-After', retry_delay * 2))
                logger.warning(f"Rate limited. Waiting {wait_time} seconds.")
                time.sleep(wait_time)
                continue
                
            # Return successful response
            return response
            
        except requests.exceptions.RequestException as e:
            last_exception = e
            
            # If this was our last attempt, raise the exception
            if attempt >= max_retries:
                logger.error(f"Request failed after {max_retries + 1} attempts: {str(e)}")
                raise
            
            # Calculate backoff time
            backoff_time = retry_delay * (2 ** attempt)
            logger.warning(f"Request attempt {attempt + 1} failed: {str(e)}. "
                          f"Retrying in {backoff_time} seconds...")
            time.sleep(backoff_time)
    
    # This should not be reached due to the raise in the last iteration
    if last_exception:
        raise last_exception
    
    # Fallback in case somehow we get here
    raise requests.exceptions.RequestException("All request attempts failed")


def get_filing_dates(period_type, num_periods):
    """
    Generate filing date ranges based on period type and number of periods.
    
    Args:
        period_type (str): 'annual' or 'quarterly'
        num_periods (int): Number of periods to cover
        
    Returns:
        list: List of date ranges as (start_date, end_date) tuples
    """
    today = datetime.now()
    date_ranges = []
    
    if period_type.lower() == 'annual':
        # For annual reports, look back by fiscal years
        # Most companies have fiscal year ending Dec 31, but we'll be more flexible
        
        # Start with a wider range to improve the chances of finding filings
        for i in range(num_periods):
            # For each period, look at a full year
            # But offset the periods by 1 year each
            end_year = today.year - i
            
            # End date is current date for most recent period, Dec 31 for others
            if i == 0:
                end_date = today
            else:
                end_date = datetime(end_year, 12, 31)
            
            # Start date is 1 year and 3 months before end date (to cover fiscal year variations)
            start_date = datetime(end_year - 1, 9, 1)
            
            date_ranges.append((start_date, end_date))
    
    elif period_type.lower() == 'quarterly':
        # For quarterly reports, be more flexible with the quarters
        for i in range(num_periods):
            # Offset by 3 months for each period
            end_date = today - timedelta(days=i*90)
            # Start date is 4 months before end date (to cover various fiscal quarters)
            start_date = end_date - timedelta(days=120)
            
            date_ranges.append((start_date, end_date))
    
    else:  # Year-to-date or other
        # Simple approach - just go back in time
        end_date = today
        for i in range(num_periods):
            if i > 0:
                end_date = date_ranges[-1][0] - timedelta(days=1)
            start_date = end_date - timedelta(days=365)
            date_ranges.append((start_date, end_date))
    
    return date_ranges


def format_financial_number(number, decimals=2):
    """
    Format a financial number with appropriate scale (K, M, B).
    
    Args:
        number (float): The number to format
        decimals (int): Number of decimal places
        
    Returns:
        str: Formatted number with scale suffix
    """
    if number is None:
        return "N/A"
        
    abs_number = abs(number)
    
    if abs_number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.{decimals}f}B"
    elif abs_number >= 1_000_000:
        return f"{number / 1_000_000:.{decimals}f}M"
    elif abs_number >= 1_000:
        return f"{number / 1_000:.{decimals}f}K"
    else:
        return f"{number:.{decimals}f}"


def get_fiscal_period_focus(filing_date):
    """
    Determine the likely fiscal period focus based on a filing date.
    
    Args:
        filing_date (datetime): The filing date
        
    Returns:
        str: Fiscal period focus (e.g., 'Q1', 'Q2', 'Q3', 'FY')
    """
    month = filing_date.month
    
    if 1 <= month <= 3:
        return "Q1"
    elif 4 <= month <= 6:
        return "Q2"
    elif 7 <= month <= 9:
        return "Q3"
    else:  # 10 <= month <= 12
        return "FY"


def parse_date(date_str):
    """
    Parse a date string into a datetime object.
    
    Args:
        date_str (str): Date string in various formats
        
    Returns:
        datetime: Parsed datetime object or None if parsing fails
    """
    if not date_str:
        return None
        
    date_formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y%m%d"
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None