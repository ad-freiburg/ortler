"""
Generic handling of custom stages for ortler.

Reads stage definitions from JSON files in custom-stages/ directory,
fetches responses from OpenReview API, and generates RDF triples.
"""

import json
from pathlib import Path
from typing import Any

from .log import log
from .rdf import Rdf


def load_stage_definition(stage_path: Path) -> dict[str, Any]:
    """Load a custom stage definition from JSON file."""
    with open(stage_path) as f:
        return json.load(f)


def build_enum_mapping(stage_def: dict[str, Any]) -> dict[str, dict[str, str]]:
    """
    Build mapping from enum values to ortler short values for all fields.
    Returns: {field_name: {long_value: short_value}}
    """
    mapping = {}
    content = stage_def.get("content", {})

    for field_name, field_def in content.items():
        param = field_def.get("value", {}).get("param", {})
        enum_values = param.get("enum", [])
        ortler_values = param.get("ortler", [])

        if enum_values and ortler_values and len(enum_values) == len(ortler_values):
            mapping[field_name] = dict(zip(enum_values, ortler_values))

    return mapping


def fetch_stage_responses(
    client, venue_id: str, stage_def: dict[str, Any]
) -> dict[str, dict[str, str]]:
    """
    Fetch all responses for a custom stage from OpenReview API.
    Returns: {author_id: {field_name: value}}
    """
    stage_name = stage_def.get("name", "")
    committee = stage_def.get("committee", "Authors")

    # Build invitation ID based on committee
    if committee.lower() == "authors":
        invitation_id = f"{venue_id}/Authors/-/{stage_name}"
    else:
        invitation_id = f"{venue_id}/-/{stage_name}"

    try:
        notes = list(client.get_all_notes(invitation=invitation_id))
    except Exception as e:
        log.warning(f"Failed to fetch responses for {stage_name}: {e}")
        return {}

    # Build enum mapping for value translation
    enum_mapping = build_enum_mapping(stage_def)

    # Extract responses
    responses = {}
    content_fields = stage_def.get("content", {}).keys()

    for note in notes:
        author_id = note.signatures[0] if note.signatures else None
        if not author_id:
            continue

        note_content = note.content or {}
        response = {}

        for field_name in content_fields:
            raw_value = note_content.get(field_name, {})
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("value", "")

            # Map to ortler short value if available
            if field_name in enum_mapping and raw_value in enum_mapping[field_name]:
                response[field_name] = enum_mapping[field_name][raw_value]
            else:
                response[field_name] = raw_value or ""

        responses[author_id] = response

    return responses


def add_stage_triples(
    rdf: Rdf, stage_def: dict[str, Any], responses: dict[str, dict[str, str]]
) -> None:
    """
    Add RDF triples for all responses to a custom stage.
    Predicate names are :task_{field_name}.
    """
    for author_id, response in responses.items():
        person_iri = rdf.personIri(author_id)

        for field_name, value in response.items():
            predicate = f":task_{field_name}"
            rdf.add_triple(
                person_iri,
                predicate,
                rdf.literal(value) if value else ":novalue",
            )


def get_all_stage_definitions(
    stages_dir: str = "custom-stages",
) -> list[dict[str, Any]]:
    """Load all custom stage definitions from the stages directory."""
    stages_path = Path(stages_dir)
    if not stages_path.exists():
        return []

    definitions = []
    for json_file in stages_path.glob("*.json"):
        try:
            definitions.append(load_stage_definition(json_file))
        except Exception as e:
            log.warning(f"Failed to load stage definition {json_file}: {e}")

    return definitions
