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
                'CashAndCashEquivalentsAtCarryingValue', 'ShortTermInvestments',
                'AccountsReceivableNet', 'InventoryNet', 'Inventory',
                'PrepaidExpenseAndOtherAssetsCurrent', 'PropertyPlantAndEquipmentNet',
                'Goodwill', 'IntangibleAssetsNet', 'MarketableSecuritiesCurrent',
                'MarketableSecuritiesNoncurrent', 'OtherAssetsCurrent', 'OtherAssetsNoncurrent'
            ]
            concept_groups['Liabilities'] = [
                'Liabilities', 'LiabilitiesCurrent', 'LiabilitiesNoncurrent',
                'AccountsPayable', 'AccountsPayableCurrent', 'AccruedLiabilitiesCurrent',
                'DeferredRevenueCurrent', 'DeferredRevenueNoncurrent',
                'LongTermDebt', 'LongTermDebtNoncurrent', 'DeferredTaxLiabilitiesNoncurrent',
                'CommercialPaper', 'ShortTermBorrowings', 'AccruedIncomeTaxesCurrent',
                'OtherLiabilitiesCurrent', 'OtherLiabilitiesNoncurrent'
            ]
            concept_groups['Equity'] = [
                'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
                'RetainedEarningsAccumulatedDeficit', 'CommonStockValue', 'AdditionalPaidInCapital',
                'TreasuryStockValue', 'AccumulatedOtherComprehensiveIncomeLossNetOfTax',
                'CommonStockParOrStatedValuePerShare', 'CommonStocksIncludingAdditionalPaidInCapital',
                'CommonStockSharesIssued', 'CommonStockSharesOutstanding',
                'StockholdersEquityAttributableToParent'
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
        found_concepts = set()  # Track found concepts for later reference
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
        normalized_data = self._normalize_api_data(financial_data, period_type, all_periods, num_periods, found_concepts, facts_data)
        logger.info(f"Retrieved data for {len(normalized_data['periods'])} periods: {normalized_data['periods']}")
        return normalized_data
    
    def _normalize_api_data(self, financial_data, period_type, all_periods, num_periods, found_concepts, facts_data=None):
        """
        Normalize financial data from SEC API into a structured format.
        
        Args:
            financial_data (dict): Extracted financial data
            period_type (str): 'annual' or 'quarterly' or 'ytd'
            all_periods (list): All period end dates found in the data
            num_periods (int): Number of periods to return
            found_concepts (set): Set of concepts found in the data
            facts_data (dict): Original facts data from the API
            
        Returns:
            dict: Normalized financial data by period
        """
        # Define the proper order of categories for balance sheet presentation
        category_order = {
            'Assets': 0,
            'Liabilities': 1,
            'Equity': 2
        }
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
        
        # Fill in data for each period - use sorted categories
        for category in sorted(financial_data.keys(), key=lambda x: category_order.get(x, 99)):
            for tag in financial_data[category]:
                # Create a human-readable label from the tag
                concept_name = tag.split(':')[-1]
                formatted_label = self._format_concept_name(concept_name)
                metric_key = f"{category}_{formatted_label}"
                
                normalized_data['metrics'][metric_key] = {
                    'values': {},
                    'category': category,
                    'tag': tag,
                    'display_name': formatted_label,
                    'order': self._get_concept_order(concept_name, category)
                }
                
                # Find values for each period
                for period in limited_periods:
                    value = None
                    
                    # Search for matching fact
                    for fact in financial_data[category][tag]:
                        if fact['end'] == period:
                            value = fact['val']
                            break
                    
                    # Deal with CommonStockValue specially (many companies report it differently)
                    if concept_name == "CommonStockValue" and value is None:
                        # Look for alternative tags for common stock
                        common_stock_alternatives = [
                            'CommonStocksIncludingAdditionalPaidInCapital',
                            'CommonStockParOrStatedValuePerShare',
                            'StockholdersEquityAttributableToParent'
                        ]
                        
                        for alt_concept in common_stock_alternatives:
                            if alt_concept in found_concepts:
                                for tag, tag_data in financial_data[category].items():
                                    if alt_concept in tag:
                                        for tag_fact in tag_data:
                                            if tag_fact['end'] == period and 'val' in tag_fact:
                                                value = tag_fact['val']
                                                break
                                        if value is not None:
                                            break
                                if value is not None:
                                    break
                        
                        # If still not found, look directly in the entity's financial data
                        if value is None and facts_data:
                            for taxonomy in ['us-gaap', 'ifrs-full']:
                                if taxonomy not in facts_data.get('facts', {}):
                                    continue
                                    
                                if value is not None:
                                    break
                                    
                                for tag_name in ['CommonStock', 'CapitalStock', 'IssuedCapital']:
                                    if tag_name in facts_data['facts'][taxonomy]:
                                        for unit_type, facts in facts_data['facts'][taxonomy][tag_name].get('units', {}).items():
                                            if unit_type == 'USD':
                                                for fact in facts:
                                                    if fact.get('end') == period:
                                                        value = fact.get('val')
                                                        break
                                                if value is not None:
                                                    break
                        
                        # If still not found, use 'N/A'
                        if value is None:
                            value = "N/A"  # Use N/A instead of blank for display purposes
                    
                    # For accounts payable, if total is missing, try to calculate it
                    if concept_name == "AccountsPayable" and value is None and "AccountsPayableCurrent" in found_concepts:
                        try:
                            # Look for current accounts payable in the same period
                            for other_tag, other_data in financial_data[category].items():
                                if "AccountsPayableCurrent" in other_tag:
                                    for other_fact in other_data:
                                        if other_fact['end'] == period and 'val' in other_fact:
                                            # Found current accounts payable, use it as a substitute
                                            value = other_fact['val']
                                            break
                        except Exception as e:
                            logger.warning(f"Error calculating total accounts payable: {e}")
                    
                    normalized_data['metrics'][metric_key]['values'][period] = value
        
        # Add fiscal year metadata to help with display
        normalized_data['metadata'] = {
            'fiscal_month': fiscal_month,
            'period_type': period_type
        }
        
        return normalized_data
    
    def _format_concept_name(self, concept_name):
        """
        Format a concept name into a human-readable label.
        
        Args:
            concept_name (str): Original concept name (e.g., 'AssetsCurrent')
            
        Returns:
            str: Formatted label (e.g., 'Current Assets')
        """
        # Special case handling for common concepts
        concept_labels = {
            'Assets': 'Total Assets',
            'AssetsCurrent': 'Current Assets',
            'AssetsNoncurrent': 'Non-Current Assets',
            'CashAndCashEquivalentsAtCarryingValue': 'Cash and Cash Equivalents',
            'Liabilities': 'Total Liabilities',
            'LiabilitiesCurrent': 'Current Liabilities',
            'LiabilitiesNoncurrent': 'Non-Current Liabilities',
            'AccountsPayable': 'Accounts Payable (Total)',
            'AccountsPayableCurrent': 'Accounts Payable (Current)',
            'LongTermDebt': 'Total Debt',
            'LongTermDebtNoncurrent': 'Long-Term Debt',
            'StockholdersEquity': 'Stockholders\' Equity',
            'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest': 'Total Equity',
            'RetainedEarningsAccumulatedDeficit': 'Retained Earnings',
            'CommonStockValue': 'Common Stock',
            'CommonStocksIncludingAdditionalPaidInCapital': 'Common Stock',
            'CommonStockParOrStatedValuePerShare': 'Common Stock',
            'StockholdersEquityAttributableToParent': 'Common Stock',
            'Revenues': 'Total Revenue',
            'RevenueFromContractWithCustomer': 'Revenue from Contracts',
            'RevenueFromContractWithCustomerExcludingAssessedTax': 'Revenue (Excluding Taxes)',
            'SalesRevenueNet': 'Net Sales Revenue',
            'NetIncomeLoss': 'Net Income',
            'ProfitLoss': 'Profit/Loss',
            'NetIncomeLossAvailableToCommonStockholdersBasic': 'Net Income to Common Stockholders',
            'OperatingIncomeLoss': 'Operating Income',
            'GrossProfit': 'Gross Profit',
            'EarningsPerShareBasic': 'EPS (Basic)',
            'EarningsPerShareDiluted': 'EPS (Diluted)',
            'NetCashProvidedByUsedInOperatingActivities': 'Net Cash from Operations',
            'NetCashProvidedByUsedInInvestingActivities': 'Net Cash from Investing',
            'NetCashProvidedByUsedInFinancingActivities': 'Net Cash from Financing'
        }
        
        if concept_name in concept_labels:
            return concept_labels[concept_name]
        
        # Generic formatting for other concepts
        # Insert spaces before capital letters
        formatted = re.sub(r'([a-z])([A-Z])', r'\1 \2', concept_name)
        # Handle acronyms (e.g., "EBITDA" shouldn't become "E B I T D A")
        formatted = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', formatted)
        
        return formatted
    
    def _get_concept_order(self, concept_name, category):
        """
        Determine the display order for a concept within its category.
        
        Args:
            concept_name (str): The concept name
            category (str): The category name
            
        Returns:
            int: The ordering value
        """
        # Standard ordering for Assets section - from most liquid to least liquid
        if category == 'Assets':
            order_map = {
                'Assets': 0,  # Total Assets comes first
                'AssetsCurrent': 10,  # Current Assets second
                'CashAndCashEquivalentsAtCarryingValue': 20,  # Cash and equivalents
                'ShortTermInvestments': 30,  # Short-term investments
                'AccountsReceivableNet': 40,  # Accounts receivable
                'Inventory': 50,  # Inventory
                'PrepaidExpenseAndOtherAssetsCurrent': 60,  # Prepaid expenses
                'AssetsNoncurrent': 100,  # Non-current assets last
                'PropertyPlantAndEquipmentNet': 110,  # PP&E
                'Goodwill': 120,  # Goodwill
                'IntangibleAssetsNet': 130  # Intangible assets
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for Liabilities section - current before non-current
        elif category == 'Liabilities':
            order_map = {
                'Liabilities': 0,  # Total Liabilities comes first
                'LiabilitiesCurrent': 10,  # Current Liabilities
                'AccountsPayableCurrent': 20,  # Accounts payable 
                'AccountsPayable': 25,  # Make sure this comes after AccountsPayableCurrent
                'AccruedLiabilitiesCurrent': 30,  # Accrued liabilities
                'DeferredRevenueCurrent': 40,  # Deferred revenue
                'LiabilitiesNoncurrent': 100,  # Non-current liabilities
                'LongTermDebt': 110,  # Long-term debt
                'LongTermDebtNoncurrent': 120,  # Non-current portion of long-term debt
                'DeferredRevenueNoncurrent': 130,  # Deferred revenue, non-current
                'DeferredTaxLiabilitiesNoncurrent': 140  # Deferred tax liabilities
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for Equity section
        elif category == 'Equity':
            order_map = {
                'StockholdersEquity': 0,  # Total Equity comes first
                'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest': 5,  # Total equity including non-controlling interest
                'CommonStockValue': 10,  # Common stock
                'CommonStocksIncludingAdditionalPaidInCapital': 10,  # Same priority as CommonStockValue
                'CommonStockParOrStatedValuePerShare': 10,  # Same priority as CommonStockValue
                'StockholdersEquityAttributableToParent': 10,  # Same priority as CommonStockValue
                'AdditionalPaidInCapital': 15,  # Additional paid-in capital
                'TreasuryStockValue': 18,  # Treasury stock
                'RetainedEarningsAccumulatedDeficit': 20,  # Retained earnings/accumulated deficit
                'AccumulatedOtherComprehensiveIncomeLossNetOfTax': 30  # AOCI
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for Income section
        elif category == 'Revenue' or category == 'Income':
            order_map = {
                'Revenues': 0,
                'SalesRevenueNet': 10,
                'GrossProfit': 20, 
                'OperatingIncomeLoss': 30,
                'NetIncomeLoss': 40
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for EPS section
        elif category == 'EPS':
            order_map = {
                'EarningsPerShareBasic': 0,
                'EarningsPerShareDiluted': 10
            }
            return order_map.get(concept_name, 50)  # Default order
        
        # Default ordering for other categories
        return 50
    
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
        found_concepts = set()  # Add this line to track found concepts
        
        for category in financial_data:
            for tag in financial_data[category]:
                concept_name = tag.split(':')[-1]
                found_concepts.add(concept_name)  # Add this line to track found concepts
                for fact in financial_data[category][tag]:
                    if 'end' in fact:
                        all_periods.append(fact['end'])
        
        return self._normalize_api_data(financial_data, period_type, all_periods, num_periods, found_concepts)