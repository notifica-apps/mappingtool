"""
Self-Learning Module for Mapping Tool

This module implements a feedback loop that:
1. Logs predictions made by the mapping engine
2. Tracks corrections made by users
3. Uses corrections to improve future predictions
4. Provides analytics on prediction accuracy over time
"""
import json
import os
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
import pandas as pd
import pytz


class LearningStore:
    """
    Persistent storage for learning data.
    Stores predictions, corrections, and learned mappings.
    """

    def __init__(self, store_dir: str):
        """
        Initialize the learning store.

        Args:
            store_dir: Directory to store learning data files
        """
        self.store_dir = store_dir
        os.makedirs(store_dir, exist_ok=True)

        # File paths
        self.predictions_file = os.path.join(store_dir, 'predictions.jsonl')
        self.corrections_file = os.path.join(store_dir, 'corrections.jsonl')
        self.learned_mappings_file = os.path.join(store_dir, 'learned_mappings.json')
        self.stats_file = os.path.join(store_dir, 'stats.json')

        # In-memory caches
        self._learned_mappings: Dict[str, Dict[str, Any]] = {}
        self._load_learned_mappings()

    def _get_key(self, mapping_type: str, normalized_input: str, extra_context: str = "") -> str:
        """Generate a unique key for a mapping entry."""
        combined = f"{mapping_type}:{normalized_input}:{extra_context}"
        return hashlib.md5(combined.encode()).hexdigest()[:16]

    def _get_timestamp(self) -> str:
        """Get current timestamp in Amsterdam timezone."""
        tz = pytz.timezone('Europe/Amsterdam')
        return datetime.now(tz).isoformat()

    def _load_learned_mappings(self):
        """Load learned mappings from disk."""
        if os.path.exists(self.learned_mappings_file):
            try:
                with open(self.learned_mappings_file, 'r', encoding='utf-8') as f:
                    self._learned_mappings = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._learned_mappings = {}

    def _save_learned_mappings(self):
        """Save learned mappings to disk."""
        with open(self.learned_mappings_file, 'w', encoding='utf-8') as f:
            json.dump(self._learned_mappings, f, indent=2, ensure_ascii=False)

    def log_prediction(
        self,
        mapping_type: str,
        original_input: str,
        normalized_input: str,
        predicted_output: Optional[Tuple],
        match_method: str,
        confidence: float = 1.0,
        extra_context: Dict = None
    ) -> str:
        """
        Log a prediction made by the mapping engine.

        Args:
            mapping_type: Type of mapping (Taken, WV, Balans)
            original_input: Original input string (Taak or Rubriek)
            normalized_input: Normalized input key
            predicted_output: Predicted mapping tuple or None
            match_method: Method used to make the prediction
            confidence: Confidence score (0-1)
            extra_context: Additional context (e.g., Type for Taken)

        Returns:
            Prediction ID for reference
        """
        prediction_id = self._get_key(mapping_type, normalized_input, str(extra_context))

        entry = {
            'id': prediction_id,
            'timestamp': self._get_timestamp(),
            'mapping_type': mapping_type,
            'original_input': original_input,
            'normalized_input': normalized_input,
            'predicted_output': list(predicted_output) if predicted_output else None,
            'match_method': match_method,
            'confidence': confidence,
            'extra_context': extra_context or {},
            'corrected': False,
        }

        # Append to predictions log
        with open(self.predictions_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        return prediction_id

    def log_correction(
        self,
        mapping_type: str,
        original_input: str,
        normalized_input: str,
        original_prediction: Optional[Tuple],
        corrected_output: Tuple,
        extra_context: Dict = None
    ):
        """
        Log a correction made by a user.

        Args:
            mapping_type: Type of mapping
            original_input: Original input string
            normalized_input: Normalized input key
            original_prediction: What was originally predicted (can be None)
            corrected_output: The correct mapping as provided by user
            extra_context: Additional context
        """
        correction_id = self._get_key(mapping_type, normalized_input, str(extra_context))

        entry = {
            'id': correction_id,
            'timestamp': self._get_timestamp(),
            'mapping_type': mapping_type,
            'original_input': original_input,
            'normalized_input': normalized_input,
            'original_prediction': list(original_prediction) if original_prediction else None,
            'corrected_output': list(corrected_output),
            'extra_context': extra_context or {},
            'prediction_was_wrong': original_prediction != corrected_output,
        }

        # Append to corrections log
        with open(self.corrections_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        # Update learned mappings
        self._update_learned_mapping(
            mapping_type,
            normalized_input,
            corrected_output,
            extra_context
        )

    def _update_learned_mapping(
        self,
        mapping_type: str,
        normalized_input: str,
        correct_output: Tuple,
        extra_context: Dict = None
    ):
        """Update the learned mappings with a correction."""
        key = self._get_key(mapping_type, normalized_input, str(extra_context))

        if key not in self._learned_mappings:
            self._learned_mappings[key] = {
                'mapping_type': mapping_type,
                'normalized_input': normalized_input,
                'extra_context': extra_context or {},
                'outputs': {},
                'total_corrections': 0,
            }

        entry = self._learned_mappings[key]
        output_key = str(correct_output)

        if output_key not in entry['outputs']:
            entry['outputs'][output_key] = {
                'output': list(correct_output),
                'count': 0,
                'last_used': None,
            }

        entry['outputs'][output_key]['count'] += 1
        entry['outputs'][output_key]['last_used'] = self._get_timestamp()
        entry['total_corrections'] += 1

        self._save_learned_mappings()

    def get_learned_mapping(
        self,
        mapping_type: str,
        normalized_input: str,
        extra_context: Dict = None
    ) -> Optional[Tuple]:
        """
        Get a learned mapping if one exists.

        Returns the most frequently corrected output for this input.

        Args:
            mapping_type: Type of mapping
            normalized_input: Normalized input key
            extra_context: Additional context

        Returns:
            The learned mapping tuple or None
        """
        key = self._get_key(mapping_type, normalized_input, str(extra_context))

        if key not in self._learned_mappings:
            return None

        entry = self._learned_mappings[key]
        outputs = entry.get('outputs', {})

        if not outputs:
            return None

        # Return the output with the highest count
        best_output = max(outputs.values(), key=lambda x: x['count'])
        return tuple(best_output['output'])

    def get_all_learned_mappings(self, mapping_type: str = None) -> List[Dict]:
        """Get all learned mappings, optionally filtered by type."""
        result = []

        for key, entry in self._learned_mappings.items():
            if mapping_type and entry['mapping_type'] != mapping_type:
                continue

            # Get the best output
            outputs = entry.get('outputs', {})
            if outputs:
                best_output = max(outputs.values(), key=lambda x: x['count'])
                result.append({
                    'normalized_input': entry['normalized_input'],
                    'mapping_type': entry['mapping_type'],
                    'extra_context': entry.get('extra_context', {}),
                    'best_output': best_output['output'],
                    'count': best_output['count'],
                    'total_corrections': entry['total_corrections'],
                })

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """Calculate and return learning statistics."""
        stats = {
            'total_predictions': 0,
            'total_corrections': 0,
            'accuracy_by_type': {},
            'corrections_over_time': [],
            'top_corrected_inputs': [],
        }

        # Count predictions
        if os.path.exists(self.predictions_file):
            with open(self.predictions_file, 'r', encoding='utf-8') as f:
                predictions = [json.loads(line) for line in f if line.strip()]
                stats['total_predictions'] = len(predictions)

                # Group by type
                by_type = defaultdict(list)
                for p in predictions:
                    by_type[p['mapping_type']].append(p)

                for mapping_type, preds in by_type.items():
                    stats['accuracy_by_type'][mapping_type] = {
                        'total': len(preds),
                        'methods': defaultdict(int),
                    }
                    for p in preds:
                        stats['accuracy_by_type'][mapping_type]['methods'][p['match_method']] += 1

        # Count corrections
        if os.path.exists(self.corrections_file):
            with open(self.corrections_file, 'r', encoding='utf-8') as f:
                corrections = [json.loads(line) for line in f if line.strip()]
                stats['total_corrections'] = len(corrections)

                # Calculate accuracy (predictions that didn't need correction)
                wrong_predictions = sum(1 for c in corrections if c.get('prediction_was_wrong', True))

                if stats['total_predictions'] > 0:
                    stats['overall_accuracy'] = 1 - (wrong_predictions / stats['total_predictions'])
                else:
                    stats['overall_accuracy'] = None

                # Group by date
                by_date = defaultdict(int)
                for c in corrections:
                    date = c['timestamp'][:10]  # YYYY-MM-DD
                    by_date[date] += 1

                stats['corrections_over_time'] = [
                    {'date': d, 'count': c}
                    for d, c in sorted(by_date.items())
                ]

        # Top corrected inputs
        input_corrections = defaultdict(int)
        for entry in self._learned_mappings.values():
            input_corrections[entry['normalized_input']] = entry['total_corrections']

        stats['top_corrected_inputs'] = sorted(
            [{'input': k, 'corrections': v} for k, v in input_corrections.items()],
            key=lambda x: -x['corrections']
        )[:20]

        stats['total_learned_mappings'] = len(self._learned_mappings)

        return stats


class LearningEnhancedMatcher:
    """
    A wrapper that enhances any matcher with learning capabilities.
    It checks learned mappings first, then falls back to the original matcher.
    """

    def __init__(self, base_matcher, learning_store: LearningStore, mapping_type: str):
        """
        Initialize the learning-enhanced matcher.

        Args:
            base_matcher: The original matcher (TakenMatcher or WVBalansMatcher)
            learning_store: The learning store instance
            mapping_type: Type of mapping (Taken, WV, Balans)
        """
        self.base_matcher = base_matcher
        self.learning_store = learning_store
        self.mapping_type = mapping_type
        self.learning_matches = 0
        self.base_matches = 0

    def match(self, normalized_key: str, **kwargs) -> Tuple[Optional[Tuple], str, float]:
        """
        Match with learning enhancement.

        Returns:
            Tuple of (result, method, confidence)
        """
        # Build extra context from kwargs
        extra_context = {}
        if 'taak_type' in kwargs:
            extra_context['type'] = kwargs['taak_type']

        # First check learned mappings
        learned = self.learning_store.get_learned_mapping(
            self.mapping_type,
            normalized_key,
            extra_context
        )

        if learned:
            self.learning_matches += 1
            return learned, 'learned', 1.0

        # Fall back to base matcher
        if hasattr(self.base_matcher, 'match'):
            result, method = self.base_matcher.match(normalized_key, **kwargs)
        else:
            result, method = None, 'unmatched'

        # Calculate confidence based on method
        confidence_map = {
            'A_exact': 1.0,
            'exact': 1.0,
            'B_anchor': 0.95,
            'anchor_fixed': 0.95,
            'anchor_niveau': 0.90,
            'C_prefix': 0.85,
            'prefix': 0.85,
            'D_token_set': 0.80,
            'fuzzy': 0.80,
            'E_token_sort': 0.75,
            'G_majority': 0.70,
            'H_client_top': 0.60,
            'H_type_top': 0.50,
            'unmatched': 0.0,
        }
        confidence = confidence_map.get(method, 0.5)

        self.base_matches += 1

        return result, method, confidence

    def log_prediction(self, original_input: str, normalized_input: str,
                       result: Optional[Tuple], method: str, confidence: float,
                       extra_context: Dict = None):
        """Log a prediction for learning."""
        self.learning_store.log_prediction(
            self.mapping_type,
            original_input,
            normalized_input,
            result,
            method,
            confidence,
            extra_context
        )

    def log_correction(self, original_input: str, normalized_input: str,
                       original_prediction: Optional[Tuple], correct_output: Tuple,
                       extra_context: Dict = None):
        """Log a correction for learning."""
        self.learning_store.log_correction(
            self.mapping_type,
            original_input,
            normalized_input,
            original_prediction,
            correct_output,
            extra_context
        )


def export_learned_mappings_to_csv(learning_store: LearningStore, output_path: str):
    """
    Export learned mappings to a CSV file that can be reviewed or imported.
    """
    mappings = learning_store.get_all_learned_mappings()

    if not mappings:
        return

    # Flatten for CSV
    rows = []
    for m in mappings:
        row = {
            'mapping_type': m['mapping_type'],
            'normalized_input': m['normalized_input'],
            'correction_count': m['count'],
            'total_corrections': m['total_corrections'],
        }

        # Add output fields based on type
        output = m['best_output']
        if m['mapping_type'] == 'Taken':
            row['Taakgroepcode'] = output[0] if len(output) > 0 else ''
            row['Taakgroep'] = output[1] if len(output) > 1 else ''
        else:
            row['CoA_code'] = output[0] if len(output) > 0 else ''
            row['Niveau1'] = output[1] if len(output) > 1 else ''
            row['Niveau2'] = output[2] if len(output) > 2 else ''

        # Add extra context
        extra = m.get('extra_context', {})
        if 'type' in extra:
            row['Type'] = extra['type']

        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(output_path, sep=';', index=False, encoding='utf-8-sig')
