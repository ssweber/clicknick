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

    def __init__(self):
        self.contains_filter = ContainsFilter()
        self._time_patterns = [
            (re.compile(r"([a-zA-Z])\1{3}([a-zA-Z])\2{1}([a-zA-Z])\3{1}"), r"\1\1\1\1 \2\2 \3\3"),
            (re.compile(r"([a-zA-Z])\1{3}([a-zA-Z])\2{1}"), r"\1\1\1\1 \2\2"),
            (re.compile(r"([a-zA-Z])\1{1}([a-zA-Z])\2{1}([a-zA-Z])\3{1}"), r"\1\1 \2\2 \3\3"),
            (re.compile(r"([a-zA-Z])\1{1}([a-zA-Z])\2{1}"), r"\1\1 \2\2"),
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
        """Split text into words on underscore, spaces, and camelCase boundaries"""
        processed_text = text
        
        # split YYYYMMDD, YYMMDD, hhmmss
        for pattern, replacement in self._time_patterns:
            processed_text = pattern.sub(replacement, processed_text)

        # split on underscore and spaces
        parts = re.split(r"[_\s]+", processed_text)

        # split each part on camelCase boundaries
        words = []
        for part in parts:
            if not part:
                continue
            # split on camelCase: insert space before uppercase letters that follow lowercase
            camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
            words.extend(camel_split.split())

        # don't return single-characters
        return [word for word in words if len(word) > 1]

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
                reduce_post_vowel_clusters # optional
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
        variants = {
            "original": needle_lower,
            "abbreviated": self.abbreviate_word(needle_lower),
            "abbreviated_alt": self.abbreviate_word(needle_lower, False),
            "mapped_shorthand": [],
        }

        # Check if needle matches any abbreviation mappings
        for full_word, abbrevs in self.mapped_shorthand.items():
            if needle_lower == full_word:
                variants["mapped_shorthand"].extend(abbrevs)

        return variants

    def matches_abbreviation_tags(self, item, needle_variants):
        """Check if item matches based on its abbreviation tags"""
        abbr_tags = getattr(item, "abbr_tags", "")
        if not abbr_tags:
            return False

        # Check against needle variants
        for abbr in abbr_tags:
            if (
                abbr.startswith(needle_variants["original"])
                or abbr.startswith(needle_variants["abbreviated"])
                or abbr.startswith(needle_variants["abbreviated_alt"])
            ):
                return True

        return False

    def matches_shorthand_in_item(self, item, needle_variants):
        """Check if any needle shorthand appears in the item text"""
        if not needle_variants["mapped_shorthand"]:
            return False

        abbr_tags = getattr(item, "abbr_tags", "")
        if not abbr_tags:
            return False

        for abbr in abbr_tags:
            for shorthand in needle_variants["mapped_shorthand"]:
                if abbr.startswith(shorthand):
                    return True

        return False

    def get_abbreviation_matches(self, items, needle_variants):
        """Get items that match via abbreviation logic"""
        matches = []

        for item in items:
            if self.matches_abbreviation_tags(
                item, needle_variants
            ) or self.matches_shorthand_in_item(item, needle_variants):
                matches.append(item)

        return matches

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
        """Cascade: first ContainsFilter, then abbreviation matching on remainder"""
        if not current_text:
            return completion_list

        # First pass: Use contains filter
        contains_matches = self.contains_filter.filter_matches(completion_list, current_text)

        # Get items that didn't match the contains filter
        contains_matched_ids = {id(item) for item in contains_matches}
        remaining_items = [item for item in completion_list if id(item) not in contains_matched_ids]

        # Second pass: Apply abbreviation matching to remaining items
        abbreviation_matches = []
        if remaining_items:
            needle_variants = self.get_needle_variants(current_text)
            abbreviation_matches = self.get_abbreviation_matches(remaining_items, needle_variants)

        # Combine results: contains matches first, then abbreviation matches
        return contains_matches + abbreviation_matches
