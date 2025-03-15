"""
Constants for the EDGAR Financial Tool.
"""

# SEC API endpoints
SEC_BASE_URL = "https://www.sec.gov"
EDGAR_BASE_URL = f"{SEC_BASE_URL}/edgar"
COMPANY_TICKERS_URL = f"{SEC_BASE_URL}/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
XBRL_INSTANCE_URL = f"{SEC_BASE_URL}/Archives/edgar/data"

# Filing types
FILING_TYPES = {
    "10-K": "Annual report",
    "10-Q": "Quarterly report",
    "8-K": "Current report",
    "20-F": "Annual report for foreign private issuers",
    "40-F": "Annual report for Canadian companies",
    "6-K": "Current report for foreign private issuers",
    "DEF 14A": "Definitive proxy statement",
    "S-1": "Registration statement for new securities",
    "S-3": "Simplified registration statement",
    "S-4": "Registration for mergers or acquisitions",
}

# Financial statement types
FINANCIAL_STATEMENT_TYPES = {
    "BS": "Balance Sheet",
    "IS": "Income Statement",
    "CF": "Cash Flow Statement",
    "EQ": "Equity Statement",
    "CI": "Comprehensive Income",
    "ALL": "All Financial Statements"
}

# Reporting periods
REPORTING_PERIODS = {
    "annual": "Annual",
    "quarterly": "Quarterly",
    "ytd": "Year-to-Date"
}

# XBRL Tags for common financial items
XBRL_TAGS = {
    # Balance Sheet
    "Assets": [
        "us-gaap:Assets",
        "us-gaap:AssetsCurrent"
    ],
    "Liabilities": [
        "us-gaap:Liabilities",
        "us-gaap:LiabilitiesCurrent"
    ],
    "StockholdersEquity": [
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    ],
    
    # Income Statement
    "Revenue": [
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    ],
    "NetIncome": [
        "us-gaap:NetIncomeLoss",
        "us-gaap:ProfitLoss",
        "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic"
    ],
    "EPS": [
        "us-gaap:EarningsPerShareBasic",
        "us-gaap:EarningsPerShareDiluted"
    ],
    
    # Cash Flow
    "OperatingCashFlow": [
        "us-gaap:NetCashProvidedByUsedInOperatingActivities"
    ],
    "InvestingCashFlow": [
        "us-gaap:NetCashProvidedByUsedInInvestingActivities"
    ],
    "FinancingCashFlow": [
        "us-gaap:NetCashProvidedByUsedInFinancingActivities"
    ]
}

# HTTP Request Headers
HTTP_HEADERS = {
    "User-Agent": "Financial Statement Analyzer 1.0 (contact@example.com)"
}

# Cache configuration
CACHE_CONFIG = {
    "TTL": 86400,  # Time to live in seconds (24 hours)
    "MAX_SIZE": 1000,  # Maximum number of items in cache
    "ENABLED": True
}

# Error messages
ERROR_MESSAGES = {
    "COMPANY_NOT_FOUND": "Company not found. Please check the name and try again.",
    "INVALID_CIK": "Invalid CIK number. Please provide a valid CIK.",
    "NO_FILINGS": "No filings found for the specified criteria.",
    "CONNECTION_ERROR": "Error connecting to SEC EDGAR. Please check your internet connection.",
    "RATE_LIMIT": "SEC API rate limit exceeded. Please try again later.",
    "PARSING_ERROR": "Error parsing XBRL data. The filing may not contain the requested information."
}