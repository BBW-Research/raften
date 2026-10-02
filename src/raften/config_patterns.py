"""Bounded ambiguity checks with one declaration-order witness per selector."""

from raften.config_validation import Validator
from raften.diagnostics import CFG_AMBIGUOUS_OVERRIDE
from raften.matcher import pattern_specificity, patterns_provably_disjoint


class PatternAmbiguities:
    def __init__(self, validator: Validator) -> None:
        self.validator = validator
        self.groups: dict[tuple[int, ...], list[tuple[int, str]]] = {}

    def add(self, index: int, pattern: str, field_path: str) -> None:
        group = self.groups.setdefault(pattern_specificity(pattern), [])
        for other_index, other_pattern in group:
            self.validator.compare_pattern(field_path)
            if not patterns_provably_disjoint(other_pattern, pattern):
                self.validator.add(
                    CFG_AMBIGUOUS_OVERRIDE, field_path,
                    "equal-specificity patterns are not provably disjoint",
                    details=(("other_index", other_index), ("other_pattern", other_pattern)),
                )
                break
        group.append((index, pattern))
