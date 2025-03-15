import os
import json
import logging
import time
import threading
import requests
from datetime import datetime
from lxml import etree
from jsonschema import validate, ValidationError

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

# Initialize cache for filing data with an expiry (e.g., 1 hour)
filing_cache = Cache("filing_data", expiry=3600)

# Optional: Define a basic JSON schema for validating EDGAR submissions.
# (This is a simplified example; you might want to expand it based on actual response structure.)
EDGAR_SUBMISSIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "filings": {
            "type": "object",
            "properties": {
                "recent": {"type": "object"},
                "files": {"type": "array"}
            },
            "required": ["recent", "files"]
        }
    },
    "required": ["filings"]
}


class FilingRetrieval:
    """
    Class for retrieving SEC EDGAR filings.
    """
    
    def __init__(self):
        """Initialize the filing retrieval object."""
        self.last_request_time = 0
        self.rate_limit_lock = threading.Lock()
        
    def _respect_rate_limit(self):
        """
        Ensure we respect SEC's rate limiting guidelines.
        This method is thread-safe.
        """
        with self.rate_limit_lock:
            current_time = time.time()
            time_since_last_request = current_time - self.last_request_time
            sleep_time = max(0, (1.0 / RATE_LIMIT_REQUESTS_PER_SECOND) - time_since_last_request)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self.last_request_time = time.time()
    
    def validate_submissions_data(self, data):
        """
        Validate the JSON structure of EDGAR submissions data using jsonschema.
        """
        try:
            validate(instance=data, schema=EDGAR_SUBMISSIONS_SCHEMA)
        except ValidationError as e:
            logger.error(f"EDGAR submissions JSON validation error: {e}")
            return False
        return True
    
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
        
        formatted_cik = str(cik).zfill(10)
        cache_key = f"submissions_{formatted_cik}"
        cached_data = filing_cache.get(cache_key)
        if cached_data:
            return cached_data
        
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
            if not self.validate_submissions_data(submissions_data):
                return None
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
            # Continue anyway; SEC may have filing types we don't list
        
        formatted_cik = str(cik).zfill(10)
        submissions = self.get_company_submissions(formatted_cik)
        if not submissions:
            return []
        
        filings = []
        # Process recent filings first
        recent_filings = submissions.get("filings", {}).get("recent", {})
        if recent_filings:
            filings.extend(self._process_filings_data(
                recent_filings, 
                filing_type, 
                start_date, 
                end_date, 
                limit
            ))
        
        # If more filings are needed, process historical filings
        if len(filings) < limit:
            historical_filings = submissions.get("filings", {}).get("files", [])
            remaining_limit = limit - len(filings)
            for file_info in historical_filings:
                if len(filings) >= limit:
                    break
                file_url = f"{SEC_BASE_URL}{file_info.get('name')}"
                historical_data = self._get_historical_filings(file_url)
                if historical_data:
                    more_filings = self._process_filings_data(
                        historical_data, 
                        filing_type, 
                        start_date, 
                        end_date, 
                        remaining_limit
                    )
                    filings.extend(more_filings)
                    remaining_limit = limit - len(filings)
        
        if not filings:
            logger.warning(f"No {filing_type} filings found for CIK {cik} in the specified date range")
        
        return filings
    
    def _get_historical_filings(self, file_url):
        """
        Get historical filings data from SEC.
        
        Args:
            file_url (str): URL to the historical filings index
            
        Returns:
            dict: Historical filings data or None on error
        """
        cache_key = f"historical_{file_url}"
        cached_data = filing_cache.get(cache_key)
        if cached_data:
            return cached_data
        
        try:
            self._respect_rate_limit()
            response = retry_request(
                requests.get,
                file_url,
                headers=HTTP_HEADERS,
                timeout=API_REQUEST_TIMEOUT,
                max_retries=API_RETRY_COUNT,
                retry_delay=API_RETRY_DELAY
            )
            response.raise_for_status()
            historical_data = response.json()
            filing_cache.set(cache_key, historical_data)
            return historical_data
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching historical filings: {e}")
            return None
    
    def _process_filings_data(self, filings_data, filing_type, start_date, end_date, limit):
        """
        Process filings data to extract relevant filings.
        
        Args:
            filings_data (dict): Filings data from SEC API
            filing_type (str): Type of filing to filter
            start_date (datetime): Start date for filtering
            end_date (datetime): End date for filtering
            limit (int): Maximum number of filings to extract
            
        Returns:
            list: List of filing metadata
        """
        processed_filings = []
        
        accession_numbers = filings_data.get("accessionNumber", [])
        form_types = filings_data.get("form", [])
        filing_dates = filings_data.get("filingDate", [])
        descriptions = filings_data.get("primaryDocument", [])
        urls = filings_data.get("primaryDocumentUrl", [])
        reporting_dates = filings_data.get("reportDate", [])
        
        for i in range(min(len(accession_numbers), len(form_types))):
            form = form_types[i] if i < len(form_types) else ""
            if filing_type.upper() != "ALL" and form.upper() != filing_type.upper():
                continue
            
            filing_date_str = filing_dates[i] if i < len(filing_dates) else ""
            filing_date = parse_date(filing_date_str)
            if start_date and filing_date and filing_date < start_date:
                continue
            if end_date and filing_date and filing_date > end_date:
                continue
            
            filing_info = {
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else "",
                "form": form,
                "filing_date": filing_date_str,
                "description": descriptions[i] if i < len(descriptions) else "",
                "url": urls[i] if i < len(urls) else "",
                "reporting_date": reporting_dates[i] if i < len(reporting_dates) else "",
            }
            
            processed_filings.append(filing_info)
            if len(processed_filings) >= limit:
                break
        
        return processed_filings
    
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
        
        cache_key = f"filing_content_{url}"
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
            
            if not output_dir:
                output_dir = os.path.join(DEFAULT_OUTPUT_DIR, "filings")
            os.makedirs(output_dir, exist_ok=True)
            file_path = os.path.join(output_dir, file_name)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
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
        
        formatted_cik = str(cik).zfill(10)
        formatted_accession = accession_number.replace('-', '')
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
        
        formatted_cik = str(cik).zfill(10)
        formatted_accession = accession_number.replace('-', '')
        cache_key = f"xbrl_content_{formatted_cik}_{formatted_accession}"
        cached_content = filing_cache.get(cache_key)
        if cached_content:
            return cached_content.get("path"), cached_content.get("content")
        
        _, filing_content = self.get_filing_by_accession(cik, accession_number)
        if not filing_content:
            return None, None
        
        # Use lxml to parse the filing content and extract the XBRL filename
        try:
            parser = etree.XMLParser(recover=True)
            root = etree.fromstring(filing_content.encode('utf-8'), parser=parser)
            xbrl_filename = root.findtext('.//FILENAME')
            if not xbrl_filename:
                logger.warning(f"No XBRL instance document found in filing {accession_number}")
                return None, None
            
            url = f"{SEC_BASE_URL}/Archives/edgar/data/{int(formatted_cik)}/{formatted_accession}/{xbrl_filename}"
            file_path, file_content = self.download_filing(url)
            if file_path and file_content:
                filing_cache.set(cache_key, {
                    "path": file_path,
                    "content": file_content
                })
            return file_path, file_content
        except etree.XMLSyntaxError as e:
            logger.error(f"XML parsing error in XBRL extraction: {e}")
            return None, None