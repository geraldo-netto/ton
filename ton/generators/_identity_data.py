"""Small built-in word lists for the identity generators.

Deliberately compact so TON keeps zero runtime dependencies. Callers
who need richer data should plug in their own generator via the
``ton.generators`` entry-point group.
"""

from __future__ import annotations

GIVEN_NAMES: tuple[str, ...] = (
    "Alex", "Ana", "Aria", "Aviv", "Bobby", "Cai", "Camila", "Chen",
    "Dara", "Diego", "Elena", "Eli", "Fatima", "Felix", "Gabi", "Hiro",
    "Ines", "Iggy", "Jordan", "Juno", "Kai", "Kira", "Leo", "Lin",
    "Mara", "Mateo", "Nadia", "Nico", "Omar", "Pia", "Quinn", "Rin",
    "Rui", "Sam", "Sofia", "Taro", "Uma", "Val", "Wei", "Yara", "Zane",
)

FAMILY_NAMES: tuple[str, ...] = (
    "Adams", "Brown", "Chen", "Davila", "Eriksen", "Fox", "Garcia", "Hayashi",
    "Ito", "Johnson", "Khan", "Lopez", "Mehta", "Novak", "Okafor", "Patel",
    "Quispe", "Rossi", "Silva", "Tanaka", "Underhill", "Vargas", "Wang",
    "Xu", "Yamamoto", "Zhang",
)

EMAIL_DOMAINS: tuple[str, ...] = (
    "example.com",
    "example.org",
    "example.net",
    "test.invalid",
)
