"""
EDGAR Financial Tool - Main Module.

This is the main entry point for the EDGAR Financial Tool.
"""

import os
import sys
import logging
import argparse
from datetime import datetime

from config.constants import FINANCIAL_STATEMENT_TYPES, REPORTING_PERIODS, ERROR_MESSAGES
from config.settings import (
    DEFAULT_OUTPUT_FORMAT, SUPPORTED_OUTPUT_FORMATS, 
    DEFAULT_ANNUAL_PERIODS, DEFAULT_QUARTERLY_PERIODS,
    LOG_LEVEL, LOG_FILE, LOG_FORMAT, LOG_DATE_FORMAT
)

from edgar.company_lookup import search_company, get_cik_by_company_name
from edgar.filing_retrieval import FilingRetrieval
from edgar.xbrl_parser import XBRLParser
from edgar.data_formatter import DataFormatter

from utils.validators import (
    is_valid_company_name, is_valid_cik, 
    is_valid_statement_type, is_valid_reporting_period,
    is_valid_number_of_periods, is_valid_output_format
)

# Set up logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

# Initialize logger
logger = logging.getLogger(__name__)


def setup_args():
    """
    Set up command-line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="EDGAR Financial Tool - Retrieve and analyze financial statements from SEC EDGAR"
    )
    
    # Company information
    company_group = parser.add_argument_group("Company Information")
    company_group.add_argument(
        "--company", "-c", type=str, help="Company name or ticker"
    )
    company_group.add_argument(
        "--cik", type=str, help="Company CIK number (overrides --company if provided)"
    )
    
    # Filing selection
    filing_group = parser.add_argument_group("Filing Selection")
    filing_group.add_argument(
        "--statement-type", "-s", type=str, default="ALL",
        choices=FINANCIAL_STATEMENT_TYPES.keys(),
        help="Financial statement type to extract (default: ALL)"
    )
    filing_group.add_argument(
        "--period-type", "-p", type=str, default="annual",
        choices=REPORTING_PERIODS.keys(),
        help="Reporting period type (default: annual)"
    )
    filing_group.add_argument(
        "--num-periods", "-n", type=int,
        help=f"Number of periods to retrieve (default: {DEFAULT_ANNUAL_PERIODS} for annual, "
             f"{DEFAULT_QUARTERLY_PERIODS} for quarterly)"
    )
    
    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output-format", "-f", type=str, default=DEFAULT_OUTPUT_FORMAT,
        choices=SUPPORTED_OUTPUT_FORMATS,
        help=f"Output format (default: {DEFAULT_OUTPUT_FORMAT})"
    )
    output_group.add_argument(
        "--output-file", "-o", type=str,
        help="Output file path (default: auto-generated)"
    )
    
    # Parse arguments
    return parser.parse_args()


def interactive_mode():
    """
    Run the tool in interactive mode.
    
    Returns:
        dict: User-provided parameters
    """
    print("\n" + "=" * 60)
    print("  EDGAR Financial Tool - Interactive Mode")
    print("=" * 60 + "\n")
    
    # Company selection
    company_name = input("Enter company name or ticker: ")
    
    while not is_valid_company_name(company_name):
        print("Invalid company name. Please enter a valid company name or ticker.")
        company_name = input("Enter company name or ticker: ")
    
    # Search for the company
    matches = search_company(company_name)
    
    if not matches:
        print(ERROR_MESSAGES["COMPANY_NOT_FOUND"])
        return None
    
    cik = None
    
    # If multiple matches, let user choose
    if len(matches) > 1:
        print(f"\nFound {len(matches)} matches for '{company_name}':")
        for i, match in enumerate(matches, 1):
            print(f"{i}. {match['name']} (Ticker: {match['ticker']}, CIK: {match['cik']})")
        
        while True:
            try:
                choice = int(input("\nEnter the number of the correct company (0 to cancel): "))
                if choice == 0:
                    return None
                if 1 <= choice <= len(matches):
                    cik = matches[choice-1]["cik"]
                    company_name = matches[choice-1]["name"]
                    break
                print("Invalid choice, please try again.")
            except ValueError:
                print("Please enter a valid number.")
    else:
        cik = matches[0]["cik"]
        company_name = matches[0]["name"]
    
    print(f"\nSelected: {company_name} (CIK: {cik})")
    
    # Statement type selection
    print("\nAvailable financial statement types:")
    for code, name in FINANCIAL_STATEMENT_TYPES.items():
        print(f"{code}: {name}")
    
    statement_type = input("\nEnter financial statement type (default: ALL): ").upper() or "ALL"
    
    while not is_valid_statement_type(statement_type):
        print("Invalid statement type. Please enter a valid type.")
        statement_type = input("Enter financial statement type (default: ALL): ").upper() or "ALL"
    
    # Reporting period selection
    print("\nReporting period options:")
    for code, name in REPORTING_PERIODS.items():
        print(f"{code}: {name}")
    
    period_type = input("\nEnter reporting period type (default: annual): ").lower() or "annual"
    
    while not is_valid_reporting_period(period_type):
        print("Invalid period type. Please enter a valid type.")
        period_type = input("Enter reporting period type (default: annual): ").lower() or "annual"
    
    # Number of periods
    default_periods = DEFAULT_ANNUAL_PERIODS if period_type == "annual" else DEFAULT_QUARTERLY_PERIODS
    num_periods_input = input(f"\nEnter number of periods to retrieve (default: {default_periods}): ") or str(default_periods)
    
    try:
        num_periods = int(num_periods_input)
        
        if not is_valid_number_of_periods(num_periods, period_type):
            print(f"Invalid number of periods. Using default ({default_periods}).")
            num_periods = default_periods
    except ValueError:
        print(f"Invalid input. Using default ({default_periods}).")
        num_periods = default_periods
    
    # Output format
    print("\nAvailable output formats:")
    for fmt in SUPPORTED_OUTPUT_FORMATS:
        print(f"- {fmt}")
    
    output_format = input(f"\nEnter output format (default: {DEFAULT_OUTPUT_FORMAT}): ").lower() or DEFAULT_OUTPUT_FORMAT
    
    while not is_valid_output_format(output_format):
        print("Invalid output format. Please enter a valid format.")
        output_format = input(f"Enter output format (default: {DEFAULT_OUTPUT_FORMAT}): ").lower() or DEFAULT_OUTPUT_FORMAT
    
    # Output file path (optional)
    output_file = input("\nEnter output file path (leave blank for auto-generated): ")
    
    return {
        "company_name": company_name,
        "cik": cik,
        "statement_type": statement_type,
        "period_type": period_type,
        "num_periods": num_periods,
        "output_format": output_format,
        "output_file": output_file if output_file else None
    }


def run(params):
    """
    Run the EDGAR financial data retrieval process.
    
    Args:
        params (dict): Parameters for the retrieval process
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Initialize components
        filing_retrieval = FilingRetrieval()
        xbrl_parser = XBRLParser()
        data_formatter = DataFormatter(params["output_format"])
        
        print(f"\nRetrieving {params['statement_type']} for {params['company_name']} ({params['cik']})...")
        
        # Use the SEC API approach to get financial data
        print("Fetching financial data from SEC API...")
        
        # Get all financial facts for the company
        facts_data = filing_retrieval.get_company_facts(params["cik"])
        
        if not facts_data:
            print("\nNo financial data found for the company. Please check the CIK number.")
            return False
        
        # Parse the facts data to extract the requested statement type
        normalized_data = xbrl_parser.parse_company_facts(
            facts_data, 
            params["statement_type"],
            params["period_type"]
        )
        
        if not normalized_data or not normalized_data.get("periods") or not normalized_data.get("metrics"):
            print("\nInsufficient financial data for the requested statement type.")
            print("Try a different statement type or company.")
            return False
        
        # Format and output the data
        output = data_formatter.format_statement(
            normalized_data,
            params["statement_type"],
            params["company_name"],
            params["output_file"]
        )
        
        if output:
            if params["output_format"] in ["csv", "json", "excel"]:
                print(f"\nOutput saved to: {output}")
            else:
                print(output)
            
            return True
        else:
            print("\nError formatting the financial data.")
            return False
            
    except Exception as e:
        logger.error(f"Error in EDGAR financial data retrieval: {e}", exc_info=True)
        print(f"\nError: {str(e)}")
        return False


