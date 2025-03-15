"""
XBRL parser for extracting financial data from SEC filings.
"""

import re
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

from config.constants import XBRL_TAGS, ERROR_MESSAGES
from utils.cache import Cache

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize cache for parsed data
parser_cache = Cache("xbrl_parser")


class XBRLParser:
    """
    Parser for XBRL financial data.
    """
    
    def __init__(self):
        """Initialize the XBRL parser."""
        self.ns_map = {}
    
    def _extract_namespaces(self, xml_content):
        """
        Extract namespace mappings from XBRL document.
        
        Args:
            xml_content (str): XML content of the XBRL document
            
        Returns:
            dict: Namespace prefix to URI mapping
        """
        ns_pattern = re.compile(r'xmlns:([a-zA-Z0-9]+)=[\'"](.*?)[\'"]')
        matches = ns_pattern.findall(xml_content)
        
        ns_map = {}
        for prefix, uri in matches:
            ns_map[prefix] = uri
        
        return ns_map
    
    def _resolve_tag(self, tag_name):
        """
        Resolve a tag name with namespace prefix to tag with URI.
        
        Args:
            tag_name (str): Tag name with namespace prefix (e.g., 'us-gaap:Assets')
            
        Returns:
            str: Tag name with namespace URI in Clark notation
        """
        if ':' not in tag_name:
            return tag_name
            
        prefix, local_name = tag_name.split(':', 1)
        
        if prefix not in self.ns_map:
            return tag_name
            
        return f"{{{self.ns_map[prefix]}}}{local_name}"
    
    def _get_context_dates(self, root):
        """
        Extract context periods from XBRL document.
        
        Args:
            root (ElementTree.Element): Root element of XBRL document
            
        Returns:
            dict: Context ID to period mapping
        """
        context_dates = {}
        
        # Find all context elements
        for context in root.findall(".//*[@id]"):
            context_id = context.get('id')
            
            if context_id:
                # Find period element
                period = context.find(".//*[local-name()='period']")
                
                if period is not None:
                    # Check for instant period
                    instant = period.find(".//*[local-name()='instant']")
                    if instant is not None and instant.text:
                        date_str = instant.text.strip()
                        try:
                            date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            context_dates[context_id] = {
                                'type': 'instant',
                                'date': date,
                                'value': date_str
                            }
                            continue
                        except ValueError:
                            pass
                    
                    # Check for start/end period
                    start_date = period.find(".//*[local-name()='startDate']")
                    end_date = period.find(".//*[local-name()='endDate']")
                    
                    if start_date is not None and start_date.text and end_date is not None and end_date.text:
                        start_str = start_date.text.strip()
                        end_str = end_date.text.strip()
                        
                        try:
                            start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                            end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                            
                            context_dates[context_id] = {
                                'type': 'duration',
                                'start_date': start,
                                'end_date': end,
                                'start_value': start_str,
                                'end_value': end_str
                            }
                        except ValueError:
                            pass
        
        return context_dates
    
    def _get_fact_value(self, fact_element):
        """
        Extract a numeric value from a fact element.
        
        Args:
            fact_element (ElementTree.Element): XBRL fact element
            
        Returns:
            float or None: Numeric value if parseable, None otherwise
        """
        if fact_element is None or fact_element.text is None:
            return None
            
        # Get the text value
        value_text = fact_element.text.strip()
        
        # Check for decimals attribute
        decimals = fact_element.get('decimals')
        
        try:
            # Convert to float
            value = float(value_text)
            
            # Apply scaling based on decimals if provided
            if decimals is not None and decimals != 'INF':
                try:
                    scale = int(decimals)
                    if scale < 0:
                        # If negative decimals (e.g., -3 for thousands), scale the value
                        value = value * (10 ** abs(scale))
                except ValueError:
                    pass
            
            return value
            
        except ValueError:
            return None
    
    def _find_period_facts(self, root, context_dates, tag_name, period_type=None, date=None):
        """
        Find facts for a specific tag and period.
        
        Args:
            root (ElementTree.Element): Root element of XBRL document
            context_dates (dict): Context ID to period mapping
            tag_name (str): XBRL tag name to search for
            period_type (str): 'instant' or 'duration'
            date (datetime): Target date for filtering
            
        Returns:
            list: List of matching fact elements
        """
        tag = self._resolve_tag(tag_name)
        xpath = f".//{tag}"
        
        facts = []
        for fact in root.findall(xpath):
            context_ref = fact.get('contextRef')
            
            if not context_ref or context_ref not in context_dates:
                continue
                
            context = context_dates[context_ref]
            
            # Filter by period type if specified
            if period_type and context.get('type') != period_type:
                continue
                
            # Filter by date if specified
            if date:
                if context.get('type') == 'instant' and context.get('date') != date:
                    continue
                elif context.get('type') == 'duration' and context.get('end_date') != date:
                    continue
            
            facts.append(fact)
        
        return facts
    
    def parse_xbrl(self, xbrl_content):
        """
        Parse XBRL document and extract financial data.
        
        Args:
            xbrl_content (str): XBRL document content
            
        Returns:
            dict: Extracted financial data
        """
        if not xbrl_content:
            logger.error("Empty XBRL content")
            return {}
            
        # Check cache
        cache_key = f"parsed_data_{hash(xbrl_content)}"
        cached_data = parser_cache.get(cache_key)
        if cached_data:
            return cached_data
        
        try:
            # Extract namespaces
            self.ns_map = self._extract_namespaces(xbrl_content)
            
            # Parse the XML
            root = ET.fromstring(xbrl_content)
            
            # Get context periods
            context_dates = self._get_context_dates(root)
            
            # Extract financial data for each category and tag
            financial_data = {}
            
            for category, tags in XBRL_TAGS.items():
                financial_data[category] = {}
                
                for tag in tags:
                    # Find all facts for this tag
                    facts = []
                    for fact in root.findall(".//*"):
                        if fact.tag.endswith(tag.split(':')[-1]):
                            context_ref = fact.get('contextRef')
                            
                            if not context_ref or context_ref not in context_dates:
                                continue
                                
                            # Get value and context period
                            value = self._get_fact_value(fact)
                            context = context_dates[context_ref]
                            
                            if value is not None:
                                fact_data = {
                                    'value': value,
                                    'context': context
                                }
                                
                                # Add units if available
                                unit_ref = fact.get('unitRef')
                                if unit_ref:
                                    fact_data['unit'] = unit_ref
                                    
                                facts.append(fact_data)
                    
                    if facts:
                        financial_data[category][tag] = facts
            
            # Sort facts by date
            for category in financial_data:
                for tag in financial_data[category]:
                    financial_data[category][tag].sort(
                        key=lambda x: x['context']['date'] if x['context']['type'] == 'instant' 
                        else x['context']['end_date']
                    )
            
            # Cache the parsed data
            parser_cache.set(cache_key, financial_data)
            
            return financial_data
            
        except ET.ParseError as e:
            logger.error(f"Error parsing XBRL document: {e}")
            return {}
            
        except Exception as e:
            logger.error(f"Error processing XBRL document: {e}")
            return {}
    
    def extract_financial_statement(self, xbrl_content, statement_type):
        """
        Extract a specific financial statement from XBRL document.
        
        Args:
            xbrl_content (str): XBRL document content
            statement_type (str): Type of financial statement to extract
            
        Returns:
            dict: Financial statement data
        """
        # Parse full XBRL data
        financial_data = self.parse_xbrl(xbrl_content)
        
        if not financial_data:
            return {}
        
        # Filter data based on statement type
        statement_data = {}
        
        if statement_type.upper() == 'BS':
            # Balance Sheet
            categories = ['Assets', 'Liabilities', 'StockholdersEquity']
        elif statement_type.upper() == 'IS':
            # Income Statement
            categories = ['Revenue', 'NetIncome', 'EPS']
        elif statement_type.upper() == 'CF':
            # Cash Flow Statement
            categories = ['OperatingCashFlow', 'InvestingCashFlow', 'FinancingCashFlow']
        elif statement_type.upper() == 'ALL':
            # All statements
            return financial_data
        else:
            logger.warning(f"Unsupported statement type: {statement_type}")
            return {}
        
        # Extract relevant categories
        for category in categories:
            if category in financial_data:
                statement_data[category] = financial_data[category]
        
        return statement_data
    
    def normalize_financial_data(self, financial_data, period_type='annual'):
        """
        Normalize financial data into a structured format.
        
        Args:
            financial_data (dict): Parsed financial data
            period_type (str): 'annual' or 'quarterly'
            
        Returns:
            dict: Normalized financial data by period
        """
        if not financial_data:
            return {}
        
        # Collect all periods first
        periods = set()
        
        for category in financial_data:
            for tag in financial_data[category]:
                for fact in financial_data[category][tag]:
                    context = fact['context']
                    
                    if context['type'] == 'instant':
                        period_key = context['value']
                    else:
                        period_key = context['end_value']
                    
                    periods.add(period_key)
        
        # Sort periods
        sorted_periods = sorted(periods)
        
        # Filter periods based on period_type
        if period_type.lower() == 'annual':
            # For annual, keep only year-end periods (typically Dec 31)
            filtered_periods = [p for p in sorted_periods if p.endswith('-12-31')]
        else:
            # For quarterly, keep all periods
            filtered_periods = sorted_periods
        
        # Create normalized data structure
        normalized_data = {
            'periods': filtered_periods,
            'metrics': {}
        }
        
        # Fill in data for each period
        for category in financial_data:
            for tag in financial_data[category]:
                # Create a simplified tag name
                simple_tag = tag.split(':')[-1]
                metric_key = f"{category}_{simple_tag}"
                
                normalized_data['metrics'][metric_key] = {
                    'values': {},
                    'category': category,
                    'tag': tag
                }
                
                # Find values for each period
                for period in filtered_periods:
                    value = None
                    
                    # Search for matching fact
                    for fact in financial_data[category][tag]:
                        context = fact['context']
                        
                        if (context['type'] == 'instant' and context['value'] == period) or \
                           (context['type'] == 'duration' and context['end_value'] == period):
                            value = fact['value']
                            break
                    
                    normalized_data['metrics'][metric_key]['values'][period] = value
        
        return normalized_data