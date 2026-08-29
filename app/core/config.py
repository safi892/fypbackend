import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Populate ``os.environ`` from a ``.env`` file if one exists.

    Problem solved: the project is configured entirely through environment
    variables, but ``uv run`` here does not auto-load ``.env``. Why process env
    wins: explicit variables passed on the command line must override the file.
    Why tiny + dependency-free: a full dotenv lib is overkill for ``KEY=VALUE`` lines.

    :param path: location of the ``.env`` file to read.
    """
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()


def _resolve_model_dir(checkpoint_name: str) -> str:
    """Find a checkpoint directory by name across the known model locations.

    Problem solved: the fine-tuned checkpoints live in two places -- the older
    ``codet5_commenst_expla`` bundle and the Kaggle-trained ``trained_model/...``
    archive (which carries the full, correct tokenizer). Why search both: the
    backend should locate a named checkpoint wherever it actually sits instead of
    assuming one fixed parent. Why the trained_model archive is checked first:
    its tokenizer is the one the model was trained with, so it must win over the
    older bundle that ships a truncated tokenizer.

    :param checkpoint_name: the checkpoint folder name (e.g. ``checkpoint-9604``).
    :return: the absolute path to the checkpoint directory.
    """
    candidates = [
        BASE_DIR
        / "trained_model"
        / "fyp_models"
        / "archive"
        / "model_checkpoints"
        / checkpoint_name,
        BASE_DIR / "codet5_commenst_expla" / checkpoint_name,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)
    # Fall back to the first candidate so the later existence check gives a clear
    # "model path not found" error pointing at the expected location.
    return str(candidates[0])


# Select a bundled checkpoint by name (e.g. "checkpoint-9604", "checkpoint_best").
# MODEL_PATH still allows an explicit absolute/relative override.
MODEL_CHECKPOINT = os.getenv("MODEL_CHECKPOINT", "checkpoint_best")
MODEL_PATH = os.getenv("MODEL_PATH", _resolve_model_dir(MODEL_CHECKPOINT))
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", MODEL_PATH)
# If a checkpoint ships a broken tokenizer (some fine-tune exports do), fall back
# to the Kaggle-trained archive tokenizer, which is the full one the model was
# trained with. Avoid the older bundle's truncated tokenizer.
FALLBACK_TOKENIZER_PATH = _resolve_model_dir("checkpoint-9604")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "app.db"))

# Generation caps. We use ``max_new_tokens`` (output-only) rather than
# ``max_length`` (input+output) so the cap is independent of prompt size and can
# be tightened for speed without risking a zero-token budget on long inputs.
RAW_MAX_NEW_TOKENS = int(os.getenv("RAW_MAX_NEW_TOKENS", "384"))
RAW_NUM_BEAMS = int(os.getenv("RAW_NUM_BEAMS", "4"))
# Prompt prefix the checkpoint was fine-tuned with ("comment and explain: " +
# code). Feeding the raw code *without* this prefix makes the model emit only a
# commented function and a VERIFICATION trailer -- it never reaches the
# ### EXPLANATION section, so the explanation service falls back to rules. The
# prefix is what elicits the full three-section (code + verification + explanation)
# output the model was trained on.
PROMPT_PREFIX = os.getenv("PROMPT_PREFIX", "comment and explain: ")
# Beam search (num_beams>1) plus a gentle repetition penalty is what the training
# run used; greedy decoding (num_beams=1) produced hallucinated identifiers and
# dropped the explanation. ``repetition_penalty`` is kept near 1.0 (1.05) on
# purpose: a high value (1.2) penalises the ``//`` comment characters and degrades
# output. ``do_sample`` is OFF so the API is deterministic; the Kaggle notebook
# used sampling but beam-only yields the same quality here.
RAW_REPETITION_PENALTY = float(os.getenv("RAW_REPETITION_PENALTY", "1.05"))
RAW_DO_SAMPLE = os.getenv("RAW_DO_SAMPLE", "0") == "1"
RAW_TEMPERATURE = float(os.getenv("RAW_TEMPERATURE", "0.4"))
RAW_TOP_P = float(os.getenv("RAW_TOP_P", "0.95"))
PROMPT_MAX_NEW_TOKENS = int(os.getenv("PROMPT_MAX_NEW_TOKENS", "384"))
PROMPT_NUM_BEAMS = int(os.getenv("PROMPT_NUM_BEAMS", "4"))
# Opt-in graph compilation. Off by default: on CPU/MPS the compile overhead
# usually outweighs the gain for a 220M model, but it can help on CUDA.
TORCH_COMPILE = os.getenv("TORCH_COMPILE", "0") == "1"
# MPS (Apple GPU) is opt-in: on torch 2.0.1 its beam-decode path is far slower
# than CPU for this seq2seq model, so we default to CPU and keep CUDA auto-on.
USE_MPS = os.getenv("USE_MPS", "0") == "1"
# CPU inference tuning. Accuracy is the priority, so the model always loads in
# FP32 (full precision) -- no quantization is applied, which keeps the generated
# code and comments faithful to the checkpoint's training.
# Threads for torch intra-op parallelism. 0 = auto (all physical cores, capped
# at 8 to avoid contention). Override with TORCH_THREADS if needed.
TORCH_THREADS = int(os.getenv("TORCH_THREADS", "0"))
# When set, ``run_model`` records the raw decoded ``model.generate`` text so the
# inspector can show it next to the parsed/selected output.
DEBUG_MODEL = os.getenv("DEBUG_MODEL", "0") == "1"

# --- Model backend -------------------------------------------------------- #
# Which engine answers ``run_model``.
#
#   "codet5"    the original fine-tuned seq2seq checkpoint, loaded in-process
#   "qwen_gguf" the Qwen2.5-Coder LoRA, merged and quantised, served by
#               llama-server over HTTP
#
# Kept as a switch rather than a replacement so the two can be compared on the
# same requests and so a bad deploy is one environment variable away from being
# undone. The mobile contract is identical either way: the adapter renders the
# new model's line-anchored output into the ``commented_code`` string the app
# already expects.
MODEL_BACKEND = os.getenv("MODEL_BACKEND", "codet5")

# Where llama-server is listening. The server is started outside the app: it
# loads a multi-gigabyte model once and outlives any single worker, which is
# the opposite of how the in-process CodeT5 path behaves.
#
# Port 8081, not llama.cpp's default 8080: this API already listens on 8080,
# and the two silently fighting over the socket is a confusing way to find out.
LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8081")

# The GGUF weights, inside the project so a checkout is all a teammate needs.
# Resolved from BASE_DIR rather than the working directory, so the path holds
# wherever the server is launched from.
LLAMA_MODEL_PATH = os.getenv(
    "LLAMA_MODEL_PATH",
    str(BASE_DIR / "models" / "gguf" / "qwen-cpp-review-q4_k_m.gguf"),
)
# Threads for llama-server. 0 lets it choose.
LLAMA_THREADS = int(os.getenv("LLAMA_THREADS", "8"))
LLAMA_CONTEXT = int(os.getenv("LLAMA_CONTEXT", "4096"))
LLAMA_TIMEOUT = float(os.getenv("LLAMA_TIMEOUT", "180"))
LLAMA_MAX_NEW_TOKENS = int(os.getenv("LLAMA_MAX_NEW_TOKENS", "900"))
# Chunk budget for whole-file annotation. Matches the training distribution:
# the model saw functions of roughly fifteen lines and answers those best.
LLAMA_CHUNK_TOKENS = int(os.getenv("LLAMA_CHUNK_TOKENS", "300"))

ROMAN_URDU_MODEL_PATH = os.getenv(
    "ROMAN_URDU_MODEL_PATH",
    str(BASE_DIR / "models" / "roman-model" / "t5-stage2-c"),
)
ROMAN_URDU_NUM_BEAMS = int(os.getenv("ROMAN_URDU_NUM_BEAMS", "4"))
ROMAN_URDU_MAX_NEW_TOKENS = int(os.getenv("ROMAN_URDU_MAX_NEW_TOKENS", "160"))

PASSWORD_HASH_ITERATIONS = int(os.getenv("PASSWORD_HASH_ITERATIONS", "200000"))
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "720"))
