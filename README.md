## Code Analyzer Backend

This service exposes a FastAPI endpoint that analyzes source code using a local model and a small SQLite auth layer.

Start here:

- [Setup](docs/SETUP.md)
- [API Reference](docs/API.md)
- [Auth and Database](docs/AUTH.md)
- [Android Integration](docs/ANDROID.md)

Project structure:

- `app/` contains the FastAPI package
- `app/main.py` is the FastAPI entrypoint
- `run_model_server.sh` starts llama.cpp with the model
- `runserver.sh` starts the API
- `uv sync` installs dependencies





