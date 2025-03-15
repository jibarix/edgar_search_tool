"""
Data formatter for presenting financial statement data.
"""

import os
import csv
import json
import logging
from datetime import datetime
from tabulate import tabulate
import pandas as pd

from config.settings import DEFAULT_OUTPUT_FORMAT, DEFAULT_OUTPUT_DIR, TERMINAL_WIDTH
from utils.helpers import format_financial_number

# Initialize logger
logger = logging.getLogger(__name__)


class DataFormatter:
    """
    Formatter for financial statement data.
    """
    
    def __init__(self, output_format=DEFAULT_OUTPUT_FORMAT):
        """
        Initialize the data formatter.
        
        Args:
            output_format (str): Format to output data in ('csv', 'json', 'excel', 'console')
        """
        self.output_format = output_format.lower()
    
    def _get_statement_title(self, statement_type):
        """
        Get a human-readable title for a financial statement.
        
        Args:
            statement_type (str): Type of financial statement
            
        Returns:
            str: Human-readable title
        """
        statement_type = statement_type.upper()
        
        if statement_type == 'BS':
            return "Balance Sheet"
        elif statement_type == 'IS':
            return "Income Statement"
        elif statement_type == 'CF':
            return "Cash Flow Statement"
        elif statement_type == 'EQ':
            return "Statement of Stockholders' Equity"
        elif statement_type == 'CI':
            return "Statement of Comprehensive Income"
        elif statement_type == 'ALL':
            return "Financial Statements"
        else:
            return f"Financial Statement ({statement_type})"
    
    def _format_period_header(self, period, metadata=None):
        """
        Format a period date into a readable header.
        
        Args:
            period (str): Period date in ISO format (YYYY-MM-DD)
            metadata (dict): Optional metadata about the fiscal year
            
        Returns:
            str: Formatted period header
        """
        try:
            date_obj = datetime.strptime(period, "%Y-%m-%d")
            
            # If metadata is provided, check if this is a fiscal year end
            if metadata and 'fiscal_month' in metadata:
                fiscal_month = metadata['fiscal_month']
                period_type = metadata.get('period_type', 'annual')
                
                if period.split('-')[1] == fiscal_month:
                    # This is a fiscal year end date
                    if period_type == 'annual' or period_type == 'ytd':
                        return f"FY {date_obj.year}"
                    else:
                        # For quarterly periods
                        return f"Q{(date_obj.month % 3) or 4} {date_obj.year}"
                else:
                    # Not a fiscal year end - use the quarter if this is quarterly data
                    if period_type == 'quarterly':
                        return f"Q{(date_obj.month % 3) or 4} {date_obj.year}"
            
            # Default formatting - use FY for annual data
            if metadata and metadata.get('period_type') == 'annual':
                return f"FY {date_obj.year}"
                
            # Default formatting
            return date_obj.strftime("%b %d, %Y")
        except ValueError:
            # If date parsing fails, return the original
            return period
    
    def _create_dataframe(self, data):
        """
        Create a DataFrame from normalized financial data.
        
        Args:
            data (dict): Normalized financial statement data
            
        Returns:
            pandas.DataFrame: DataFrame with financial data
        """
        # Prepare data for DataFrame
        df_data = []
        
        # Format period headers
        metadata = data.get('metadata', {})
        formatted_periods = {period: self._format_period_header(period, metadata) 
                            for period in data['periods']}
        
        # Group metrics by category for better organization
        metrics_by_category = {}
        for metric_key, metric_data in data['metrics'].items():
            category = metric_data['category']
            if category not in metrics_by_category:
                metrics_by_category[category] = []
            metrics_by_category[category].append((metric_key, metric_data))
        
        # Add each metric to the DataFrame data
        for category in sorted(metrics_by_category.keys()):
            # Add category header
            df_data.append({
                'Metric': f"--- {category} ---",
                **{formatted_periods[period]: "" for period in data['periods']}
            })
            
            # Sort metrics in this category by their order value
            sorted_metrics = sorted(metrics_by_category[category], 
                                   key=lambda x: x[1].get('order', 50))
            
            # Add metrics in this category
            for metric_key, metric_data in sorted_metrics:
                # Use the display name if available, otherwise use the metric key
                display_name = metric_data.get('display_name')
                if not display_name:
                    # Clean up metric name for display
                    display_name = metric_key.split('_', 1)[1]
                    display_name = ' '.join(word.capitalize() for word in display_name.split())
                
                row_data = {'Metric': display_name}
                
                for period in data['periods']:
                    value = metric_data['values'].get(period)
                    row_data[formatted_periods[period]] = value
                
                df_data.append(row_data)
        
        # Create DataFrame
        return pd.DataFrame(df_data)
    
    def _format_dataframe(self, df):
        """
        Apply formatting to the DataFrame.
        
        Args:
            df (pandas.DataFrame): DataFrame with financial data
            
        Returns:
            pandas.DataFrame: Formatted DataFrame
        """
        # Create a copy to avoid modifying the original
        formatted_df = df.copy()
        
        # Format numeric columns
        for col in formatted_df.columns:
            if col != 'Metric':
                # Apply formatting to numeric values
                formatted_df[col] = formatted_df[col].apply(
                    lambda x: format_financial_number(x) if pd.notnull(x) and not isinstance(x, str) else x
                )
        
        return formatted_df
    
    def format_statement(self, data, statement_type, company_name=None, output_file=None):
        """
        Format financial statement data.
        
        Args:
            data (dict): Normalized financial statement data
            statement_type (str): Type of financial statement
            company_name (str): Name of the company
            output_file (str): Path to output file
            
        Returns:
            str: Path to the output file or formatted data for console
        """
        if not data or not data.get('periods') or not data.get('metrics'):
            logger.warning("No data to format")
            return None
        
        statement_title = self._get_statement_title(statement_type)
        
        # Log information about the periods being formatted
        period_info = ", ".join([self._format_period_header(p, data.get('metadata')) for p in data['periods']])
        logger.info(f"Formatting {statement_title} for periods: {period_info}")
        
        # Create a DataFrame from the data
        df = self._create_dataframe(data)
        
        # Apply formatting
        formatted_df = self._format_dataframe(df)
        
        # Add company name if not already present
        if company_name and 'Company' not in formatted_df.columns:
            formatted_df.insert(0, 'Company', company_name)
        
        # Output based on format
        if self.output_format == 'csv':
            return self._output_csv(formatted_df, statement_type, company_name, output_file)
        elif self.output_format == 'json':
            return self._output_json(formatted_df, statement_type, company_name, output_file)
        elif self.output_format == 'excel':
            return self._output_excel(formatted_df, statement_type, company_name, output_file, data)
        else:  # console
            return self._format_for_console(formatted_df, statement_title, company_name)
    
    def _output_csv(self, df, statement_type, company_name=None, output_file=None):
        """
        Output data as CSV file.
        
        Args:
            df (pandas.DataFrame): DataFrame to output
            statement_type (str): Type of financial statement
            company_name (str): Name of the company
            output_file (str): Path to output file
            
        Returns:
            str: Path to the output file
        """
        # Generate output filename if not provided
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            company_slug = company_name.replace(" ", "_").lower() if company_name else "company"
            statement_slug = statement_type.lower()
            
            filename = f"{company_slug}_{statement_slug}_{timestamp}.csv"
            output_file = os.path.join(DEFAULT_OUTPUT_DIR, filename)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # Write to CSV
        df.to_csv(output_file, index=False, quoting=csv.QUOTE_NONNUMERIC)
        
        logger.info(f"CSV output saved to {output_file}")
        return output_file
    
    def _output_json(self, df, statement_type, company_name=None, output_file=None):
        """
        Output data as JSON file.
        
        Args:
            df (pandas.DataFrame): DataFrame to output
            statement_type (str): Type of financial statement
            company_name (str): Name of the company
            output_file (str): Path to output file
            
        Returns:
            str: Path to the output file
        """
        # Generate output filename if not provided
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            company_slug = company_name.replace(" ", "_").lower() if company_name else "company"
            statement_slug = statement_type.lower()
            
            filename = f"{company_slug}_{statement_slug}_{timestamp}.json"
            output_file = os.path.join(DEFAULT_OUTPUT_DIR, filename)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # Convert DataFrame to JSON
        json_data = {
            "metadata": {
                "company": company_name,
                "statement_type": self._get_statement_title(statement_type),
                "generated_at": datetime.now().isoformat(),
                "fiscal_periods": [col for col in df.columns if col not in ['Company', 'Metric']]
            },
            "data": json.loads(df.to_json(orient="records"))
        }
        
        # Write to JSON file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"JSON output saved to {output_file}")
        return output_file
    
    def _output_excel(self, df, statement_type, company_name=None, output_file=None, data=None):
        """
        Output data as Excel file.
        
        Args:
            df (pandas.DataFrame): DataFrame to output
            statement_type (str): Type of financial statement
            company_name (str): Name of the company
            output_file (str): Path to output file
            data (dict): Original normalized data
            
        Returns:
            str: Path to the output file
        """
        # Generate output filename if not provided
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            company_slug = company_name.replace(" ", "_").lower() if company_name else "company"
            statement_slug = statement_type.lower()
            
            filename = f"{company_slug}_{statement_slug}_{timestamp}.xlsx"
            output_file = os.path.join(DEFAULT_OUTPUT_DIR, filename)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # Write to Excel
        with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
            # Write DataFrame to Excel
            df.to_excel(writer, sheet_name=self._get_statement_title(statement_type), index=False)
            
            # Access the workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets[self._get_statement_title(statement_type)]
            
            # Add title
            title_format = workbook.add_format({
                'bold': True,
                'font_size': 14,
                'align': 'center'
            })
            
            statement_title = self._get_statement_title(statement_type)
            if company_name:
                title = f"{company_name} - {statement_title}"
            else:
                title = statement_title
                
            worksheet.merge_range(0, 0, 0, len(df.columns) - 1, title, title_format)
            
            # Add fiscal year info if available
            if data and 'metadata' in data and 'fiscal_month' in data['metadata']:
                fiscal_month = int(data['metadata']['fiscal_month'])
                month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                               'July', 'August', 'September', 'October', 'November', 'December']
                fiscal_note = f"Note: Company uses a fiscal year ending in {month_names[fiscal_month-1]}"
                
                note_format = workbook.add_format({
                    'italic': True,
                    'font_size': 10,
                    'align': 'center'
                })
                
                worksheet.merge_range(1, 0, 1, len(df.columns) - 1, fiscal_note, note_format)
                
                # Adjust the starting row for the data
                df.to_excel(writer, sheet_name=self._get_statement_title(statement_type), 
                            startrow=2, index=False)
                
                # Adjust header row for formats below
                header_row = 2
            else:
                # Move data down one row to make space for the title
                df.to_excel(writer, sheet_name=self._get_statement_title(statement_type), 
                            startrow=1, index=False)
                
                # Standard header row
                header_row = 1
            
            # Format headers
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'border': 1
            })
            
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(header_row, col_num, value, header_format)
            
            # Format category rows
            category_format = workbook.add_format({
                'bold': True,
                'italic': True,
                'bg_color': '#E0E0E0'
            })
            
            # Format for financial data cells
            number_format = workbook.add_format({
                'num_format': '#,##0.00_);(#,##0.00)',
                'align': 'right'
            })
            
            # Apply formatting to rows
            for row_num, row_data in enumerate(df.values, start=header_row+1):
                for col_num, cell_value in enumerate(row_data):
                    # Skip company name column
                    if col_num == 0 and 'Company' in df.columns:
                        continue
                    
                    # Skip metric name column
                    metric_col = 0 if 'Company' not in df.columns else 1
                    if col_num == metric_col:
                        # Check if this is a category row
                        if isinstance(cell_value, str) and cell_value.startswith('---'):
                            for i in range(len(row_data)):
                                worksheet.write(row_num, i, row_data[i], category_format)
                            break
                        continue
                    
                    # Format numbers in other columns
                    if isinstance(cell_value, (int, float)) or (isinstance(cell_value, str) and 
                                                              any(c.isdigit() for c in cell_value)):
                        worksheet.write(row_num, col_num, cell_value, number_format)
            
            # Auto-adjust column widths
            for i, col in enumerate(df.columns):
                # Calculate the maximum length
                max_len = max(df[col].astype(str).apply(len).max(),
                              len(str(col)))
                # Set width with some extra padding
                worksheet.set_column(i, i, max_len + 2)
        
        logger.info(f"Excel output saved to {output_file}")
        return output_file
    
    def _format_for_console(self, df, title, company_name=None):
        """
        Format data for console output.
        
        Args:
            df (pandas.DataFrame): DataFrame to output
            title (str): Statement title
            company_name (str): Name of the company
            
        Returns:
            str: Formatted string for console output
        """
        # Create a header
        if company_name:
            header = f"{company_name} - {title}"
        else:
            header = title
            
        # Format header with borders
        header_border = "=" * min(len(header) + 4, TERMINAL_WIDTH)
        formatted_header = f"\n{header_border}\n  {header}  \n{header_border}\n"
        
        # Create a copy of the DataFrame for display formatting
        display_df = df.copy()
        
        # Identify category rows
        category_rows = []
        for i, row in display_df.iterrows():
            metric_col = 'Metric'
            if isinstance(row[metric_col], str) and row[metric_col].startswith('---'):
                category_name = row[metric_col].strip('- ')
                # Replace the category marker with a better formatted version
                display_df.at[i, metric_col] = f"{category_name.upper()}:"
                category_rows.append(i)
        
        # Format the table
        table = tabulate(display_df, headers="keys", tablefmt="grid", showindex=False)
        
        # Combine and return
        return f"{formatted_header}\n{table}"