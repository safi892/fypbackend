## Code Analyzer Backend

This service exposes a FastAPI endpoint that analyzes source code using a local model.

### Prerequisites

- Python 3.11+
- macOS or Linux shell. Windows users should use Git Bash or WSL.

### Setup

On macOS/Linux (or Git Bash/WSL on Windows):

```bash
chmod +x setup.sh runserver.sh
./setup.sh
```

### Run the server

```bash
./runserver.sh start
```

### Common commands

```bash
./runserver.sh status
./runserver.sh logs
./runserver.sh stop
./runserver.sh restart
```

### Configuration

Environment variables supported by the scripts:

- `PORT` (default: `8000`)
- `MODEL_PATH` and `TOKENIZER_PATH` are set automatically by `runserver.sh`

### API

- Health: `GET /health`
- Analyze: `POST /analyze`
