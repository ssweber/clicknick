import re
from functools import lru_cache


class FilterBase:
    """Base class for autocomplete strategies"""

    def filter_matches(self, completion_list, current_text):
        """Filter completion list based on current text"""
        raise NotImplementedError()


class NoneFilter(FilterBase):
    """No filtering strategy"""

    def filter_matches(self, completion_list, current_text):
        return completion_list


class PrefixFilter(FilterBase):
    """Simple prefix matching strategy"""

    def filter_matches(self, completion_list, current_text):
        if not current_text:
            return completion_list

        current_text = current_text.lower()
        return [item for item in completion_list if str(item).lower().startswith(current_text)]


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
            item_str = str(item).lower()
            if current_lower not in item_str:
                continue

            # Check if match occurs after common word delimiters or before uppercase
            match_pos = item_str.find(current_lower)
            original_item_str = str(item)
            if (
                match_pos == 0
                or original_item_str[match_pos - 1] in "_- "
                or original_item_str[match_pos].isupper()
            ):
                word_start_matches.append(item)
            else:
                other_matches.append(item)

        return word_start_matches + other_matches


class ContainsPlusFilter(FilterBase):
    """Enhanced contains matching with abbreviation support - with caching"""

    # Class-level regex constants
    DT_PATTERN_1 = re.compile(r"([a-zA-Z])\1{3}([a-zA-Z])\2{1}([a-zA-Z])\3{1}")
    DT_PATTERN_2 = re.compile(r"([a-zA-Z])\1{3}([a-zA-Z])\2{1}")
    DT_PATTERN_3 = re.compile(r"([a-zA-Z])\1{1}([a-zA-Z])\2{1}([a-zA-Z])\3{1}")
    DT_PATTERN_4 = re.compile(r"([a-zA-Z])\1{1}([a-zA-Z])\2{1}")

    # underscores, spaces, and CamelCase
    WORD_BOUNDARY_PATTERN = re.compile(r"[_\s]+|(?<=[a-z])(?=[A-Z])")

    def __init__(self):
        self.contains_filter = ContainsFilter()
        self._DT_PATTERNs = [
            (self.DT_PATTERN_1, r"\1\1\1\1 \2\2 \3\3"),
            (self.DT_PATTERN_2, r"\1\1\1\1 \2\2"),
            (self.DT_PATTERN_3, r"\1\1 \2\2 \3\3"),
            (self.DT_PATTERN_4, r"\1\1 \2\2"),
        ]
        self.vowels = frozenset("aeiou")
        self.mapped_shorthand = {
            # Ordinals
            "first": ["1st"],
            "second": ["2nd", "ss"],
            "third": ["3rd"],
            "fourth": ["4th"],
            "fifth": ["5th"],
            "sixth": ["6th"],
            "seventh": ["7th"],
            "eighth": ["8th"],
            "ninth": ["9th"],
            "tenth": ["10th"],
            # Time formats (lowercase)
            "hour": ["hh"],
            "minute": ["mm"],
            "millisecond": ["ms"],
            # Date formats (always uppercase regardless of input case)
            "year": ["YY", "YYYY"],
            "month": ["MM"],
            "day": ["DD"],
        }

    def split_into_words(self, text):
        # Single regex operation instead of multiple substitutions
        for pattern, replacement in self._DT_PATTERNs:
            text = pattern.sub(replacement, text)

        # Single split operation
        words = [word for word in self.WORD_BOUNDARY_PATTERN.split(text) if len(word) > 1]
        return words

    def _abbrword_special_case(self, word):
        """Special Abbreviation Cases"""
        # return all same letter (like YYYY) unmodified case
        if len(set(word)) <= 1:
            return word

        # short words
        word_lower = word.lower()
        if len(word_lower) <= 3:
            return word_lower

        # all consonants (excluding first - possibly already abbreviated)
        vowels = self.vowels
        if not vowels & set(word_lower[1:]):
            return word_lower

    def _abbrword_consonants(self, word):
        """Keep first letter. Keep all consonants. Delete doubles."""

        vowels = self.vowels
        word_lower = word.lower()
        result = [word_lower[0]]  # Always keep first letter

        # Keep all consonants (skip vowels after first letter)
        for i in range(1, len(word_lower)):
            char = word_lower[i]
            if char not in vowels:
                result.append(char)

        # Remove consecutive duplicates
        final = [result[0]]
        for char in result[1:]:
            if char != final[-1]:
                final.append(char)

        return "".join(final)

    def _abbrword_reduced_consonants(self, word):
        """Keep first letter. Drop all vowels. Drop first consonant after vowel if next is consonant. Delete doubles."""

        vowels = self.vowels
        word_lower = word.lower()
        result = [word_lower[0]]  # Always keep first letter

        # Process characters starting from index 1 (skip first letter from rule)
        for i in range(1, len(word_lower)):
            char = word_lower[i]

            if char in vowels:
                # Skip all vowels
                continue

            # It's a consonant - check if we should drop it
            if (
                i > 1  # Don't apply rule to second character (index 1)
                and word_lower[i - 1] in vowels  # Previous was vowel
                and i + 1 < len(word_lower)  # There is a next character
                and word_lower[i + 1] not in vowels
            ):  # Next is consonant
                # Skip this consonant (first consonant after vowel when next is consonant)
                continue

            result.append(char)

        # Remove consecutive duplicates
        final = [result[0]]
        for char in result[1:]:
            if char != final[-1]:
                final.append(char)

        return "".join(final)

    def get_needle_variants(self, needle):
        """Get all variants of the search needle for matching"""
        needle_lower = needle.lower()
        variants = [needle_lower]

        # Add abbreviation variants
        variants.extend(self.get_abbreviated_word_list(needle_lower))

        # Add mapped shorthand
        for full_word, abbrevs in self.mapped_shorthand.items():
            if needle_lower == full_word:
                variants.extend(abbrevs)

        return variants

    def get_abbreviated_word_list(self, word):
        """Generate a list of abbreviated variants for a given word.

        Returns special case abbreviation if available, otherwise generates
        consonant-based abbreviations of varying lengths.
        """
        variants = []
        abbr = self._abbrword_special_case(word)

        if abbr:
            return [abbr]

        abbr2 = self._abbrword_consonants(word)
        if len(abbr2) >= 2:
            variants.append(abbr2)
            abbr3 = self._abbrword_reduced_consonants(word)
            if len(abbr3) >= 2:
                variants.append(abbr3)
        return variants

    def matches_abbreviation(self, item, needle_variants):
        """Check if item matches any needle variant"""
        abbr_tags = getattr(item, "abbr_tags", [])
        if not abbr_tags:
            return False

        for tag in abbr_tags:
            for variant in needle_variants:
                if tag.startswith(variant):
                    return True
        return False

    @lru_cache(maxsize=12000)  # noqa: B019
    def _generate_tags_cached(self, text):
        """Internal cached method that returns a tuple"""
        words = self.split_into_words(text)
        tags = []

        # Add original words (4+ chars)
        for word in words:
            if len(word) >= 4:
                tags.append(word.lower())

        # Add predefined abbreviations
        for word in words:
            word_lower = word.lower()
            if word_lower in self.mapped_shorthand:
                tags.extend(self.mapped_shorthand[word_lower])

        # Add computed abbreviations
        for word in words:
            tags.extend(self.get_abbreviated_word_list(word))

        return tuple(sorted(set(tags)))  # Return tuple for hashability

    def generate_tags(self, text):
        """Generate searchable tags for a nickname - returns list for compatibility"""
        return list(self._generate_tags_cached(text))

    def _filter_single_word(self, completion_list, word):
        """Filter using cascading approach for single word searches"""
        contains_matches = self.contains_filter.filter_matches(completion_list, word)
        contains_matched_ids = {id(item) for item in contains_matches}
        remaining_items = [item for item in completion_list if id(item) not in contains_matched_ids]

        needle_variants = self.get_needle_variants(word)
        abbreviation_matches = [
            item for item in remaining_items if self.matches_abbreviation(item, needle_variants)
        ]
        return contains_matches + abbreviation_matches

    def _filter_multiple_words(self, completion_list, search_words):
        """Filter using intersection approach for multiple word searches"""
        # Sort words by length (longer/more specific words first for faster elimination)
        search_words.sort(key=len, reverse=True)

        matching_items = set(completion_list)

        for word in search_words:
            # Early exit if no items match all previous words
            if not matching_items:
                break

            # Only search within current candidates (progressively smaller set)
            current_candidates = list(matching_items)

            # Get contains matches for this word
            contains_matches = set(self.contains_filter.filter_matches(current_candidates, word))

            # Get abbreviation matches for this word
            needle_variants = self.get_needle_variants(word)
            abbreviation_matches = {
                item
                for item in current_candidates
                if self.matches_abbreviation(item, needle_variants)
            }

            # Combine both types of matches for this word
            word_matches = contains_matches | abbreviation_matches

            # Keep only items that match this word too (intersection)
            matching_items &= word_matches

        return list(matching_items)

    def filter_matches(self, completion_list, current_text):
        """Find items that match ALL search words (intersection) with early termination optimization"""
        if not current_text:
            return completion_list

        # Split input into words for multi-word search
        search_words = self.split_into_words(current_text)
        if not search_words:
            # If no valid words extracted (e.g., whitespace only), return full list
            return completion_list

        # Route to appropriate filtering method
        if len(search_words) == 1:
            return self._filter_single_word(completion_list, search_words[0])
        else:
            return self._filter_multiple_words(completion_list, search_words)
