# MatrixGuard

## Overview

MatrixGuard is a Python Matrix room moderation bot with rules, anti-spam controls, warnings, and persistent event records.

## Features

- Flood, repeated-message, blocked-phrase, and link filtering
- Room rules, warning counts, redaction, and kick commands
- Join and moderation event logging
- SQLite persistence and matrix-nio encrypted-capable client support

## Commands

`!rules`, `!warn USER`, `!warnings [USER]`, `!clearwarnings USER`, `!redact EVENT_ID`, `!kick USER [reason]`, and `!matrixguard`.

## Requirements

Python 3.11+, a Matrix account and access token, plus sufficient room power level for enabled actions.

## Installation

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env`, invite the bot account to target rooms, and assign only the power level it needs.

## Environment Variables

Required: `MATRIX_HOMESERVER`, `MATRIX_USER_ID`, and `MATRIX_ACCESS_TOKEN`. Optional: `DATABASE_PATH`, `ROOM_RULES`, `BLOCKED_PHRASES`, `SPAM_MESSAGES`, and `SPAM_WINDOW_SECONDS`.

## Running

```bash
python -m matrixguard
```

## Security

The access token stays outside source, privileged commands check room power levels, database values are bound, and logs avoid credentials.

## Limitations

Spam state is process-local, homeserver moderation capabilities vary, and encrypted rooms require a correctly configured crypto-capable installation.

## Disclaimer

School Purpose Only. Test power levels and redaction behavior in a non-production room first.

## License

MIT; see the collection's root `LICENSE` file.
