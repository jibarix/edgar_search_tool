"""
Enhanced parser for extracting financial data from SEC XBRL and JSON APIs.
Uses LLM-powered tag classification for comprehensive concept coverage.
"""

import re
import logging
from datetime import datetime
from collections import Counter, defaultdict

from config.constants import XBRL_TAGS, ERROR_MESSAGES
from edgar.tag_classifier import TagClassifier
from utils.cache import Cache

logger = logging.getLogger(__name__)
parser_cache = Cache("xbrl_parser")


class XBRLParser:
    """Parser for financial data from SEC APIs."""

    def __init__(self):
        self.classifier = TagClassifier()

    def parse_company_facts(self, facts_data, statement_type=None, period_type='annual', num_periods=1):
        """
        Parse company facts JSON data from SEC API.

        Args:
            facts_data: JSON data from SEC Company Facts API
            statement_type: Type of financial statement (BS, IS, CF, ALL)
            period_type: 'annual', 'quarterly', or 'ytd'
            num_periods: Number of most recent periods to include

        Returns:
            dict: Normalized financial data by period
        """
        if not facts_data or 'facts' not in facts_data:
            logger.error("Invalid company facts data")
            return {}

        taxonomies = []
        if 'us-gaap' in facts_data['facts']:
            taxonomies.append('us-gaap')
        if 'ifrs-full' in facts_data['facts']:
            taxonomies.append('ifrs-full')

        if not taxonomies:
            logger.error("No supported taxonomies found in company facts")
            return {}

        entity_name = facts_data.get('entityName', '')
        logger.info(f"Processing XBRL data for {entity_name}")

        # Collect ALL concept names from the data
        all_concept_names = set()
        for taxonomy in taxonomies:
            all_concept_names.update(facts_data['facts'].get(taxonomy, {}).keys())

        logger.info(f"Found {len(all_concept_names)} unique concepts in data")

        # Classify all concepts at once (uses cache, only calls LLM for unknowns)
        classifications = self.classifier.classify_tags(
            list(all_concept_names),
            statement_type=statement_type
        )

        logger.info(f"Classified {len(classifications)} concepts for statement type '{statement_type}'")

        # Extract values for classified concepts
        concept_values = defaultdict(list)
        all_periods = []

        for taxonomy in taxonomies:
            for concept, concept_data in facts_data['facts'].get(taxonomy, {}).items():
                if concept not in classifications:
                    continue

                units = concept_data.get('units', {})
                for unit_type, facts in units.items():
                    if unit_type not in ['USD', 'USD/shares', 'pure', 'shares']:
                        continue

                    for fact in facts:
                        if 'val' not in fact or 'end' not in fact:
                            continue

                        all_periods.append(fact['end'])
                        concept_values[concept].append({
                            'val': fact['val'],
                            'end': fact['end'],
                            'start': fact.get('start'),
                            'unit': unit_type,
                            'filed': fact.get('filed'),
                            'accn': fact.get('accn'),
                        })

        # Build financial_data grouped by category
        financial_data = {}
        concept_units = {}
        for concept, info in classifications.items():
            if concept not in concept_values:
                continue
            category = info['category']
            if category not in financial_data:
                financial_data[category] = {}
            taxonomy = 'us-gaap' if concept in facts_data['facts'].get('us-gaap', {}) else 'ifrs-full'
            tag = f"{taxonomy}:{concept}"
            financial_data[category][tag] = concept_values[concept]
            # Track dominant unit for this concept
            units_seen = [v['unit'] for v in concept_values[concept]]
            concept_units[concept] = max(set(units_seen), key=units_seen.count) if units_seen else 'USD'

        # Normalize
        normalized = self._normalize_api_data(
            financial_data, period_type, all_periods,
            num_periods, classifications, concept_units
        )

        if normalized and normalized.get('periods'):
            logger.info(f"Retrieved data for {len(normalized['periods'])} periods: {normalized['periods']}")
            return normalized
        else:
            logger.warning("No periods found in normalized data")
            return {}

    def _normalize_api_data(self, financial_data, period_type, all_periods, num_periods, classifications, concept_units=None):
        """
        Normalize financial data into a structured format.

        Args:
            financial_data: Extracted financial data grouped by category
            period_type: 'annual', 'quarterly', or 'ytd'
            all_periods: All period end dates found in the data
            num_periods: Number of periods to return
            classifications: dict of concept_name -> classification info
            concept_units: dict of concept_name -> unit string (USD, USD/shares, etc.)

        Returns:
            dict: Normalized financial data by period
        """
        if concept_units is None:
            concept_units = {}
        category_order = {
            'Assets': 0, 'Liabilities': 1, 'Equity': 2,
            'Revenue': 3, 'Income': 4, 'EPS': 5,
            'OperatingCashFlow': 6, 'InvestingCashFlow': 7, 'FinancingCashFlow': 8,
        }

        # Collect all unique periods from the data
        periods = set()
        for category in financial_data:
            for tag in financial_data[category]:
                for fact in financial_data[category][tag]:
                    periods.add(fact['end'])

        fiscal_month = self._detect_fiscal_year_end(all_periods)
        logger.info(f"Detected fiscal year end month: {fiscal_month}")

        # Filter periods
        filtered_periods = []
        for period in periods:
            try:
                if period_type == 'annual' and period.split('-')[1] == fiscal_month:
                    filtered_periods.append(period)
                elif period_type == 'quarterly':
                    filtered_periods.append(period)
                elif period_type == 'ytd':
                    filtered_periods.append(period)
            except (ValueError, IndexError):
                continue

        if not filtered_periods:
            filtered_periods = list(periods)
            logger.warning(f"No periods matched fiscal year end month {fiscal_month}, using all periods")

        sorted_periods = sorted(filtered_periods, reverse=True)
        limited_periods = sorted_periods[:num_periods]

        if not limited_periods:
            logger.warning("No periods available after filtering")
            return None

        normalized_data = {
            'periods': limited_periods,
            'metrics': {},
        }

        for category in sorted(financial_data.keys(), key=lambda x: category_order.get(x, 99)):
            for tag in financial_data[category]:
                concept_name = tag.split(':')[-1]
                info = classifications.get(concept_name, {})
                display_name = info.get('display_name', self._format_concept_name(concept_name))
                order = info.get('order', 50)
                unit = concept_units.get(concept_name, 'USD')
                metric_key = f"{category}_{concept_name}"

                values = {}
                for period in limited_periods:
                    value = None
                    for fact in financial_data[category][tag]:
                        if fact['end'] == period:
                            value = fact['val']
                            break
                    values[period] = value

                # Skip metrics where ALL periods are None
                if all(v is None for v in values.values()):
                    continue

                # Skip metrics with data in less than half the periods (sparse/discontinued)
                non_null = sum(1 for v in values.values() if v is not None)
                if non_null < len(limited_periods) / 2:
                    continue

                source = info.get('source', 'sec')

                normalized_data['metrics'][metric_key] = {
                    'values': values,
                    'category': category,
                    'tag': tag,
                    'display_name': display_name,
                    'order': order,
                    'unit': unit,
                    'source': source,
                    'indent': info.get('indent', 0),
                    'is_subtotal': info.get('is_subtotal', False),
                    'section': info.get('section', ''),
                }

        normalized_data['metadata'] = {
            'fiscal_month': fiscal_month,
            'period_type': period_type,
        }

        return normalized_data

    def _format_concept_name(self, concept_name):
        """Fallback: convert CamelCase to human-readable label."""
        formatted = re.sub(r'([a-z])([A-Z])', r'\1 \2', concept_name)
        formatted = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', formatted)
        return formatted

    def _detect_fiscal_year_end(self, all_periods):
        """Detect fiscal year end month from period end dates."""
        months = []
        for period in all_periods:
            try:
                month = period.split('-')[1]
                if month.isdigit() and 1 <= int(month) <= 12:
                    months.append(month)
            except (IndexError, ValueError):
                continue

        month_counter = Counter(months)
        most_common = month_counter.most_common(1)
        return most_common[0][0] if most_common else '12'

    def normalize_financial_data(self, financial_data, period_type='annual', num_periods=1):
        """Normalize financial data (compatibility method)."""
        all_periods = []
        found_concepts = set()

        for category in financial_data:
            for tag in financial_data[category]:
                concept_name = tag.split(':')[-1]
                found_concepts.add(concept_name)
                for fact in financial_data[category][tag]:
                    if 'end' in fact:
                        all_periods.append(fact['end'])

        classifications = self.classifier.classify_tags(list(found_concepts))
        return self._normalize_api_data(financial_data, period_type, all_periods, num_periods, classifications)
