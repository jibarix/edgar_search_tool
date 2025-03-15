"""
Enhanced parser for extracting financial data from SEC XBRL and JSON APIs.
"""

import re
import logging
from datetime import datetime
from collections import Counter, defaultdict

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
        
        # Get the entity information
        entity_name = facts_data.get('entityName', '')
        logger.info(f"Processing XBRL data for {entity_name}")
        
        # Define concept groups based on statement type
        concept_groups = {}
        if statement_type == 'BS' or statement_type == 'ALL':
            concept_groups['Assets'] = [
                'Assets', 'AssetsCurrent', 'AssetsNoncurrent',
                'CashAndCashEquivalentsAtCarryingValue', 'ShortTermInvestments',
                'AccountsReceivableNet', 'InventoryNet', 'Inventory',
                'PrepaidExpenseAndOtherAssetsCurrent', 'PropertyPlantAndEquipmentNet',
                'Goodwill', 'IntangibleAssetsNet', 'MarketableSecuritiesCurrent',
                'MarketableSecuritiesNoncurrent', 'OtherAssetsCurrent', 'OtherAssetsNoncurrent',
                # Add more asset concepts that companies might use
                'CashAndCashEquivalents', 'AccountsReceivable', 'CurrentAssets',
                'NoncurrentAssets', 'TotalAssets', 'AvailableForSaleSecurities',
                'TradingSecurities', 'InvestmentsShortTerm', 'InvestmentsLongTerm'
            ]
            concept_groups['Liabilities'] = [
                'Liabilities', 'LiabilitiesCurrent', 'LiabilitiesNoncurrent',
                'AccountsPayable', 'AccountsPayableCurrent', 'AccruedLiabilitiesCurrent',
                'DeferredRevenueCurrent', 'DeferredRevenueNoncurrent',
                'LongTermDebt', 'LongTermDebtNoncurrent', 'DeferredTaxLiabilitiesNoncurrent',
                'CommercialPaper', 'ShortTermBorrowings', 'AccruedIncomeTaxesCurrent',
                'OtherLiabilitiesCurrent', 'OtherLiabilitiesNoncurrent',
                # Add more liability concepts
                'CurrentLiabilities', 'NoncurrentLiabilities', 'TotalLiabilities',
                'ShortTermDebt', 'DeferredRevenue', 'AccruedLiabilities',
                'AccruedExpenses', 'NotesPayable', 'DebtCurrent',
                'DebtLongTerm', 'LineOfCredit'
            ]
            concept_groups['Equity'] = [
                'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
                'RetainedEarningsAccumulatedDeficit', 'CommonStockValue', 'AdditionalPaidInCapital',
                'TreasuryStockValue', 'AccumulatedOtherComprehensiveIncomeLossNetOfTax',
                'CommonStockParOrStatedValuePerShare', 'CommonStocksIncludingAdditionalPaidInCapital',
                'CommonStockSharesIssued', 'CommonStockSharesOutstanding',
                'StockholdersEquityAttributableToParent',
                # Add more equity concepts
                'RetainedEarnings', 'TreasuryStock', 'TotalEquity',
                'EquityAttributableToParent', 'EquityAttributableToNoncontrollingInterest',
                'PreferredStockValue', 'PreferredStockSharesIssued'
            ]
        
        if statement_type == 'IS' or statement_type == 'ALL':
            concept_groups['Revenue'] = [
                'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                'SalesRevenueNet', 'RevenueFromContractWithCustomer',
                # Add more revenue concepts
                'TotalRevenue', 'NetSales', 'ServiceRevenue', 'ProductRevenue',
                'InterestAndDividendIncomeOperating', 'RealEstateRevenueNet',
                'AdvertisingRevenue', 'SubscriptionRevenue'
            ]
            concept_groups['Income'] = [
                'NetIncomeLoss', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic',
                'OperatingIncomeLoss', 'GrossProfit',
                # Add more income concepts
                'IncomeLossFromContinuingOperationsBeforeIncomeTaxes',
                'IncomeTaxExpenseBenefit', 'NetIncome', 'NetLoss',
                'ComprehensiveIncomeNetOfTax', 'CostOfRevenue', 
                'CostOfGoodsAndServicesSold', 'ResearchAndDevelopmentExpense',
                'SellingGeneralAndAdministrativeExpense', 'InterestExpense'
            ]
            concept_groups['EPS'] = [
                'EarningsPerShareBasic', 'EarningsPerShareDiluted',
                # Add more EPS concepts
                'IncomeLossFromContinuingOperationsPerBasicShare',
                'IncomeLossFromContinuingOperationsPerDilutedShare',
                'IncomeLossFromDiscontinuedOperationsNetOfTaxPerBasicShare',
                'IncomeLossFromDiscontinuedOperationsNetOfTaxPerDilutedShare'
            ]
        
        if statement_type == 'CF' or statement_type == 'ALL':
            concept_groups['OperatingCashFlow'] = [
                'NetCashProvidedByUsedInOperatingActivities',
                # Add more operating cash flow concepts
                'OperatingCashFlow', 'NetCashProvidedByOperatingActivities',
                'NetCashUsedInOperatingActivities', 'CashFlowsFromOperatingActivities'
            ]
            concept_groups['InvestingCashFlow'] = [
                'NetCashProvidedByUsedInInvestingActivities',
                # Add more investing cash flow concepts
                'InvestingCashFlow', 'NetCashProvidedByInvestingActivities',
                'NetCashUsedInInvestingActivities', 'CashFlowsFromInvestingActivities',
                'PaymentsToAcquirePropertyPlantAndEquipment',
                'PaymentsToAcquireBusinessesNetOfCashAcquired'
            ]
            concept_groups['FinancingCashFlow'] = [
                'NetCashProvidedByUsedInFinancingActivities',
                # Add more financing cash flow concepts
                'FinancingCashFlow', 'NetCashProvidedByFinancingActivities',
                'NetCashUsedInFinancingActivities', 'CashFlowsFromFinancingActivities',
                'PaymentsOfDividends', 'PaymentsForRepurchaseOfCommonStock',
                'ProceedsFromIssuanceOfLongTermDebt'
            ]
        
        # Extract financial data
        financial_data = {}
        found_concepts = set()  # Track found concepts for later reference
        all_periods = []
        
        # Create a mapping of all concepts to their values
        concept_values = defaultdict(list)
        
        for taxonomy in taxonomies:
            for concept in facts_data['facts'].get(taxonomy, {}):
                # Store the concept for later reference
                found_concepts.add(concept)
                
                # Extract units data
                units = facts_data['facts'][taxonomy][concept].get('units', {})
                
                # Extract values for appropriate units
                for unit_type, facts in units.items():
                    # Skip non-monetary units for financial statement values
                    if unit_type not in ['USD', 'USD/shares', 'pure']:
                        continue
                        
                    for fact in facts:
                        if 'val' not in fact or 'end' not in fact:
                            continue
                            
                        # Store the period end date
                        all_periods.append(fact['end'])
                        
                        # Store the value with its metadata
                        concept_values[concept].append({
                            'val': fact['val'],
                            'end': fact['end'],
                            'start': fact.get('start'),
                            'unit': unit_type,
                            'filed': fact.get('filed'),
                            'accn': fact.get('accn')
                        })
        
        # Now organize the data by concept groups
        for group, concepts in concept_groups.items():
            if group not in financial_data:
                financial_data[group] = {}
                
            for concept in concepts:
                if concept in concept_values:
                    taxonomy = 'us-gaap' if concept in facts_data['facts'].get('us-gaap', {}) else 'ifrs-full'
                    tag = f"{taxonomy}:{concept}"
                    financial_data[group][tag] = concept_values[concept]
        
        # Normalize the data
        normalized_data = self._normalize_api_data(
            financial_data, 
            period_type, 
            all_periods, 
            num_periods, 
            found_concepts, 
            facts_data
        )
        
        if normalized_data and normalized_data.get('periods'):
            logger.info(f"Retrieved data for {len(normalized_data['periods'])} periods: {normalized_data['periods']}")
            return normalized_data
        else:
            logger.warning("No periods found in normalized data")
            return {}
    
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
            'Equity': 2,
            'Revenue': 3,
            'Income': 4,
            'EPS': 5,
            'OperatingCashFlow': 6,
            'InvestingCashFlow': 7,
            'FinancingCashFlow': 8
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
        
        # Filter periods based on period_type
        filtered_periods = []
        for period in periods:
            try:
                end_date = datetime.fromisoformat(period.replace('Z', '+00:00'))
                
                # For annual reports, check if it's a fiscal year end
                if period_type == 'annual' and period.split('-')[1] == fiscal_month:
                    filtered_periods.append(period)
                # For quarterly reports, include all quarters
                elif period_type == 'quarterly':
                    filtered_periods.append(period)
                # For YTD reports, include all periods
                elif period_type == 'ytd':
                    filtered_periods.append(period)
            except (ValueError, IndexError):
                continue
        
        # If we didn't find any periods matching the fiscal year end,
        # use all periods as a fallback
        if not filtered_periods:
            filtered_periods = list(periods)
            logger.warning(f"No periods matched fiscal year end month {fiscal_month}, using all periods")
        
        # Sort periods in descending order (most recent first)
        sorted_periods = sorted(filtered_periods, reverse=True)
        
        # Limit to the number of periods requested
        limited_periods = sorted_periods[:num_periods]
        
        if not limited_periods:
            logger.warning("No periods available after filtering")
            return None
        
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
            'CashAndCashEquivalents': 'Cash and Cash Equivalents',
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
            'RetainedEarnings': 'Retained Earnings',
            'CommonStockValue': 'Common Stock',
            'CommonStocksIncludingAdditionalPaidInCapital': 'Common Stock',
            'CommonStockParOrStatedValuePerShare': 'Common Stock',
            'StockholdersEquityAttributableToParent': 'Common Stock',
            'Revenues': 'Total Revenue',
            'TotalRevenue': 'Total Revenue',
            'RevenueFromContractWithCustomer': 'Revenue from Contracts',
            'RevenueFromContractWithCustomerExcludingAssessedTax': 'Revenue (Excluding Taxes)',
            'SalesRevenueNet': 'Net Sales Revenue',
            'NetSales': 'Net Sales',
            'NetIncomeLoss': 'Net Income',
            'NetIncome': 'Net Income',
            'ProfitLoss': 'Profit/Loss',
            'NetIncomeLossAvailableToCommonStockholdersBasic': 'Net Income to Common Stockholders',
            'OperatingIncomeLoss': 'Operating Income',
            'GrossProfit': 'Gross Profit',
            'EarningsPerShareBasic': 'EPS (Basic)',
            'EarningsPerShareDiluted': 'EPS (Diluted)',
            'NetCashProvidedByUsedInOperatingActivities': 'Net Cash from Operations',
            'OperatingCashFlow': 'Net Cash from Operations',
            'NetCashProvidedByUsedInInvestingActivities': 'Net Cash from Investing',
            'InvestingCashFlow': 'Net Cash from Investing',
            'NetCashProvidedByUsedInFinancingActivities': 'Net Cash from Financing',
            'FinancingCashFlow': 'Net Cash from Financing',
            'CostOfRevenue': 'Cost of Revenue',
            'CostOfGoodsAndServicesSold': 'Cost of Goods Sold',
            'ResearchAndDevelopmentExpense': 'R&D Expenses',
            'SellingGeneralAndAdministrativeExpense': 'SG&A Expenses',
            'InterestExpense': 'Interest Expense',
            'IncomeTaxExpenseBenefit': 'Income Tax Expense'
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
                'TotalAssets': 0,  # Alternative name
                'AssetsCurrent': 10,  # Current Assets second
                'CurrentAssets': 10,  # Alternative name
                'CashAndCashEquivalentsAtCarryingValue': 20,  # Cash and equivalents
                'CashAndCashEquivalents': 20,  # Alternative name
                'ShortTermInvestments': 30,  # Short-term investments
                'InvestmentsShortTerm': 30,  # Alternative name
                'AccountsReceivableNet': 40,  # Accounts receivable
                'AccountsReceivable': 40,  # Alternative name
                'Inventory': 50,  # Inventory
                'InventoryNet': 50,  # Alternative name
                'PrepaidExpenseAndOtherAssetsCurrent': 60,  # Prepaid expenses
                'AssetsNoncurrent': 100,  # Non-current assets last
                'NoncurrentAssets': 100,  # Alternative name
                'PropertyPlantAndEquipmentNet': 110,  # PP&E
                'Goodwill': 120,  # Goodwill
                'IntangibleAssetsNet': 130  # Intangible assets
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for Liabilities section - current before non-current
        elif category == 'Liabilities':
            order_map = {
                'Liabilities': 0,  # Total Liabilities comes first
                'TotalLiabilities': 0,  # Alternative name
                'LiabilitiesCurrent': 10,  # Current Liabilities
                'CurrentLiabilities': 10,  # Alternative name
                'AccountsPayableCurrent': 20,  # Accounts payable 
                'AccountsPayable': 25,  # Make sure this comes after AccountsPayableCurrent
                'AccruedLiabilitiesCurrent': 30,  # Accrued liabilities
                'AccruedLiabilities': 30,  # Alternative name
                'DeferredRevenueCurrent': 40,  # Deferred revenue
                'DeferredRevenue': 45,  # Deferred revenue (general)
                'LiabilitiesNoncurrent': 100,  # Non-current liabilities
                'NoncurrentLiabilities': 100,  # Alternative name
                'LongTermDebt': 110,  # Long-term debt
                'DebtLongTerm': 110,  # Alternative name
                'LongTermDebtNoncurrent': 120,  # Non-current portion of long-term debt
                'DeferredRevenueNoncurrent': 130,  # Deferred revenue, non-current
                'DeferredTaxLiabilitiesNoncurrent': 140  # Deferred tax liabilities
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for Equity section
        elif category == 'Equity':
            order_map = {
                'StockholdersEquity': 0,  # Total Equity comes first
                'TotalEquity': 0,  # Alternative name
                'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest': 5,  # Total equity including non-controlling interest
                'EquityAttributableToParent': 8,  # Equity attributable to parent
                'CommonStockValue': 10,  # Common stock
                'CommonStocksIncludingAdditionalPaidInCapital': 10,  # Same priority as CommonStockValue
                'CommonStockParOrStatedValuePerShare': 10,  # Same priority as CommonStockValue
                'StockholdersEquityAttributableToParent': 10,  # Same priority as CommonStockValue
                'AdditionalPaidInCapital': 15,  # Additional paid-in capital
                'TreasuryStockValue': 18,  # Treasury stock
                'TreasuryStock': 18,  # Alternative name
                'RetainedEarningsAccumulatedDeficit': 20,  # Retained earnings/accumulated deficit
                'RetainedEarnings': 20,  # Alternative name
                'AccumulatedOtherComprehensiveIncomeLossNetOfTax': 30  # AOCI
            }
            return order_map.get(concept_name, 50)  # Default order
            
        # Standard ordering for Income section
        elif category == 'Revenue' or category == 'Income':
            order_map = {
                'Revenues': 0,
                'TotalRevenue': 0,
                'SalesRevenueNet': 10,
                'NetSales': 10,
                'RevenueFromContractWithCustomer': 15,
                'GrossProfit': 20, 
                'CostOfRevenue': 25,
                'CostOfGoodsAndServicesSold': 30,
                'SellingGeneralAndAdministrativeExpense': 35,
                'ResearchAndDevelopmentExpense': 40,
                'OperatingIncomeLoss': 45,
                'InterestExpense': 50,
                'IncomeTaxExpenseBenefit': 55,
                'NetIncomeLoss': 60,
                'NetIncome': 60
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
        months = []
        for period in all_periods:
            try:
                month = period.split('-')[1]
                if month.isdigit() and 1 <= int(month) <= 12:
                    months.append(month)
            except (IndexError, ValueError):
                continue
        
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
        found_concepts = set()
        
        for category in financial_data:
            for tag in financial_data[category]:
                concept_name = tag.split(':')[-1]
                found_concepts.add(concept_name)
                for fact in financial_data[category][tag]:
                    if 'end' in fact:
                        all_periods.append(fact['end'])
        
        return self._normalize_api_data(financial_data, period_type, all_periods, num_periods, found_concepts)