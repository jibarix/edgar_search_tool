"""
Filing retrieval functionality for accessing and downloading EDGAR filings.
"""

import os
import json
import logging
import time
import requests
from datetime import datetime

from config.constants import (
    SEC_BASE_URL, EDGAR_BASE_URL, SUBMISSIONS_URL, HTTP_HEADERS, ERROR_MESSAGES
)
from config.settings import (
    API_REQUEST_TIMEOUT, API_RETRY_COUNT, API_RETRY_DELAY, 
    RATE_LIMIT_REQUESTS_PER_SECOND, DEFAULT_OUTPUT_DIR
)
from utils.cache import Cache
from utils.helpers import retry_request, get_filing_dates, parse_date
from utils.validators import is_valid_cik, is_valid_filing_type

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize cache for filing data
filing_cache = Cache("filing_data")


class FilingRetrieval:
    """
    Class for retrieving SEC EDGAR filings.
    """
    
    def __init__(self):
        """Initialize the filing retrieval object."""
        self.last_request_time = 0
        
    def _respect_rate_limit(self):
        """
        Ensure we respect SEC's rate limiting guidelines.
        """
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        # Calculate sleep time needed to respect rate limit
        sleep_time = max(0, (1.0 / RATE_LIMIT_REQUESTS_PER_SECOND) - time_since_last_request)
        
        if sleep_time > 0:
            time.sleep(sleep_time)
            
        self.last_request_time = time.time()
    
    def get_company_submissions(self, cik):
        """
        Get company submissions data from SEC.
        
        Args:
            cik (str): The company CIK
            
        Returns:
            dict: Company submissions data
        """
        if not is_valid_cik(cik):
            logger.error(ERROR_MESSAGES["INVALID_CIK"])
            return None
        
        # Format CIK for API
        formatted_cik = str(cik).zfill(10)
        
        # Check cache first
        cache_key = f"submissions_{formatted_cik}"
        cached_data = filing_cache.get(cache_key)
        if cached_data:
            return cached_data
        
        # If not in cache, fetch from SEC
        url = SUBMISSIONS_URL.format(cik=formatted_cik)
        
        try:
            self._respect_rate_limit()
            response = retry_request(
                requests.get,
                url,
                headers=HTTP_HEADERS,
                timeout=API_REQUEST_TIMEOUT,
                max_retries=API_RETRY_COUNT,
                retry_delay=API_RETRY_DELAY
            )
            response.raise_for_status()
            
            submissions_data = response.json()
            
            # Cache the data
            filing_cache.set(cache_key, submissions_data)
            
            return submissions_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching company submissions: {e}")
            return None
    
    def get_filing_metadata(self, cik, filing_type="10-K", start_date=None, end_date=None, limit=10):
        """
        Get metadata for company filings.
        
        Args:
            cik (str): The company CIK
            filing_type (str): Type of filing to retrieve
            start_date (datetime): Start date for filings
            end_date (datetime): End date for filings
            limit (int): Maximum number of filings to retrieve
            
        Returns:
            list: List of filing metadata
        """
        if not is_valid_cik(cik):
            logger.error(ERROR_MESSAGES["INVALID_CIK"])
            return []
            
        if not is_valid_filing_type(filing_type):
            logger.warning(f"Unsupported filing type: {filing_type}")
            # Continue anyway as SEC may have filing types we don't list
        
        # Format CIK for API
        formatted_cik = str(cik).zfill(10)
        
        # Get company submissions
        submissions = self.get_company_submissions(formatted_cik)
        if not submissions:
            return []
        
        # Get recent filings by type
        filings = []
        recent_filings = submissions.get("filings", {}).get("recent", {})
        
        if not recent_filings:
            logger.warning(f"No recent filings found for CIK {cik}")
            return []
        
        # Prepare filing data
        accession_numbers = recent_filings.get("accessionNumber", [])
        form_types = recent_filings.get("form", [])
        filing_dates = recent_filings.get("filingDate", [])
        descriptions = recent_filings.get("primaryDocument", [])
        urls = recent_filings.get("primaryDocumentUrl", [])
        reporting_dates = recent_filings.get("reportDate", [])
        
        # Iterate through filings
        for i in range(min(len(accession_numbers), limit)):
            form = form_types[i] if i < len(form_types) else ""
            
            # Skip if not the requested filing type
            if filing_type.upper() != "ALL" and form.upper() != filing_type.upper():
                continue
            
            # Parse filing date
            filing_date_str = filing_dates[i] if i < len(filing_dates) else ""
            filing_date = parse_date(filing_date_str)
            
            # Skip if outside requested date range
            if start_date and filing_date and filing_date < start_date:
                continue
            if end_date and filing_date and filing_date > end_date:
                continue
            
            # Gather filing metadata
            filing_info = {
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else "",
                "form": form,
                "filing_date": filing_date_str,
                "description": descriptions[i] if i < len(descriptions) else "",
                "url": urls[i] if i < len(urls) else "",
                "reporting_date": reporting_dates[i] if i < len(reporting_dates) and i < len(reporting_dates) else "",
            }
            
            filings.append(filing_info)
        
        if not filings:
            logger.warning(f"No {filing_type} filings found for CIK {cik} in the specified date range")
        
        return filings
    
    def download_filing(self, url, output_dir=None):
        """
        Download a filing document from SEC.
        
        Args:
            url (str): URL of the filing document
            output_dir (str): Directory to save the file
            
        Returns:
            tuple: (file_path, file_content) if successful, (None, None) otherwise
        """
        if not url:
            logger.error("Invalid URL")
            return None, None
        
        # Check cache first
        cache_key = f"filing_content_{url.split('/')[-1]}"
        cached_content = filing_cache.get(cache_key)
        if cached_content:
            return cached_content.get("path"), cached_content.get("content")
        
        try:
            self._respect_rate_limit()
            response = retry_request(
                requests.get,
                url,
                headers=HTTP_HEADERS,
                timeout=API_REQUEST_TIMEOUT,
                max_retries=API_RETRY_COUNT,
                retry_delay=API_RETRY_DELAY
            )
            response.raise_for_status()
            
            file_content = response.text
            file_name = url.split('/')[-1]
            
            # Determine output directory
            if not output_dir:
                output_dir = os.path.join(DEFAULT_OUTPUT_DIR, "filings")
            
            os.makedirs(output_dir, exist_ok=True)
            file_path = os.path.join(output_dir, file_name)
            
            # Save file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            # Cache the content
            filing_cache.set(cache_key, {
                "path": file_path,
                "content": file_content
            })
            
            return file_path, file_content
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading filing: {e}")
            return None, None
    
    def get_filing_by_accession(self, cik, accession_number):
        """
        Get a filing document by CIK and accession number.
        
        Args:
            cik (str): The company CIK
            accession_number (str): The filing accession number
            
        Returns:
            tuple: (file_path, file_content) if successful, (None, None) otherwise
        """
        if not is_valid_cik(cik) or not accession_number:
            logger.error("Invalid CIK or accession number")
            return None, None
        
        # Format CIK and accession number
        formatted_cik = str(cik).zfill(10)
        formatted_accession = accession_number.replace('-', '')
        
        # Construct the URL
        url = f"{SEC_BASE_URL}/Archives/edgar/data/{int(formatted_cik)}/{formatted_accession}/{accession_number}.txt"
        
        return self.download_filing(url)
    
    def get_xbrl_filing(self, cik, accession_number):
        """
        Get XBRL instance document for a filing.
        
        Args:
            cik (str): The company CIK
            accession_number (str): The filing accession number
            
        Returns:
            tuple: (file_path, file_content) if successful, (None, None) otherwise
        """
        if not is_valid_cik(cik) or not accession_number:
            logger.error("Invalid CIK or accession number")
            return None, None
        
        # Format CIK and accession number
        formatted_cik = str(cik).zfill(10)
        formatted_accession = accession_number.replace('-', '')
        
        # Check cache first
        cache_key = f"xbrl_content_{formatted_cik}_{formatted_accession}"
        cached_content = filing_cache.get(cache_key)
        if cached_content:
            return cached_content.get("path"), cached_content.get("content")
        
        # Get the main filing to find the XBRL document
        _, filing_content = self.get_filing_by_accession(cik, accession_number)
        
        if not filing_content:
            return None, None
        
        # Find the XBRL instance document in the filing
        try:
            import re
            xbrl_pattern = re.compile(r'<FILENAME>(.*\.xml)')
            match = xbrl_pattern.search(filing_content)
            
            if not match:
                logger.warning(f"No XBRL instance document found in filing {accession_number}")
                return None, None
            
            xbrl_filename = match.group(1)
            
            # Construct the URL for the XBRL document
            url = f"{SEC_BASE_URL}/Archives/edgar/data/{int(formatted_cik)}/{formatted_accession}/{xbrl_filename}"
            
            # Download the XBRL document
            file_path, file_content = self.download_filing(url)
            
            # Cache the content
            if file_path and file_content:
                filing_cache.set(cache_key, {
                    "path": file_path,
                    "content": file_content
                })
            
            return file_path, file_content
            
        except Exception as e:
            logger.error(f"Error extracting XBRL document from filing: {e}")
            return None, None