def main():
    """Main entry point for the EDGAR Financial Tool."""
    # Check for command-line arguments
    args = setup_args()
    
    # If company or CIK not provided, use interactive mode
    if not args.company and not args.cik:
        params = interactive_mode()
        
        if not params:
            print("\nOperation cancelled.")
            return
    else:
        # Use command-line arguments
        if args.cik:
            # Use provided CIK
            if not is_valid_cik(args.cik):
                print(ERROR_MESSAGES["INVALID_CIK"])
                return
            
            cik = args.cik
            company_name = f"Company CIK {cik}"
        else:
            # Look up CIK from company name
            cik = get_cik_by_company_name(args.company)
            
            if not cik:
                return
                
            company_name = args.company
        
        # Determine default number of periods
        if args.num_periods:
            num_periods = args.num_periods
        else:
            num_periods = DEFAULT_ANNUAL_PERIODS if args.period_type == "annual" else DEFAULT_QUARTERLY_PERIODS
        
        params = {
            "company_name": company_name,
            "cik": cik,
            "statement_type": args.statement_type,
            "period_type": args.period_type,
            "num_periods": num_periods,
            "output_format": args.output_format,
            "output_file": args.output_file
        }
    
    # Run the tool with the provided parameters
    success = run(params)
    
    if success:
        print("\nOperation completed successfully.")
    else:
        print("\nOperation failed. See messages above for details.")


if __name__ == "__main__":
    main()