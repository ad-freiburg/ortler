"""
QLever API functions for SPARQL query retrieval and execution.
"""

import os
from typing import Any

import requests


def get_sparql_query(short_hash: str) -> str:
    """
    Get a SPARQL query from the QLever link API using a short hash (e.g., 'PZGwbS').
    """
    link_api = os.environ.get("QLEVER_LINK_API", "https://qlever.dev/api/link/")
    url = f"{link_api}{short_hash}/"

    response = requests.get(url)
    response.raise_for_status()

    data = response.json()
    return data["content"]


def issue_sparql_query(query: str) -> dict[str, Any]:
    """
    Execute a SPARQL query against the QLever query API (with Basic auth).
    """
    query_api = os.environ.get("QLEVER_QUERY_API", "")
    username = os.environ.get("QLEVER_QUERY_API_USERNAME", "")
    password = os.environ.get("QLEVER_QUERY_API_PASSWORD", "")

    # Add http:// if no protocol specified
    if query_api and not query_api.startswith(("http://", "https://")):
        query_api = f"http://{query_api}"

    auth = (username, password) if username and password else None

    response = requests.get(
        query_api,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        auth=auth,
    )
    response.raise_for_status()

    return response.json()


def _convert_email_profile_to_email(profile_id: str) -> str:
    """
    Convert email-as-profile IDs like ~ida_mele_at_iasi_cnr_it to email addresses.
    Returns the original profile_id if it doesn't match the pattern.
    """
    if "_at_" not in profile_id:
        return profile_id

    # Remove ~ prefix if present
    pid = profile_id.lstrip("~")

    # Split on _at_ to get local part and domain
    parts = pid.split("_at_", 1)
    if len(parts) != 2:
        return profile_id

    local_part, domain = parts
    # Replace underscores with dots in domain (e.g., iasi_cnr_it -> iasi.cnr.it)
    domain = domain.replace("_", ".")

    return f"{local_part}@{domain}"


def _extract_value(cell: dict) -> str:
    """
    Extract a display value from a SPARQL result cell.
    For URIs, extracts the last path component or fragment.
    For literals, unescapes common escape sequences and returns the value.
    """
    cell_type = cell.get("type", "")
    value = cell.get("value", "")

    if cell_type == "uri":
        # Extract last component from URI
        # e.g., "https://openreview.net/profile?id=~User1" -> "~User1"
        # e.g., "http://example.org/foo#bar" -> "bar"
        if "?id=" in value:
            return value.split("?id=")[-1]
        elif "#" in value:
            return value.split("#")[-1]
        elif "/" in value:
            return value.rstrip("/").split("/")[-1]
        return value
    else:
        return value


def query_results_by_recipient(hash_or_url: str) -> tuple[list[str], dict[str, dict]]:
    """
    Execute a SPARQL query and return results keyed by recipient.

    Returns:
        (recipients, data_by_recipient) where:
        - recipients: list of profile IDs/emails (from first column with profile IRIs)
        - data_by_recipient: dict mapping each recipient to {variable: value, ...}
          for all other variables in that row
    """
    short_hash = hash_or_url.rstrip("/").split("/")[-1]
    query = get_sparql_query(short_hash)
    result = issue_sparql_query(query)

    bindings = result.get("results", {}).get("bindings", [])
    if not bindings:
        raise ValueError("Query returned no results")

    variables = result.get("head", {}).get("vars", [])
    profile_prefix = "https://openreview.net/profile?id="

    # Find first column where all values are profile IRIs
    recipient_var = None
    for var in variables:
        all_match = True
        for row in bindings:
            cell = row.get(var, {})
            if cell.get("type") != "uri":
                all_match = False
                break
            value = cell.get("value", "")
            if not value.startswith(profile_prefix):
                all_match = False
                break
        if all_match:
            recipient_var = var
            break

    if not recipient_var:
        raise ValueError("No column found with profile IRIs")

    # Build recipients list and data mapping
    recipients = []
    data_by_recipient: dict[str, dict] = {}

    for row in bindings:
        # Extract recipient ID
        recipient_cell = row.get(recipient_var, {})
        profile_id = recipient_cell.get("value", "")[len(profile_prefix) :]
        recipient = _convert_email_profile_to_email(profile_id)
        recipients.append(recipient)

        # Extract all other variables for this recipient
        row_data = {}
        for var in variables:
            if var != recipient_var:
                cell = row.get(var, {})
                row_data[var] = _extract_value(cell)
        data_by_recipient[recipient] = row_data

    return recipients, data_by_recipient


def recipients_from_query(hash_or_url: str) -> list[str]:
    """
    Get OpenReview profile IDs from a SPARQL query result. Finds the first
    column where all values are profile IRIs, extracts the profile IDs, and
    returns them as a list. Accepts a short hash or full URL.
    Converts email-as-profile IDs to actual email addresses.
    """
    recipients, _ = query_results_by_recipient(hash_or_url)
    return recipients
