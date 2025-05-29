import difflib

from rapidfuzz import fuzz


class FilterBase:
    """Base class for autocomplete strategies"""

    def filter_matches(self, completion_list, current_text):
        """Filter completion list based on current text"""
        raise NotImplementedError()


class NoneFilter(FilterBase):
    """Simple prefix matching strategy"""

    def filter_matches(self, completion_list, current_text):
        return completion_list


class PrefixFilter(FilterBase):
    """Simple prefix matching strategy"""

    def filter_matches(self, completion_list, current_text):
        if not current_text:
            return completion_list

        current_text = current_text.lower()
        return [item for item in completion_list if item.lower().startswith(current_text)]


class ContainsFilter(FilterBase):
    """Contains matching strategy with word boundary prioritization"""

    def filter_matches(self, completion_list, current_text):
        if not current_text:
            return completion_list

        current_lower = current_text.lower()

        # Split into two groups: matches at word boundaries vs matches anywhere
        word_start_matches = []
        other_matches = []

        for item in completion_list:
            if current_lower not in item.lower():
                continue

            # Check if match occurs after common word delimiters or before uppercase
            match_pos = item.lower().find(current_lower)
            if match_pos == 0 or item[match_pos - 1] in "_- " or item[match_pos].isupper():
                word_start_matches.append(item)
            else:
                other_matches.append(item)

        return word_start_matches + other_matches


class FuzzyFilter(FilterBase):
    """Fuzzy matching strategy using rapidfuzz with fallback"""

    def __init__(self, threshold=60):
        self.threshold = threshold

    def filter_matches(self, completion_list, current_text):
        if not current_text:
            return completion_list

        try:
            # Try using rapidfuzz with partial_ratio for better substring matching
            matches = []
            for item in completion_list:
                # Calculate partial similarity ratio
                ratio = fuzz.partial_ratio(current_text.lower(), item.lower())
                if ratio > self.threshold:  # Use configurable threshold
                    matches.append((item, ratio))

            # Sort by similarity ratio (highest first)
            matches.sort(key=lambda x: x[1], reverse=True)
            return [item for item, _ in matches]

        except ImportError:
            # Prefilter: must contain at least first 3 chars (or all if less than 3)
            min_chars = min(2, len(current_text))
            prefilter_text = current_text[:min_chars].lower()

            # Prefilter candidates for difflib fallback
            candidates = [item for item in completion_list if prefilter_text in item.lower()]

            if not candidates:
                # Fall back to contains matching if no matches
                return [item for item in completion_list if current_text.lower() in item.lower()]

            # Fall back to difflib if rapidfuzz not available
            # Adjust cutoff based on threshold (convert from 0-100 to 0-1 scale)
            cutoff = max(0.3, self.threshold / 100.0 - 0.1)  # Ensure minimum cutoff of 0.3
            matches = difflib.get_close_matches(current_text, candidates, n=10, cutoff=cutoff)

            # Add any remaining candidates that contain the search text
            remaining = [
                item
                for item in candidates
                if item not in matches and current_text.lower() in item.lower()
            ]

            return matches + remaining
