# EDGAR Financial Tool

A Python-based tool for retrieving, analyzing, and exporting financial statements from the SEC's EDGAR database using official SEC APIs.

## Overview

The EDGAR Financial Tool allows users to access and analyze financial data from public companies by interacting directly with the U.S. Securities and Exchange Commission's Electronic Data Gathering, Analysis, and Retrieval (EDGAR) system and its APIs. This tool simplifies the process of retrieving, parsing, and presenting financial statement data from SEC filings in XBRL format.

## Features

- **Company Search**: Look up companies by name or ticker symbol
- **Financial Statement Retrieval**: Download Balance Sheets, Income Statements, Cash Flow Statements, and more
- **XBRL Data Extraction**: Access structured financial data using SEC's official XBRL APIs
- **Multi-period Analysis**: Retrieve data across multiple reporting periods
- **Flexible Output Formats**: Export data as CSV, JSON, Excel, or view directly in console
- **Interactive Mode**: User-friendly command-line interface for step-by-step data retrieval
- **Caching System**: Efficient data retrieval with local caching to minimize redundant API calls

## SEC EDGAR API Integration

This tool leverages the SEC's official XBRL data APIs, which provide standardized financial data in JSON format:

- **Company Facts API**: Retrieves all XBRL facts for a company in a single request
  - Endpoint: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
  - Usage: Provides all financial data across all reporting periods
  
- **Company Concept API**: Retrieves specific financial concepts for a company
  - Endpoint: `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/taxonomy/tag.json`
  - Example: `https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json`
  - Usage: Provides historical values for a specific financial metric

These APIs offer several advantages over traditional EDGAR filing access:
- Standardized data structure across companies
- Clean, normalized values for financial metrics
- Historical data in a single request
- Lower bandwidth requirements and faster processing

## SEC API Compliance

The tool adheres to SEC.gov's access requirements:
- Includes proper User-Agent headers with contact information
- Implements rate limiting (maximum 10 requests per second)
- Uses caching to minimize redundant requests
- No CORS usage or scraping of HTML content

For more information on SEC's API requirements, visit: https://www.sec.gov/developer

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/edgar-financial-tool.git
   cd edgar-financial-tool
   ```

2. Create a virtual environment:
   ```bash
   # On Windows
   python -m venv venv
   venv\Scripts\activate

   # On macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. When you're done using the tool, you can deactivate the virtual environment:
   ```bash
   deactivate
   ```

## Usage

### Interactive Mode

For a guided experience, simply run:

```bash
python main.py
```

The interactive mode will prompt you for:
- Company name or ticker
- Financial statement type (Balance Sheet, Income Statement, Cash Flow, etc.)
- Reporting period (Annual, Quarterly, or Year-to-Date)
- Number of periods to retrieve
- Output format

### Command-line Mode

For scripted or automated use:

```bash
python main.py --company "Apple Inc" --statement-type BS --period-type annual --num-periods 3 --output-format excel
```

### Command-line Options

```
Company Information:
  --company COMPANY, -c COMPANY
                        Company name or ticker
  --cik CIK             Company CIK number (overrides --company if provided)

Filing Selection:
  --statement-type {BS,IS,CF,EQ,CI,ALL}, -s {BS,IS,CF,EQ,CI,ALL}
                        Financial statement type to extract (default: ALL)
  --period-type {annual,quarterly,ytd}, -p {annual,quarterly,ytd}
                        Reporting period type (default: annual)
  --num-periods NUM_PERIODS, -n NUM_PERIODS
                        Number of periods to retrieve

Output Options:
  --output-format {csv,json,excel,console}, -f {csv,json,excel,console}
                        Output format (default: csv)
  --output-file OUTPUT_FILE, -o OUTPUT_FILE
                        Output file path (default: auto-generated)
```

## Examples

### Retrieving Apple's Balance Sheet for the Past 3 Years

```bash
python main.py -c "Apple Inc" -s BS -p annual -n 3 -f excel
```

### Getting Amazon's Income Statement for Recent Quarters

```bash
python main.py -c "Amazon.com Inc" -s IS -p quarterly -n 4 -f json
```

### Viewing Microsoft's Cash Flow Statement in the Console

```bash
python main.py -c "Microsoft Corporation" -s CF -p annual -n 2 -f console
```

## Understanding the Data

### Financial Statement Types

| Code | Description |
|------|-------------|
| BS   | Balance Sheet |
| IS   | Income Statement |
| CF   | Cash Flow Statement |
| EQ   | Equity Statement |
| CI   | Comprehensive Income |
| ALL  | All Financial Statements |

### XBRL Data Structure

Financial data retrieved through the SEC API is structured as follows:
- Company facts include multiple taxonomies (typically `us-gaap` or `ifrs-full`)
- Each taxonomy contains financial concepts (e.g., `Assets`, `Liabilities`, `Revenues`)
- Each concept has facts with:
  - Value (`val`): The numeric value
  - Period start and end dates (`start`, `end`)
  - Filing date (`filed`)
  - Unit of measure (`USD`, `shares`, etc.)

The tool normalizes this data and organizes it by financial statement type, making it easy to analyze and export.

## Project Structure

```
edgar_financial_tool/
│
├── main.py                     # Main entry point with user interface
├── requirements.txt            # Dependencies list
├── README.md                   # Documentation
│
├── edgar/                      # Core package
│   ├── __init__.py             # Package initialization
│   ├── company_lookup.py       # CIK and company lookup functionality
│   ├── filing_retrieval.py     # Access SEC APIs and retrieve data
│   ├── xbrl_parser.py          # Process and normalize API data
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
```

## Limitations

- Data availability depends on company's XBRL filings with the SEC
- Only U.S. publicly traded companies and foreign companies that file with the SEC are available
- Historical data may be limited for some companies
- Companies may use different taxonomies or tag names for similar financial concepts
- The SEC API has rate limiting restrictions (10 requests/second)

## Troubleshooting

### Common Issues

1. **Company Not Found**
   - Try searching by ticker symbol instead of company name
   - Verify the company is publicly traded and files with the SEC

2. **No Data Available**
   - Some companies may not have filed in XBRL format for older periods
   - Try using a different statement type or period type

3. **API Rate Limiting**
   - The tool implements caching to minimize API calls
   - Wait a few minutes and try again if you encounter rate limit errors

4. **Missing Financial Metrics**
   - Companies may use different taxonomy tags for reporting
   - Not all financial metrics are reported by all companies

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

Distributed under the MIT License. See `LICENSE` for more information.

## Acknowledgments

- This tool uses the SEC's EDGAR system and APIs for data access
- Thanks to the SEC for providing standardized financial data through their XBRL APIs
- Inspired by the need for accessible financial data for investment research and analysis