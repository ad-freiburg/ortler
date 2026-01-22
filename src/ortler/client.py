"""
OpenReview client singleton management.
"""

import logging
import os
import sys

import openreview

from .log import log

# Redirect openreview/urllib3 messages to stderr (they default to stdout)
_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setFormatter(logging.Formatter("%(message)s"))
for _logger_name in ("openreview", "urllib3"):
    _logger = logging.getLogger(_logger_name)
    _logger.handlers.clear()
    _logger.addHandler(_stderr_handler)
    _logger.propagate = False

# Global client instances (singletons)
_client_instance = None
_client_v1_instance = None


def _handle_openreview_exception(e: openreview.OpenReviewException) -> None:
    """
    Handle OpenReview API exceptions with user-friendly error messages.
    """
    # Extract error details from exception args
    error_info = e.args[0] if e.args else {}
    error_name = error_info.get("name", "Error")
    error_message = error_info.get("message", str(e))

    if error_name == "RateLimitError":
        log.error(f"Rate limit exceeded: {error_message}")
    elif error_name == "ForbiddenError":
        log.error(f"Access denied: {error_message}")
    elif error_name == "NotFoundError":
        log.error(f"Not found: {error_message}")
    else:
        log.error(f"OpenReview API error: {error_message}")
    sys.exit(1)


def get_client() -> openreview.api.OpenReviewClient:
    """
    Get the singleton OpenReview client, creating it lazily on first use.

    Uses environment variables for configuration:
    - OPENREVIEW_API_URL
    - OPENREVIEW_USERNAME
    - OPENREVIEW_PASSWORD
    - OPENREVIEW_IMPERSONATE_GROUP (optional)
    """
    global _client_instance

    if _client_instance is None:
        try:
            # Create client from environment variables
            _client_instance = openreview.api.OpenReviewClient(
                baseurl=os.environ.get("OPENREVIEW_API_URL"),
                username=os.environ.get("OPENREVIEW_USERNAME"),
                password=os.environ.get("OPENREVIEW_PASSWORD"),
            )

            # Apply impersonation from environment if set
            impersonate = os.environ.get("OPENREVIEW_IMPERSONATE_GROUP")
            if impersonate:
                _client_instance.impersonate(impersonate)
        except openreview.OpenReviewException as e:
            _handle_openreview_exception(e)

    return _client_instance


def get_client_v1() -> openreview.Client:
    """
    Get the singleton OpenReview API v1 client, creating it lazily on first use.
    Used for fetching legacy data (DBLP/ORCID imports).

    Uses environment variables for configuration:
    - OPENREVIEW_API_URL (to derive v1 URL from v2 URL)
    - OPENREVIEW_USERNAME
    - OPENREVIEW_PASSWORD
    """
    global _client_v1_instance

    if _client_v1_instance is None:
        try:
            # Derive API v1 URL from API v2 URL
            api_url = os.environ.get(
                "OPENREVIEW_API_URL", "https://api2.openreview.net"
            )
            if "devapi2" in api_url:
                v1_url = "https://devapi.openreview.net"
            elif "api2" in api_url:
                v1_url = "https://api.openreview.net"
            else:
                # Fallback: assume production
                v1_url = "https://api.openreview.net"

            _client_v1_instance = openreview.Client(
                baseurl=v1_url,
                username=os.environ.get("OPENREVIEW_USERNAME"),
                password=os.environ.get("OPENREVIEW_PASSWORD"),
            )
        except openreview.OpenReviewException as e:
            _handle_openreview_exception(e)

    return _client_v1_instance


def set_client_params(
    baseurl: str = None,
    username: str = None,
    password: str = None,
    impersonate_group: str = None,
) -> None:
    """
    Override client parameters from command-line arguments.
    Must be called before get_client() to have effect.
    """
    if baseurl:
        os.environ["OPENREVIEW_API_URL"] = baseurl
    if username:
        os.environ["OPENREVIEW_USERNAME"] = username
    if password:
        os.environ["OPENREVIEW_PASSWORD"] = password
    if impersonate_group:
        os.environ["OPENREVIEW_IMPERSONATE_GROUP"] = impersonate_group
