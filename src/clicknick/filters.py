import re


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
    """Enhanced contains matching with abbreviation support"""

    # Class-level regex constants
    TIME_PATTERN_1 = re.compile(r"([a-zA-Z])\1{3}([a-zA-Z])\2{1}([a-zA-Z])\3{1}")
    TIME_PATTERN_2 = re.compile(r"([a-zA-Z])\1{3}([a-zA-Z])\2{1}")
    TIME_PATTERN_3 = re.compile(r"([a-zA-Z])\1{1}([a-zA-Z])\2{1}([a-zA-Z])\3{1}")
    TIME_PATTERN_4 = re.compile(r"([a-zA-Z])\1{1}([a-zA-Z])\2{1}")

    # underscores, spaces, and CamelCase
    WORD_BOUNDARY_PATTERN = re.compile(r"[_\s]+|(?<=[a-z])(?=[A-Z])")

    def __init__(self):
        self.contains_filter = ContainsFilter()
        self._time_patterns = [
            (self.TIME_PATTERN_1, r"\1\1\1\1 \2\2 \3\3"),
            (self.TIME_PATTERN_2, r"\1\1\1\1 \2\2"),
            (self.TIME_PATTERN_3, r"\1\1 \2\2 \3\3"),
            (self.TIME_PATTERN_4, r"\1\1 \2\2"),
        ]
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
        for pattern, replacement in self._time_patterns:
            text = pattern.sub(replacement, text)

        # Single split operation
        words = [word for word in self.WORD_BOUNDARY_PATTERN.split(text) if len(word) > 1]
        return words

    def abbreviate_word(self, word, reduce_post_vowel_clusters=True):
        """Apply abbreviation rules to a word"""

        # return all same letter (like YYYY) unmodified case
        if len(set(word)) <= 1:
            return word

        # short words
        word = word.lower()
        if len(word) <= 3:
            return word

        # all consonants
        vowels = "aeiou"
        if not any(vowel in word for vowel in vowels):
            return word

        # Abbreviation logic:

        result = [word[0]]  # Rule 1: Keep first letter
        second_consonant_kept = False

        for i in range(1, len(word)):
            char = word[i]

            # Rule 2: Discard vowels
            if char in vowels:
                continue

            # Rule 3: Always keep the second consonant
            if not second_consonant_kept:
                result.append(char)
                second_consonant_kept = True
                continue

            # Rule 4: If rule 3 used, discard first of two consonants after vowel
            if (
                reduce_post_vowel_clusters  # optional
                and i > 1
                and word[i - 1] in vowels
                and i < len(word) - 1
                and word[i + 1] not in vowels
            ):
                continue

            result.append(char)

        # Rule 5: Reduce double consonants to one
        final_result = []
        for i, char in enumerate(result):
            if i == 0 or char != result[i - 1]:
                final_result.append(char)

        return "".join(final_result)

    def get_needle_variants(self, needle):
        """Get all variants of the search needle for matching"""
        needle_lower = needle.lower()
        variants = [needle_lower]

        # Add abbreviation variants
        variants.append(self.abbreviate_word(needle_lower))
        variants.append(self.abbreviate_word(needle_lower, False))

        # Add mapped shorthand
        for full_word, abbrevs in self.mapped_shorthand.items():
            if needle_lower == full_word:
                variants.extend(abbrevs)

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

    def generate_tags(self, text):
        """Generate searchable tags for a nickname"""
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
            tags.append(self.abbreviate_word(word))
            tags.append(self.abbreviate_word(word, reduce_post_vowel_clusters=False))

        return sorted(set(tags))

    def filter_matches(self, completion_list, current_text):
        """Find items that match ALL search words (intersection) with early termination optimization"""
        if not current_text:
            return completion_list

        # Split input into words for multi-word search
        search_words = self.split_into_words(current_text)
        if not search_words:
            # Fallback to original text if no words extracted
            search_words = [current_text]

        # If only one word, use the original cascading approach
        if len(search_words) == 1:
            word = search_words[0]
            contains_matches = self.contains_filter.filter_matches(completion_list, word)
            contains_matched_ids = {id(item) for item in contains_matches}
            remaining_items = [
                item for item in completion_list if id(item) not in contains_matched_ids
            ]

            needle_variants = self.get_needle_variants(word)
            abbreviation_matches = [
                item for item in remaining_items if self.matches_abbreviation(item, needle_variants)
            ]
            return contains_matches + abbreviation_matches

        # For multiple words, find intersection with early termination
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
