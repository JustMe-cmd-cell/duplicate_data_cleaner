# -*- coding: utf-8 -*-
import unicodedata
import re


def normalize_phone(phone):
    """Strip all non-digit characters for phone comparison."""
    if not phone:
        return ''
    return re.sub(r'\D', '', phone)


def levenshtein_distance(s1, s2):
    """
    Compute the Levenshtein distance between two strings.
    Used to detect near-duplicate names without external libraries.
    """
    s1 = s1.lower().strip()
    s2 = s2.lower().strip()
    if s1 == s2:
        return 0
    len1, len2 = len(s1), len(s2)
    if len1 == 0:
        return len2
    if len2 == 0:
        return len1

    # Use a rolling array to keep memory O(min(len1,len2))
    if len1 < len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    prev = list(range(len2 + 1))
    for i, c1 in enumerate(s1, 1):
        curr = [i]
        for j, c2 in enumerate(s2, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (c1 != c2)))
        prev = curr
    return prev[len2]


def name_similarity_score(name1, name2):
    """
    Return a similarity score between 0.0 and 1.0.
    1.0 = identical, 0.0 = completely different.
    Based on normalised Levenshtein similarity.
    """
    if not name1 or not name2:
        return 0.0
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)
    if n1 == n2:
        return 1.0
    max_len = max(len(n1), len(n2))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(n1, n2)
    return 1.0 - dist / max_len


def _normalize_name(name):
    """Lowercase, strip accents, remove extra spaces."""
    name = name.lower().strip()
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    name = re.sub(r'\s+', ' ', name)
    return name
