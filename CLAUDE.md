# OpenReview CLI Tool (ortler)

## Project Structure
- CLI tool for OpenReview API with commands: `update`, `dump`, `profile`, `submissions`, `recruitment`, `mail`
- Cache-based workflow: `update` syncs with OpenReview, `dump` outputs cached data as RDF
- Uses singleton client pattern for API authentication (both v1 and v2 APIs)

## Key Files
- `src/ortler/main.py`: CLI entry point with argparse
- `src/ortler/client.py`: Singleton OpenReview client management (v1 and v2 APIs)
- `src/ortler/profile.py`: ProfileWithPapers class with caching and RDF export
- `src/ortler/rdf.py`: Rdf class for triple collection and Turtle serialization
- `src/ortler/qlever.py`: QLever SPARQL query functions
- `src/ortler/commands/`: Individual command implementations
  - `update.py`: Incremental cache sync with OpenReview
  - `dump.py`: Output all cached data as RDF
  - `recruitment.py`: Manage PC/SPC/AC membership
  - `submissions.py`: Show cached submission summary
  - `mail.py`: Send emails via OpenReview API

## OpenReview APIs
OpenReview has TWO APIs that must both be queried to get complete data:
- **API v2** (`api2.openreview.net`): Current API, newer submissions
- **API v1** (`api.openreview.net`): Legacy API, contains most DBLP/ORCID imports

The `get_client()` and `get_client_v1()` functions in `client.py` provide singleton access to both.

## Authentication & Environment
Set in `.env` file:
```
OPENREVIEW_API_URL=https://api2.openreview.net
OPENREVIEW_USERNAME=your_email
OPENREVIEW_PASSWORD=your_password
OPENREVIEW_VENUE_ID=Your/Venue/ID
OPENREVIEW_IMPERSONATE_GROUP=venue_organizer_group
RDF_DEFAULT_PREFIX=http://openreview.net/
CACHE_DIR=cache
MAIL_FROM=Your Name <your-venue@openreview.net>
QLEVER_LINK_API=https://qlever.dev/api/link/
QLEVER_QUERY_API=https://qlever.dev/api/your-backend
QLEVER_QUERY_API_USERNAME=username
QLEVER_QUERY_API_PASSWORD=password
```

## RDF System
- `Rdf` class collects triples via `add_triple(subject, predicate, object)`
- `as_turtle()` outputs proper Turtle format with semicolons/commas
- Prefixes: `paper:` for papers/submissions, `person:` for profiles
- `paperIri()` handles IDs starting with `-` by using full IRI form
- Person triples: `:id`, `:state`, `:role`, `:status`, `:gender`, `:dblp_id`, `:orcid`, `:email`, `:position`, `:institution`, `:publication`, `:dblp_publication`, `:num_publications`
- Submission triples: `:status` (active/deleted/withdrawn/desk_rejected), `:title`, `:abstract`, `:author`, `:authors`, `:num_authors`, `:has_pdf`, `:created_on`, `:last_modified_on`, AI review fields

## Mail Command
- Sends emails via OpenReview API from a file with headers and body
- Supports `{{name}}` placeholder for personalized emails
- `--recipients-from-sparql-query HASH_OR_URL`: Replace To: field with SPARQL query results
- Converts email-as-profile IDs (like `~user_at_domain_com`) to actual emails
- Continues on failure and reports success/failure counts

## QLever Integration
- `get_sparql_query(short_hash)`: Fetch query from QLever link API
- `issue_sparql_query(query)`: Execute SPARQL query
- `recipients_from_query(hash_or_url)`: Get profile IDs from query results

## Code Style
Each .py file should be formatted according to `ruff format FILE && ruff check --fix FILE`

## Logging
Use `from .log import log` and then `log.info()`, `log.warning()`, `log.error()` for all output messages. Do not use `print()` for logging.

## Cache Structure
The cache directory (set via `CACHE_DIR` or `--cache-dir`) contains:
- `metadata.json`: Last update timestamp
- `profiles/`: Profile JSON files (by canonical ID, e.g., `User_Name1.json`)
- `profiles/_id_mapping.json`: Email → canonical profile ID mapping
- `submissions/`: Submission JSON files
- `groups/`: Group membership (Reviewers.json, Area_Chairs.json, etc.)
- `recruitment/reduced_loads.json`: Reduced load entries
- `reviews/`: AI review JSON files
- `pdfs/`: Downloaded submission PDFs

**Important:** Groups cache stores members by email address (e.g., `user@example.com`), not profile ID. The `_id_mapping.json` file maps emails to canonical profile IDs (e.g., `~User_Name1`).

## Profile State
Profiles have a `state` field (not included in OpenReview's `to_json()`) that indicates their status:
- `Active Institutional` - Verified institutional email
- `Active` - Manually activated
- `Active Automatic` - Auto-activated
- `Needs Moderation` - Awaiting review
- `Inactive` - Deactivated
- `Rejected` - Profile rejected
- `Blocked` - Account blocked

The `state` field is saved to cache and output as `:state` triple in RDF.

## Update Command and --recache Options
The `update` command syncs the cache with OpenReview:
- `ortler update` - Incremental update (only changed data since last update)
- `ortler update --recache submissions` - Re-fetch all submissions
- `ortler update --recache profiles` - Re-fetch profile metadata only (1 API call per profile)
- `ortler update --recache profiles-with-publications` - Re-fetch profiles + publications (3 API calls per profile)
- `ortler update --recache all` - Re-fetch submissions + profiles-with-publications

The options are NOT hierarchical (except `profiles` < `profiles-with-publications`). DBLP publication scanning only runs during incremental updates.

The update command fetches all submission types: active (`Submission`), withdrawn (`Withdrawn_Submission`), and desk-rejected (`Desk_Rejected_Submission`). It uses `trash=True` to include soft-deleted submissions.

Submission `:status` is derived from:
- `ddate` field present → "deleted" (soft delete, greyed out in UI)
- `Withdrawn_Submission` invitation → "withdrawn"
- `Desk_Rejected_Submission` invitation → "desk_rejected"
- Otherwise → "active"

## Common Workflow
1. `ortler update` - Sync cache with OpenReview (incremental)
2. `ortler update --recache all` - Force full cache refresh
3. `ortler dump --output data.rdf` - Output all cached data as RDF
4. `ortler submissions` - Show summary of cached submissions
5. `ortler recruitment --role pc --add invited user@example.com` - Add to PC

## Recruitment Command
- `ortler recruitment --search USER` - Search by profile ID or email, shows group memberships and recruitment notes (queries live API, not cache)
- `ortler recruitment --role pc --add invited USER` - Add user to PC Invited group
- `ortler recruitment --role pc --remove invited USER` - Remove user from PC Invited group
- `ortler recruitment --role pc --set-reduced-load ~User1 2` - Set reduced load (requires existing recruitment note)

Roles: `pc` (Reviewers), `spc` (Area Chairs), `ac` (Senior Area Chairs)

**Note:** `--set-reduced-load` only works for users who responded to recruitment via OpenReview. Users added directly to groups have no recruitment note and cannot have reduced_load set via API.

## Other Commands
- `ortler profile ~User_Name1 --as-rdf`: Get single profile with RDF output
- `ortler mail message.txt --dry-run`: Preview email without sending
- `ortler mail message.txt --recipients-from-sparql-query HASH`: Send to SPARQL results

## Rate Limiting
OpenReview API has rate limits (3 requests per time window). Use cache-based workflow to minimize API calls. If rate limited, wait ~30 seconds.
