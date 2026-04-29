# AtlasDB

## Setup

```bash
pip install -r requirements.txt
```

## Usage

_Coming soon._

## Security before committing

Install dev tools and activate the pre-commit hook (one-time setup):

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Run all hooks manually against every tracked file:

```bash
pre-commit run --all-files
```

After the hook is installed, it runs automatically on every `git commit`.
If `detect-secrets` flags a false positive, audit it and add an inline
`# pragma: allowlist secret` comment, then regenerate the baseline:

```bash
detect-secrets scan --exclude-files 'requirements\.txt' > .secrets.baseline
```
