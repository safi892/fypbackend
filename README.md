## Code Analyzer Backend

This service exposes a FastAPI endpoint that analyzes source code using a local model and a small SQLite auth layer.

`POST /analyze` supports `output_language: "english" | "roman_urdu"`.
English is the default. Roman Urdu requests translate generated prose
(`explanation` and inline comments) while keeping the submitted C++ unchanged.
The public response is intentionally small: `input_code`, `commented_code`,
`explanation`, and `needs_review`. The explanation omits time and space
complexity details.

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


