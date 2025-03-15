# EDGAR Financial Tool

A Python-based tool for retrieving, analyzing, and exporting financial statements from the SEC's EDGAR database.

## Overview

The EDGAR Financial Tool allows users to access and analyze financial data from public companies by interacting directly with the U.S. Securities and Exchange Commission's Electronic Data Gathering, Analysis, and Retrieval (EDGAR) system. This tool simplifies the process of retrieving, parsing, and presenting financial statement data from SEC filings.

## Features

- **Company Search**: Look up companies by name or ticker symbol
- **Financial Statement Retrieval**: Download Balance Sheets, Income Statements, Cash Flow Statements, and more
- **XBRL Data Extraction**: Parse structured financial data from XBRL filings
- **Multi-period Analysis**: Retrieve data across multiple reporting periods
- **Flexible Output Formats**: Export data as CSV, JSON, Excel, or view directly in console
- **Interactive Mode**: User-friendly command-line interface for step-by-step data retrieval
- **Caching System**: Efficient data retrieval with local caching to minimize redundant downloads

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
- Reporting period (Annual or Quarterly)
- Number of periods to retrieve
- Output format

### Command-line Mode

For scripted or automated use:

```bash
python main.py --company "Apple Inc" --statement-type BS --period-type annual --num-periods 3 --output-format csv
```

### Command-line Options

```
Company Information:
  --company COMPANY, -c COMPANY
                        Company name or ticker
  --cik CIK             Company CIK number (overrides --company if provided)

Filing Selection:
  --filing-type FILING_TYPE
                        Filing type to retrieve (default: 10-K)
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
```

## Compliance with SEC Guidelines

This tool is designed to comply with the SEC's fair access guidelines by:
- Implementing appropriate rate limiting (10 requests per second)
- Including proper User-Agent headers with contact information
- Caching retrieved data to minimize duplicate requests

For more information on SEC's EDGAR access requirements, visit: https://www.sec.gov/os/accessing-edgar-data

## Financial Statement Types

| Code | Description |
|------|-------------|
| BS   | Balance Sheet |
| IS   | Income Statement |
| CF   | Cash Flow Statement |
| EQ   | Equity Statement |
| CI   | Comprehensive Income |
| ALL  | All Financial Statements |

## Limitations

- The tool relies on the availability and accuracy of XBRL data in SEC filings
- Some older filings may not contain structured XBRL data
- Company-specific reporting variations may affect data extraction consistency
- Very large documents may require additional memory resources

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

Distributed under the MIT License. See `LICENSE` for more information.

## Acknowledgments

- This tool uses the SEC's EDGAR system data
- Inspired by the need for accessible financial data for investment research and analysis
- Thanks to the contributors of the Python packages this tool depends on