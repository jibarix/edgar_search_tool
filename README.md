# EDGAR Search Tool


## File Structure
edgar_financial_tool/
│
├── main.py                     # Main entry point with user interface
├── requirements.txt            # Dependencies list
├── README.md                   # Documentation
│
├── edgar/                      # Core package
│   ├── __init__.py             # Package initialization
│   ├── requirements.txt       # CIK and company lookup functionality
│   ├── filing_retrieval.py     # Access and download EDGAR filings
│   ├── xbrl_parser.py          # Extract and process XBRL data
│   └── data_formatter.py       # Format financial data for output
│
├── config/
│   ├── __init__.py
│   ├── settings.py             # Configuration settings
│   └── constants.py            # API endpoints, filing types, etc.
│
├── utils/
│   ├── __init__.py
│   ├── validators.py           # Input validation
│   ├── cache.py                # Data caching
│   └── helpers.py              # Utility functions
│
└── tests/                      # Unit and integration tests
    ├── __init__.py
    ├── test_company_lookup.py
    ├── test_filing_retrieval.py
    ├── test_xbrl_parser.py
    └── test_data_formatter.py