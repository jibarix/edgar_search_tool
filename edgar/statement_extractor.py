"""
EDGAR Statement Extractor - Extracts financial statements from SEC filings.

This module contains functions for extracting specific financial statements
from SEC EDGAR filings, leveraging the HTML structure of these documents.
"""

import os
import logging
import calendar
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup

from config.constants import HTTP_HEADERS
from edgar.company_lookup import format_cik

# Initialize logger
logger = logging.getLogger(__name__)

# Mapping between statement types and their possible names in filings
STATEMENT_KEYS_MAP = {
    "BS": [
        "balance sheet",
        "balance sheets",
        "statement of financial position",
        "consolidated balance sheets",
        "consolidated balance sheet",
        "consolidated financial position",
        "consolidated balance sheets - southern",
        "consolidated statements of financial position",
        "consolidated statement of financial position",
        "consolidated statements of financial condition",
        "combined and consolidated balance sheet",
        "condensed consolidated balance sheets",
        "consolidated balance sheets, as of december 31"
    ],
    "IS": [
        "income statement",
        "income statements",
        "statement of earnings (loss)",
        "statements of consolidated income",
        "consolidated statements of operations",
        "consolidated statement of operations",
        "consolidated statements of earnings",
        "consolidated statement of earnings",
        "consolidated statements of income",
        "consolidated statement of income",
        "consolidated income statements",
        "consolidated income statement",
        "condensed consolidated statements of earnings",
        "consolidated results of operations",
        "consolidated statements of income (loss)",
        "consolidated statements of income - southern",
        "consolidated statements of operations and comprehensive income",
        "consolidated statements of comprehensive income"
    ],
    "CF": [
        "cash flows statement",
        "cash flows statements",
        "statement of cash flows",
        "statements of consolidated cash flows",
        "consolidated statements of cash flows",
        "consolidated statement of cash flows",
        "consolidated statement of cash flow",
        "consolidated cash flows statements",
        "consolidated cash flow statements",
        "condensed consolidated statements of cash flows",
        "consolidated statements of cash flows (unaudited)",
        "consolidated statements of cash flows - southern"
    ]
}


