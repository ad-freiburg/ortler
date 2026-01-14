# ortler

Ortler is a powerful and versatile command-line tool for managing OpenReview venues.
It provides commands for syncing venue data to a local cache, managing committee recruitment,
tracking submissions, and sending emails via the OpenReview API. It is named after OpenReview
and a beautiful mountain in the Alps.

<img width="1476" height="431" alt="image" src="https://github.com/user-attachments/assets/4298fc2f-16c4-489a-9a70-858fc03b65b3" />

## Quickstart

### Installation and updates

```bash
# Install with pipx (recommended)
pipx install ortler

# Get latest version
pipx upgrade ortler

# Or install in editable mode for development
git clone git@github.com:ad-freiburg/ortler.git
cd ortler
pipx install -e .

# Get latest version from git:w
git pull
```

### Configuration

Create a `.env` file with your OpenReview credentials (see `.env.example`):

```bash
OPENREVIEW_API_URL=https://api2.openreview.net
OPENREVIEW_USERNAME=your.email@example.com
OPENREVIEW_PASSWORD=your-password
OPENREVIEW_VENUE_ID=Your/Venue/ID
OPENREVIEW_IMPERSONATE_GROUP=Your/Venue/ID
MAIL_FROM=Your Choice <your-choice@openreview.net>
```

If you want to use `ortler mail` with `--recipients-from-sparql-query`, you
also need to and provide the API of a SPARQL endpoint (e.g., QLever), and a
username and password in case that endpoint requires authentication:

```bash
QLEVER_LINK_API=https://qlever.dev/api/link/
QLEVER_QUERY_API=https://qlever.dev/api/...
QLEVER_QUERY_API_USERNAME=username
QLEVER_QUERY_API_PASSWORD=password
```

If you want to use commands that require a language model (like `ortler
ai-review`), you also need to provide an API key for that model:

```bash
OPENAI_API_KEY=your-openai-api-key
```

### Usage

```bash
ortler --help                  # Show all commands
ortler COMMAND --help          # Show help for a specific command
```

## Commands

### update

Sync venue data from OpenReview to a local cache. The cache enables fast queries and RDF export without repeated API calls.

```bash
# Incremental update (only fetch changes since last update)
ortler update

# Preview what would be updated
ortler update --dry-run

# Force re-fetch of all submissions
ortler update --recache submissions

# Force re-fetch of all profiles with publications
ortler update --recache profiles-with-publications

# Force re-fetch only of the specified profiles
ortler update --profiles ~John_Doe1 ~Jane_Doe2

# Force re-fetch of everything
ortler update --recache all
```

### dump

Export all cached data as RDF (Turtle format) for use with SPARQL engines like QLever.

```bash
# Output to stdout
ortler dump

# Output to file
ortler dump --output data.ttl
```

The RDF output includes triples for the following; just run it and inspect if
yourself, Turtle is quite readable for humans:
- Committee members (reviewers, area chairs, senior area chairs) with roles and status
- Submissions with titles, abstracts, authors, and status
- Profile data including affiliations and publications

### recruitment

Manage committee membership (reviewers, area chairs, senior area chairs).

```bash
# Search for a user and show their group memberships
ortler recruitment --search user@example.com
ortler recruitment --search ~John_Doe1

# Add users to the reviewer pool
ortler recruitment --role pc --add invited user1@example.com user2@example.com

# Remove a user from the invited list
ortler recruitment --role pc --remove invited user@example.com

# Set reduced review load for a member
ortler recruitment --role pc --set-reduced-load ~John_Doe1 2
```

Roles: `pc` (reviewers), `spc` (area chairs), `ac` (senior area chairs)

### mail

Send emails via the OpenReview API. Emails are defined in a file with headers and body separated by a blank line.

```bash
# Preview email without sending
ortler mail message.txt --dry-run

# Send to a test recipient first
ortler mail message.txt --test-run ~Your_Profile1

# Send emails with recipients from a SPARQL query
ortler mail message.txt --recipients-from-sparql-query QUERY_HASH
```

Example email file; the `{{name}}` placeholder will be replaced with the
recipient's first name if that information is available, otherwise the full
name. If the Cc is provided, a single email is sent to that address, with
the list of recipients, a link to the SPARQL query, and the mail body.
```
To: ~Recipient_Profile1 ~Recipient_Profile2 ...
Subject: Your subject line
Cc: ...
Reply-To: ...

Dear {{name}},

This is an email from the `ortler` tool, we hope that you like it!

Best regards,

The robots from the future
```

Example with SPARQL query; the `{{name}}` placeholder will be replaced just
like above; the list of recipients is determined by the first column of the
query result, where all values are profile IRIs; other columns of the result
can be used as additional placeholders in the email body, where, for example, 
`{{titles}}` will be replaced by the content of the `?titles` variable.
```
# Query: https://qlever.dev/name-of-endpoint/QUERY_HASH
To: (will be replaced by profile IDs from query result)
Subject: Your submissions
Cc: ...
Reply-To: ...

Dear {{name}},

You have submitted the following papers, just so you know:

{{titles}}

Best regards ...
```

## Other Commands

Run `ortler --help` to see all available commands and `ortler COMMAND --help`
for details on each command.
