"""
RDF helper functions for OpenReview data export.
"""

import os
import re
from datetime import datetime, timezone
from typing import List, Any, Dict
from collections import defaultdict


def get_rdf_default_prefix() -> str:
    """
    Get the RDF default prefix URL from environment variable or .env file.
    """
    return os.environ.get("RDF_DEFAULT_PREFIX", "http://example.org/")


def escape_rdf_literal(value: str) -> str:
    """
    Escape a string value for use in RDF literals.
    """
    # Escape backslashes first, then quotes and newlines
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return value


class Rdf:
    """
    RDF utility class for generating IRIs and literals and collecting triples.
    """

    def __init__(self, prefixes: dict[str, str] | None = None):
        default_prefix = os.environ.get("RDF_DEFAULT_PREFIX", "http://openreview.net/")
        self.prefixes = {
            "": default_prefix,
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "paper": "https://openreview.net/forum?id=",
            "person": "https://openreview.net/profile?id=~",
        }
        if prefixes:
            self.prefixes.update(prefixes)
        self.triples: list[tuple[str, str, str]] = []

    def add_triple(self, subject: str, predicate: str, object: str) -> None:
        """
        Add a triple to the collection.
        """
        self.triples.append((subject, predicate, object))

    def as_turtle(self) -> str:
        """
        Serialize triples as Turtle format with proper formatting.
        """
        lines = []

        # Add prefix declarations
        for prefix, uri in self.prefixes.items():
            if prefix == "":
                lines.append(f"@prefix : <{uri}> .")
            else:
                lines.append(f"@prefix {prefix}: <{uri}> .")

        # Empty line after prefixes
        lines.append("")

        # Group triples by subject
        if not self.triples:
            return "\n".join(lines)

        by_subject: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for s, p, o in self.triples:
            by_subject[s].append((p, o))

        # Serialize each subject group
        for subject, pred_objs in by_subject.items():
            # Group by predicate within each subject
            by_pred: dict[str, list[str]] = defaultdict(list)
            for p, o in pred_objs:
                by_pred[p].append(o)

            # Write the subject and first predicate
            pred_items = list(by_pred.items())
            if pred_items:
                first_pred, first_objs = pred_items[0]
                # Write first object
                lines.append(f"{subject} {first_pred} {first_objs[0]}")
                # Write additional objects for first predicate with comma
                for obj in first_objs[1:]:
                    lines[-1] += f", {obj}"

                # Write remaining predicates with semicolon
                for pred, objs in pred_items[1:]:
                    lines[-1] += " ;"
                    # First object of new predicate
                    lines.append(f"  {pred} {objs[0]}")
                    # Additional objects with comma
                    for obj in objs[1:]:
                        lines[-1] += f", {obj}"

                # End with period
                lines[-1] += " ."

        return "\n".join(lines)

    def paperIri(self, paper_id: str) -> str:
        """
        Create a paper IRI from an OpenReview paper/submission ID.
        Uses full IRI if ID starts with invalid prefix character (e.g., hyphen).
        """
        if paper_id and paper_id[0] == "-":
            return f"<{self.prefixes['paper']}{paper_id}>"
        return f"paper:{paper_id}"

    def _is_valid_prefixed_name(self, local_name: str) -> bool:
        """
        Check if a string can be used as the local part of a Turtle prefixed name.
        Valid: letters, numbers, underscores, hyphens, dots (not at end).
        Invalid: @, spaces, apostrophes, trailing dots.
        """
        if not local_name:
            return False
        if local_name.endswith("."):
            return False
        # Check for characters that are not allowed in prefixed names
        for char in local_name:
            if char in "@ '":
                return False
        return True

    def personIri(self, person_id: str) -> str:
        """
        Create a person IRI from a person ID.
        Uses prefixed name if valid, otherwise full IRI.
        """
        # Remove ~ prefix
        local_name = person_id.lstrip("~")

        if self._is_valid_prefixed_name(local_name):
            return f"person:{local_name}"
        else:
            return f"<{self.prefixes['person']}{local_name}>"

    def literal(self, value: str) -> str:
        """
        Format a string as an RDF literal.
        """
        escaped = escape_rdf_literal(value)
        return f'"{escaped}"'

    def literalFromJson(self, obj: Dict[str, Any], path: str) -> str:
        """
        Get a value from a JSON object via a path and return as RDF literal.
        """
        current = obj
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current.get(key)
            else:
                return ":novalue"

        # If we got a value, return it as a literal
        if current and isinstance(current, str):
            return self.literal(current)
        elif current is not None and not isinstance(current, (dict, list)):
            # Handle other types (numbers, booleans)
            return self.literal(str(current))
        else:
            return ":novalue"

    def iriFromJson(self, obj: Dict[str, Any], path: str, prefix: str) -> str:
        """
        Get a value from a JSON object via a path and return as prefixed IRI.
        """
        current = obj
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current.get(key)
            else:
                return ":novalue"

        # If we got a value, return it as a prefixed IRI
        if current and isinstance(current, str):
            if prefix == "person":
                return self.personIri(current)
            else:
                # Basic cleaning for other prefixes
                clean_id = current.replace(" ", "_")
                return f"{prefix}:{clean_id}"
        elif current is not None and not isinstance(current, (dict, list)):
            # Handle other types (numbers, booleans)
            return f"{prefix}:{str(current)}"
        else:
            return ":novalue"

    def urlFromJson(
        self, obj: Dict[str, Any], path: str, fallback: str = ":novalue"
    ) -> str:
        """
        Get a URL from a JSON object via a path and return as full IRI with angle brackets.
        """
        current = obj
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current.get(key)
            else:
                return fallback

        # If we got a URL, return it as a full IRI
        if current and isinstance(current, str):
            return f"<{current}>"
        else:
            return fallback

    def valuesFromJson(self, obj: Dict[str, Any], path: str) -> List[Any]:
        """
        Get an array of values from a JSON object via a path.
        """
        current = obj
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current.get(key)
            else:
                return []

        # If we got a list, return it; otherwise return empty list
        if isinstance(current, list):
            return current
        else:
            return []

    def dateTimeFromTimestamp(self, timestamp_ms: int | None) -> str:
        """
        Convert milliseconds timestamp to xsd:dateTime literal.
        Returns :novalue if timestamp is None or falsy.
        """
        if not timestamp_ms:
            return ":novalue"
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return f'"{dt.strftime("%Y-%m-%dT%H:%M:%SZ")}"^^xsd:dateTime'

    def dblpUrlFromBibtex(self, paper: Dict[str, Any]) -> str:
        """
        Extract DBLP URL from a paper's _bibtex field.
        Handles both API v1 (string) and API v2 (dict with value key) formats.
        Returns the URL as a full IRI with angle brackets, or empty string if not found.
        """
        bibtex_field = paper.get("content", {}).get("_bibtex", "")
        # Handle both string and dict formats
        if isinstance(bibtex_field, dict):
            bibtex = bibtex_field.get("value", "")
        else:
            bibtex = bibtex_field
        if bibtex and isinstance(bibtex, str):
            # Parse DBLP key from bibtex entry like @inproceedings{DBLP:conf/emnlp/...,
            match = re.search(r"@\w+\{DBLP:([^,]+),", bibtex)
            if match:
                return f"<https://dblp.org/rec/{match.group(1)}>"
        return ""