class StatementExtractor:
    """
    Class for extracting financial statements from SEC filings.
    """
    
    def __init__(self):
        """Initialize the statement extractor."""
        self.headers = HTTP_HEADERS.copy()
        self.headers['User-Agent'] = (
            "Financial Statement Analyzer 1.0 (example@example.com)"
        )
    
    def cik_matching_ticker(self, ticker):
        """
        Get CIK number for a ticker symbol.
        
        Args:
            ticker (str): Stock ticker symbol
            
        Returns:
            str: CIK number with leading zeros
        """
        ticker = ticker.upper().replace(".", "-")
        
        # Try to get from company_tickers.json
        try:
            response = requests.get(
                "https://www.sec.gov/files/company_tickers.json", 
                headers=self.headers
            )
            response.raise_for_status()
            ticker_json = response.json()
            
            for company in ticker_json.values():
                if company["ticker"] == ticker:
                    return format_cik(company["cik_str"])
            
            logger.warning(f"Ticker {ticker} not found in SEC database")
            return None
            
        except requests.RequestException as e:
            logger.error(f"Error fetching company tickers: {e}")
            return None
    
    def extract_statement(self, ticker, accession_number, statement_type):
        """
        Extract a financial statement for a company filing.
        
        Args:
            ticker (str): Stock ticker symbol
            accession_number (str): SEC filing accession number
            statement_type (str): Type of statement to extract ("BS", "IS", "CF")
            
        Returns:
            pandas.DataFrame: Extracted financial statement or None if extraction fails
        """
        try:
            # Get the statement soup
            soup = self.get_statement_soup(ticker, accession_number, statement_type)
            
            if soup:
                # Extract data from the statement
                columns, values, dates = self.extract_columns_values_and_dates_from_statement(soup)
                
                # Create DataFrame from the extracted data
                df = self.create_dataframe_of_statement_values_columns_dates(values, columns, dates)
                
                # Remove duplicate columns
                if not df.empty:
                    df = df.T.drop_duplicates()
                    return df
            
            logger.warning(f"Failed to extract {statement_type} for {ticker}, accession {accession_number}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting statement: {e}", exc_info=True)
            return None
    
    def get_statement_soup(self, ticker, accession_number, statement_type):
        """
        Get BeautifulSoup object for a specific financial statement.
        
        Args:
            ticker (str): Stock ticker symbol
            accession_number (str): SEC filing accession number
            statement_type (str): Type of statement to extract ("BS", "IS", "CF")
            
        Returns:
            BeautifulSoup: Parsed HTML content of the statement or None if not found
        """
        try:
            cik = self.cik_matching_ticker(ticker)
            if not cik:
                logger.error(f"Could not find CIK for ticker {ticker}")
                return None
            
            # Format the accession number
            accn_no_dashes = accession_number.replace("-", "")
            
            # Base URL for the filing
            base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_no_dashes}"
            
            # Get the filing summary
            filing_summary_url = f"{base_url}/FilingSummary.xml"
            response = requests.get(filing_summary_url, headers=self.headers)
            response.raise_for_status()
            
            # Parse the filing summary
            soup = BeautifulSoup(response.content, "lxml-xml")
            
            # Find the appropriate statement
            statement_file = None
            for report in soup.find_all("Report"):
                short_name_tag = report.find("ShortName")
                if not short_name_tag:
                    continue
                
                short_name = short_name_tag.text.lower()
                
                # Check if this is the statement we're looking for
                if short_name in STATEMENT_KEYS_MAP.get(statement_type, []):
                    file_name_tag = report.find("HtmlFileName") or report.find("XmlFileName")
                    if file_name_tag:
                        statement_file = file_name_tag.text
                        break
            
            if not statement_file:
                logger.warning(f"Could not find {statement_type} in filing {accession_number}")
                return None
            
            # Get the statement file
            statement_url = f"{base_url}/{statement_file}"
            response = requests.get(statement_url, headers=self.headers)
            response.raise_for_status()
            
            # Parse the statement HTML
            if statement_file.endswith(".xml"):
                return BeautifulSoup(response.content, "lxml-xml")
            else:
                return BeautifulSoup(response.content, "lxml")
                
        except requests.RequestException as e:
            logger.error(f"Request error fetching statement: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting statement soup: {e}", exc_info=True)
            return None
    
    def extract_columns_values_and_dates_from_statement(self, soup):
        """
        Extract columns, values, and dates from a financial statement.
        
        Args:
            soup (BeautifulSoup): Parsed HTML of the statement
            
        Returns:
            tuple: (columns, values_set, date_time_index)
        """
        columns = []
        values_set = []
        date_time_index = self.get_datetime_index_dates_from_statement(soup)
        
        for table in soup.find_all("table"):
            unit_multiplier = 1
            special_case = False
            
            # Check table headers for unit multipliers and special cases
            table_header = table.find("th")
            if table_header:
                header_text = table_header.get_text()
                # Determine unit multiplier based on header text
                if "in Thousands" in header_text:
                    unit_multiplier = 1000
                elif "in Millions" in header_text:
                    unit_multiplier = 1000000
                # Check for special case scenario
                if "unless otherwise specified" in header_text:
                    special_case = True
            
            # Process each row of the table
            for row in table.select("tr"):
                onclick_elements = row.select("td.pl a, td.pl.custom a")
                if not onclick_elements:
                    continue
                
                # Get column title
                try:
                    onclick_attr = onclick_elements[0]["onclick"]
                    column_title = onclick_attr.split("defref_")[-1].split("',")[0]
                    columns.append(column_title)
                except (KeyError, IndexError):
                    continue
                
                # Initialize values array with NaNs
                values = [np.nan] * len(date_time_index)
                
                # Process each cell in the row
                for i, cell in enumerate(row.select("td.text, td.nump, td.num")):
                    if i >= len(values) or "text" in cell.get("class", []):
                        continue
                    
                    # Clean and parse cell value
                    value = self.keep_numbers_and_decimals_only_in_string(
                        cell.text.replace("$", "")
                        .replace(",", "")
                        .replace("(", "-")
                        .replace(")", "")
                        .strip()
                    )
                    
                    if value:
                        try:
                            value = float(value)
                            # Adjust value based on special case and cell class
                            if "nump" in cell.get("class", []):
                                values[i] = value * unit_multiplier
                            else:
                                # num class indicates negative values in accounting format
                                if "num" in cell.get("class", []) and value > 0:
                                    values[i] = -value * unit_multiplier
                                else:
                                    values[i] = value * unit_multiplier
                        except ValueError:
                            pass
                
                values_set.append(values)
        
        return columns, values_set, date_time_index
    
    def get_datetime_index_dates_from_statement(self, soup):
        """
        Extract dates from a financial statement.
        
        Args:
            soup (BeautifulSoup): Parsed HTML of the statement
            
        Returns:
            pandas.DatetimeIndex: DatetimeIndex for the statement periods
        """
        table_headers = soup.find_all("th", {"class": "th"})
        dates = []
        
        for th in table_headers:
            div = th.find("div")
            if div and div.string:
                date_str = str(div.string).strip()
                # Standardize the date
                standardized_date = self.standardize_date(date_str).replace(".", "")
                dates.append(standardized_date)
        
        # Convert to DatetimeIndex
        try:
            return pd.to_datetime(dates)
        except:
            # Handle parsing errors
            logger.warning(f"Could not parse dates: {dates}")
            return pd.DatetimeIndex([])
    
    def standardize_date(self, date_str):
        """
        Standardize date format by replacing month abbreviations.
        
        Args:
            date_str (str): Original date string
            
        Returns:
            str: Standardized date string
        """
        # Replace month abbreviations with full month names
        for abbr, full in zip(calendar.month_abbr[1:], calendar.month_name[1:]):
            date_str = date_str.replace(abbr, full)
        
        return date_str
    
    def keep_numbers_and_decimals_only_in_string(self, mixed_string):
        """
        Filter a string to keep only numbers, decimals and negative sign.
        
        Args:
            mixed_string (str): Input string
            
        Returns:
            str: Filtered string
        """
        allowed_chars = "1234567890.-"
        return "".join(c for c in mixed_string if c in allowed_chars)
    
    def create_dataframe_of_statement_values_columns_dates(self, values_set, columns, index_dates):
        """
        Create a DataFrame from extracted statement data.
        
        Args:
            values_set (list): Set of values
            columns (list): Column names
            index_dates (pandas.DatetimeIndex): Date index
            
        Returns:
            pandas.DataFrame: Statement DataFrame
        """
        if not values_set or not columns or len(index_dates) == 0:
            return pd.DataFrame()
        
        # Transpose the values set
        transposed_values = list(zip(*values_set))
        
        # Create DataFrame
        df = pd.DataFrame(transposed_values, columns=columns, index=index_dates)
        
        # Format display of large numbers
        pd.options.display.float_format = (
            lambda x: "{:,.0f}".format(x) if int(x) == x else "{:,.2f}".format(x)
        )
        
        return df
    
    def save_statement_to_csv(self, statement, output_path):
        """
        Save statement DataFrame to CSV.
        
        Args:
            statement (pandas.DataFrame): Statement DataFrame
            output_path (str): Output file path
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Save to CSV
            statement.to_csv(output_path)
            logger.info(f"Statement saved to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving statement to CSV: {e}")
            return False