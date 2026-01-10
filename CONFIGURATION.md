# Configuration Guide

## Environment Variables

The OpenReview CLI tool uses environment variables for configuration. This keeps sensitive credentials out of the codebase.

### Setup

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your credentials:
   ```bash
   OPENREVIEW_USERNAME=your.email@example.com
   OPENREVIEW_PASSWORD=your-password-here
   ```

3. The `.env` file is already in `.gitignore` and will never be committed.

### Available Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENREVIEW_API_URL` | No | `https://devapi2.openreview.net` | OpenReview API endpoint |
| `OPENREVIEW_USERNAME` | Yes | None | Your OpenReview username/email |
| `OPENREVIEW_PASSWORD` | Yes | None | Your OpenReview password |
| `OPENREVIEW_VENUE_ID` | No | `SIGIR/2026/Test` | Venue ID to use |
| `OPENAI_API_KEY` | For `--random` | None | OpenAI API key for paper generation |

### Using Environment Variables

**Option 1: Use `.env` file (Recommended)**

The `.env` file is **automatically loaded** when you run the `ortler` command. Just create it and you're done:

```bash
cp .env.example .env
# Edit .env with your credentials
ortler submissions  # Works automatically!
```

**Option 2: Export directly**
```bash
export OPENREVIEW_USERNAME="your.email@example.com"
export OPENREVIEW_PASSWORD="your-password"
ortler submissions
```

**Option 3: Command-line arguments (override env vars)**
```bash
ortler --username your.email@example.com --password your-password submissions
```

### Precedence Order

Command-line arguments override environment variables:

1. Command-line flags (`--username`, `--password`, etc.)
2. Environment variables (`$OPENREVIEW_USERNAME`, etc.)
3. Built-in defaults (if any)

### Security Best Practices

- ✅ **DO** use `.env` files for local development
- ✅ **DO** use environment variables in production/CI
- ✅ **DO** keep `.env` in `.gitignore`
- ❌ **DON'T** commit credentials to version control
- ❌ **DON'T** share your `.env` file
- ❌ **DON'T** hardcode credentials in the code
