"""
Generic handling of custom stages for ortler.

Reads stage definitions from JSON files in custom-stages/ directory,
fetches responses from OpenReview API, and generates RDF triples.

Supports two types of stages:
- Per-user stages: responses keyed by author/user ID (e.g., DBLP certification)
- Per-submission stages: responses keyed by submission ID (e.g., initial checks)
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


def is_per_submission_stage(stage_def: dict[str, Any]) -> bool:
    """Check if a stage is per-submission (vs per-user)."""
    return stage_def.get("reply_to") == "forum"


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


def _extract_response_fields(
    note_or_dict, content_fields: list[str], enum_mapping: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Extract response fields from a note or dict, applying enum mapping."""
    # Handle both Note objects and dicts
    if hasattr(note_or_dict, "content"):
        content = note_or_dict.content or {}
    else:
        content = note_or_dict.get("content", {})

    response = {}
    for field_name in content_fields:
        raw_value = content.get(field_name, {})
        if isinstance(raw_value, dict):
            raw_value = raw_value.get("value", "")

        # Map to ortler short value if available
        if field_name in enum_mapping and raw_value in enum_mapping[field_name]:
            response[field_name] = enum_mapping[field_name][raw_value]
        else:
            response[field_name] = raw_value or ""

    return response


def fetch_stage_responses(
    client, venue_id: str, stage_def: dict[str, Any]
) -> dict[str, dict[str, str]]:
    """
    Fetch all responses for a custom stage from OpenReview API.

    For per-user stages: Returns {user_id: {field_name: value}}
    For per-submission stages: Returns {submission_id: {field_name: value, "_responder": user_id}}
    """
    stage_name = stage_def.get("name", "")

    if is_per_submission_stage(stage_def):
        return _fetch_per_submission_responses(client, venue_id, stage_def)

    # Per-user stage
    committee = stage_def.get("committee", "Authors")
    if committee.lower() == "authors":
        invitation_id = f"{venue_id}/Authors/-/{stage_name}"
    else:
        invitation_id = f"{venue_id}/-/{stage_name}"

    try:
        notes = list(client.get_all_notes(invitation=invitation_id))
    except Exception as e:
        log.warning(f"Failed to fetch responses for {stage_name}: {e}")
        return {}

    enum_mapping = build_enum_mapping(stage_def)
    content_fields = list(stage_def.get("content", {}).keys())

    responses = {}
    for note in notes:
        user_id = note.signatures[0] if note.signatures else None
        if not user_id:
            continue
        responses[user_id] = _extract_response_fields(
            note, content_fields, enum_mapping
        )

    return responses


def _fetch_per_submission_responses(
    client, venue_id: str, stage_def: dict[str, Any]
) -> dict[str, dict[str, str]]:
    """
    Fetch responses for a per-submission stage.
    Uses details="replies" to efficiently get all submissions with their replies
    in a single query, then filters for the specific stage.
    Returns: {submission_id: {field_name: value, "_responder": user_id}}
    """
    stage_name = stage_def.get("name", "")

    # Get all submissions with replies in one query (much faster than iterating)
    try:
        submissions = list(
            client.get_all_notes(
                invitation=f"{venue_id}/-/Submission", details="replies"
            )
        )
    except Exception as e:
        log.warning(f"Failed to fetch submissions with replies for {stage_name}: {e}")
        return {}

    enum_mapping = build_enum_mapping(stage_def)
    content_fields = list(stage_def.get("content", {}).keys())

    responses = {}
    for sub in submissions:
        if not hasattr(sub, "details") or not sub.details:
            continue
        replies = sub.details.get("replies", [])

        for reply in replies:
            # Check if this reply is for our stage
            reply_invs = reply.get("invitations", [])
            if not any(stage_name in inv for inv in reply_invs):
                continue

            submission_id = sub.id
            responder_id = reply.get("signatures", [""])[0]
            if not responder_id:
                continue

            response = _extract_response_fields(reply, content_fields, enum_mapping)
            response["_responder"] = responder_id
            responses[submission_id] = response

    return responses


def add_stage_triples(
    rdf: Rdf, stage_def: dict[str, Any], responses: dict[str, dict[str, str]]
) -> None:
    """
    Add RDF triples for all responses to a custom stage.

    For per-user stages: triples on person IRI with predicate :task_{field}
    For per-submission stages: triples on paper IRI with predicate :task_{stage}_{field}
    """
    if is_per_submission_stage(stage_def):
        _add_per_submission_triples(rdf, stage_def, responses)
    else:
        _add_per_user_triples(rdf, stage_def, responses)


def _add_per_user_triples(
    rdf: Rdf, stage_def: dict[str, Any], responses: dict[str, dict[str, str]]
) -> None:
    """Add RDF triples for per-user stage responses."""
    for user_id, response in responses.items():
        person_iri = rdf.personIri(user_id)

        for field_name, value in response.items():
            predicate = f":task_{field_name}"
            rdf.add_triple(
                person_iri,
                predicate,
                rdf.literal(value) if value else ":novalue",
            )


def _add_per_submission_triples(
    rdf: Rdf, stage_def: dict[str, Any], responses: dict[str, dict[str, str]]
) -> None:
    """Add RDF triples for per-submission stage responses."""
    stage_name = stage_def.get("name", "").lower()

    for submission_id, response in responses.items():
        paper_iri = rdf.paperIri(submission_id)

        for field_name, value in response.items():
            if field_name == "_responder":
                # Link to the responder as a person
                predicate = f":task_{stage_name}_responder"
                rdf.add_triple(paper_iri, predicate, rdf.personIri(value))
            else:
                predicate = f":task_{stage_name}_{field_name}"
                rdf.add_triple(
                    paper_iri,
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
