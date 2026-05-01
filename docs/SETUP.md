# Setup

## Prerequisites

- Python 3.11+
- macOS or Linux shell. Windows users should use Git Bash or WSL.

## Install

```bash
chmod +x setup.sh runserver.sh
./setup.sh
```

Windows:

```bat
setup.bat
```

## Run

```bash
./runserver.sh start
```

Windows:

```bat
runserver.bat start
```

## Common commands

```bash
./runserver.sh status
./runserver.sh logs
./runserver.sh stop
./runserver.sh restart
```

Windows batch files provide the same setup/start entrypoints.

## Configuration

Environment variables:

- `PORT` defaults to `8000`
- `MODEL_PATH` and `TOKENIZER_PATH` are set by `runserver.sh` or `runserver.bat`
- `DB_PATH` defaults to `app.db` in the project root

## Structure

```text
back/
├── app/
├── docs/
├── runserver.bat
├── runserver.sh
├── setup.bat
└── setup.sh
```
