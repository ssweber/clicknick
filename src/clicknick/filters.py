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
        self.abbrev_mappings = {
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

        # Special handling for time patterns like hhmmss, yyyymmdd, etc.
        time_patterns = [
            (r"(\d{4})(\d{2})(\d{2})", r"\1 \2 \3"),  # yyyymmdd -> yyyy mm dd
            (r"([a-z]{2})([a-z]{2})([a-z]{2})", r"\1 \2 \3"),  # hhmmss -> hh mm ss
        ]

        processed_text = text
        for pattern, replacement in time_patterns:
            processed_text = re.sub(pattern, replacement, processed_text)

        # First split on underscore and spaces
        parts = re.split(r"[_\s]+", processed_text)

        # Then split each part on camelCase boundaries
        words = []
        for part in parts:
            if not part:
                continue
            # Split on camelCase: insert space before uppercase letters that follow lowercase
            camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
            words.extend(camel_split.split())

        return [word for word in words if word]

    def abbreviate_word(self, word, reduce_post_vowel_clusters=True):
        """Apply abbreviation rules to a word"""
        word = word.lower()
        if len(word) <= 1:
            return word

        result = [word[0]]  # Rule 1: Keep first letter
        vowels = "aeiou"
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
                reduce_post_vowel_clusters
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

    def generate_tags(self, text):
        """Generate searchable tags for a nickname"""
        words = self.split_into_words(text)
        abbr_set = set()

        # Add original words (4+ chars)
        for word in words:
            if len(word) >= 4:
                abbr_set.add(word.lower())

        # Add full text without underscores
        abbr_set.add(text.lower().replace("_", ""))

        # Add predefined abbreviations
        for word in words:
            word_lower = word.lower()
            if word_lower in self.abbrev_mappings:
                abbr_set.update(self.abbrev_mappings[word_lower])

        # Add computed abbreviations
        for word in words:
            abbr_set.add(self.abbreviate_word(word).lower())
            abbr_set.add(self.abbreviate_word(word, reduce_post_vowel_clusters=False).lower())

        return ",".join(sorted(abbr_set))

    def filter_matches(self, completion_list, current_text):
        """Cascade: first ContainsFilter, then abbreviation matching on remainder"""
        if not current_text:
            return completion_list

        # First pass: Use contains filter
        contains_matches = self.contains_filter.filter_matches(completion_list, current_text)

        # Create a set of items that were matched by contains filter for quick lookup
        contains_matched_items = {str(item) for item in contains_matches}

        # Get the items that DIDN'T match the contains filter
        remaining_items = [
            item for item in completion_list if str(item) not in contains_matched_items
        ]

        # Second pass: Apply abbreviation matching to remaining items only
        abbreviation_matches = []
        if remaining_items:
            needle = current_text.lower()
            needle_abbr = self.abbreviate_word(needle).lower()
            needle_abbr2 = self.abbreviate_word(needle, False).lower()

            # Check if needle matches any abbreviation mappings
            needle_expansions = []
            for full_word, abbrevs in self.abbrev_mappings.items():
                if needle.startswith(full_word):
                    needle_expansions.extend(abbrevs)

            for item in remaining_items:
                # Check abbreviation tags
                abbr_tags = getattr(item, "abbr_tags", "")
                if abbr_tags:
                    abbr_tags_list = abbr_tags.split(",")

                    for abbr in abbr_tags_list:
                        if (
                            abbr.startswith(needle)
                            or abbr.startswith(needle_abbr)
                            or abbr.startswith(needle_abbr2)
                        ):
                            abbreviation_matches.append(item)
                            break

                # Check if item contains any of the needle's mapped abbreviations
                if not any(item == match for match in abbreviation_matches):  # Avoid duplicates
                    for expansion in needle_expansions:
                        if expansion in str(item):  # This will match the actual case in the tag
                            abbreviation_matches.append(item)
                            break

        # Combine results: contains matches first, then abbreviation matches
        return contains_matches + abbreviation_matches
