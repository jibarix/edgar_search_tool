"""
Parser for extracting financial data from SEC XBRL and JSON APIs.
"""

import re
import logging
from datetime import datetime

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
    
    def parse_company_facts(self, facts_data, statement_type=None, period_type='annual'):
        """
        Parse company facts JSON data from SEC API.
        
        Args:
            facts_data (dict): JSON data from SEC Company Facts API
            statement_type (str): Type of financial statement to extract
            period_type (str): 'annual', 'quarterly', or 'ytd'
            
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
        return self._normalize_api_data(financial_data, period_type)
    
    def _normalize_api_data(self, financial_data, period_type):
        """
        Normalize financial data from SEC API into a structured format.
        
        Args:
            financial_data (dict): Extracted financial data
            period_type (str): 'annual' or 'quarterly' or 'ytd'
            
        Returns:
            dict: Normalized financial data by period
        """
        # Collect all periods first
        periods = set()
        
        for category in financial_data:
            for tag in financial_data[category]:
                for fact in financial_data[category][tag]:
                    period_key = fact['end']
                    periods.add(period_key)
        
        # Sort periods
        sorted_periods = sorted(list(periods))
        
        # Filter periods based on period_type
        if period_type.lower() == 'annual':
            # For annual, prioritize December 31 dates if available
            dec_periods = [p for p in sorted_periods if p.endswith('-12-31')]
            if dec_periods:
                filtered_periods = dec_periods
            else:
                # If no December dates, use all periods
                filtered_periods = sorted_periods
        else:
            # For quarterly or ytd, keep all periods
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
                        if fact['end'] == period:
                            value = fact['val']
                            break
                    
                    normalized_data['metrics'][metric_key]['values'][period] = value
        
        return normalized_data
    
    def normalize_financial_data(self, financial_data, period_type='annual'):
        """
        Normalize financial data into a structured format.
        Maintained for compatibility with existing code.
        
        Args:
            financial_data (dict): Parsed financial data
            period_type (str): 'annual' or 'quarterly'
            
        Returns:
            dict: Normalized financial data by period
        """
        return self._normalize_api_data(financial_data, period_type)