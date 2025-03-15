"""
Parser for extracting financial data from SEC XBRL and JSON APIs.
"""

import re
import logging
from datetime import datetime
from collections import Counter

from config.constants import XBRL_TAGS, ERROR_MESSAGES
from utils.cache import Cache

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize cache for parsed data
parser_cache = Cache("xbrl_parser")


class XBRLParser:
    """
    Parser for financial data from SEC APIs.
    """
    
    def __init__(self):
        """Initialize the parser."""
        pass
    
    def parse_company_facts(self, facts_data, statement_type=None, period_type='annual', num_periods=1):
        """
        Parse company facts JSON data from SEC API.
        
        Args:
            facts_data (dict): JSON data from SEC Company Facts API
            statement_type (str): Type of financial statement to extract
            period_type (str): 'annual', 'quarterly', or 'ytd'
            num_periods (int): Number of most recent periods to include
            
        Returns:
            dict: Normalized financial data by period
        """
        if not facts_data or 'facts' not in facts_data:
            logger.error("Invalid company facts data")
            return {}
        
        # Get relevant taxonomy based on statement type
        taxonomies = []
        if 'us-gaap' in facts_data['facts']:
            taxonomies.append('us-gaap')
        if 'ifrs-full' in facts_data['facts']:
            taxonomies.append('ifrs-full')
        
        if not taxonomies:
            logger.error("No supported taxonomies found in company facts")
            return {}
        
        # Define concept groups based on statement type
        concept_groups = {}
        if statement_type == 'BS' or statement_type == 'ALL':
            concept_groups['Assets'] = [
                'Assets', 'AssetsCurrent', 'AssetsNoncurrent',
                'CashAndCashEquivalentsAtCarryingValue'
            ]
            concept_groups['Liabilities'] = [
                'Liabilities', 'LiabilitiesCurrent', 'LiabilitiesNoncurrent',
                'AccountsPayable', 'AccountsPayableCurrent', 'LongTermDebt'
            ]
            concept_groups['Equity'] = [
                'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
                'RetainedEarningsAccumulatedDeficit', 'CommonStockValue'
            ]
        
        if statement_type == 'IS' or statement_type == 'ALL':
            concept_groups['Revenue'] = [
                'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                'SalesRevenueNet', 'RevenueFromContractWithCustomer'
            ]
            concept_groups['Income'] = [
                'NetIncomeLoss', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic',
                'OperatingIncomeLoss', 'GrossProfit'
            ]
            concept_groups['EPS'] = [
                'EarningsPerShareBasic', 'EarningsPerShareDiluted'
            ]
        
        if statement_type == 'CF' or statement_type == 'ALL':
            concept_groups['OperatingCashFlow'] = [
                'NetCashProvidedByUsedInOperatingActivities'
            ]
            concept_groups['InvestingCashFlow'] = [
                'NetCashProvidedByUsedInInvestingActivities'
            ]
            concept_groups['FinancingCashFlow'] = [
                'NetCashProvidedByUsedInFinancingActivities'
            ]
        
        # Extract financial data
        financial_data = {}
        found_concepts = set()
        all_periods = []
        
        for taxonomy in taxonomies:
            for group, concepts in concept_groups.items():
                if group not in financial_data:
                    financial_data[group] = {}
                
                for concept in concepts:
                    if concept in facts_data['facts'][taxonomy]:
                        concept_data = facts_data['facts'][taxonomy][concept]
                        units = concept_data.get('units', {})
                        
                        # Extract values for appropriate units (USD for monetary values, pure for ratios)
                        for unit_type, facts in units.items():
                            if ((unit_type == 'USD' and concept not in ['EarningsPerShareBasic', 'EarningsPerShareDiluted']) or
                                (unit_type == 'USD/shares' and concept in ['EarningsPerShareBasic', 'EarningsPerShareDiluted']) or
                                (unit_type == 'pure')):
                                
                                valid_facts = []
                                
                                for fact in facts:
                                    # Check if the fact has required properties
                                    if 'val' not in fact or 'end' not in fact:
                                        continue
                                    
                                    # Collect end dates for later fiscal year analysis
                                    all_periods.append(fact['end'])
                                    
                                    # Filter by period type
                                    if 'start' in fact:  # Duration fact
                                        # Estimate period length in days
                                        start_date = datetime.fromisoformat(fact['start'].replace('Z', '+00:00'))
                                        end_date = datetime.fromisoformat(fact['end'].replace('Z', '+00:00'))
                                        period_length = (end_date - start_date).days
                                        
                                        if period_type == 'annual' and period_length >= 350:  # Annual report (approximately 1 year)
                                            valid_facts.append(fact)
                                        elif period_type == 'quarterly' and 80 <= period_length <= 100:  # Quarterly report (approximately 3 months)
                                            valid_facts.append(fact)
                                        elif period_type == 'ytd':  # Year-to-date report (any duration)
                                            valid_facts.append(fact)
                                    else:  # Instant fact (typically for balance sheet items)
                                        valid_facts.append(fact)
                                
                                if valid_facts:
                                    tag = f"{taxonomy}:{concept}"
                                    financial_data[group][tag] = valid_facts
                                    found_concepts.add(concept)
        
        # Normalize the data
        normalized_data = self._normalize_api_data(financial_data, period_type, all_periods, num_periods)
        logger.info(f"Retrieved data for {len(normalized_data['periods'])} periods: {normalized_data['periods']}")
        return normalized_data
    
    def _normalize_api_data(self, financial_data, period_type, all_periods, num_periods):
        """
        Normalize financial data from SEC API into a structured format.
        
        Args:
            financial_data (dict): Extracted financial data
            period_type (str): 'annual' or 'quarterly' or 'ytd'
            all_periods (list): All period end dates found in the data
            num_periods (int): Number of periods to return
            
        Returns:
            dict: Normalized financial data by period
        """
        # Collect all unique periods
        periods = set()
        
        for category in financial_data:
            for tag in financial_data[category]:
                for fact in financial_data[category][tag]:
                    period_key = fact['end']
                    periods.add(period_key)
        
        # Detect company's fiscal year end month
        fiscal_month = self._detect_fiscal_year_end(all_periods)
        logger.info(f"Detected fiscal year end month: {fiscal_month}")
        
        # Filter periods by the fiscal year end month
        fiscal_periods = [p for p in periods if p.split('-')[1] == fiscal_month]
        
        # Sort periods in descending order (most recent first)
        sorted_periods = sorted(fiscal_periods if fiscal_periods else periods, reverse=True)
        
        # Limit to the number of periods requested
        limited_periods = sorted_periods[:num_periods]
        
        # Create normalized data structure
        normalized_data = {
            'periods': limited_periods,
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
                for period in limited_periods:
                    value = None
                    
                    # Search for matching fact
                    for fact in financial_data[category][tag]:
                        if fact['end'] == period:
                            value = fact['val']
                            break
                    
                    normalized_data['metrics'][metric_key]['values'][period] = value
        
        # Add fiscal year metadata to help with display
        normalized_data['metadata'] = {
            'fiscal_month': fiscal_month,
            'period_type': period_type
        }
        
        return normalized_data
    
    def _detect_fiscal_year_end(self, all_periods):
        """
        Detect the company's fiscal year end month based on the frequency of period end dates.
        
        Args:
            all_periods (list): List of all period end dates
            
        Returns:
            str: Two-digit month representing fiscal year end
        """
        # Extract months from period end dates
        months = [period.split('-')[1] for period in all_periods if '-' in period]
        
        # Count occurrences of each month
        month_counter = Counter(months)
        
        # Find the most common month for period endings
        most_common_month = month_counter.most_common(1)
        
        # Return the most common month, or '12' (December) as default
        return most_common_month[0][0] if most_common_month else '12'
    
    def normalize_financial_data(self, financial_data, period_type='annual', num_periods=1):
        """
        Normalize financial data into a structured format.
        Maintained for compatibility with existing code.
        
        Args:
            financial_data (dict): Parsed financial data
            period_type (str): 'annual' or 'quarterly'
            num_periods (int): Number of periods to return
            
        Returns:
            dict: Normalized financial data by period
        """
        # Extract all periods for fiscal year detection
        all_periods = []
        for category in financial_data:
            for tag in financial_data[category]:
                for fact in financial_data[category][tag]:
                    if 'end' in fact:
                        all_periods.append(fact['end'])
        
        return self._normalize_api_data(financial_data, period_type, all_periods, num_periods)