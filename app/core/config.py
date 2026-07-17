import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

MODEL_PATH = os.getenv("MODEL_PATH", str(BASE_DIR / "codet5_commenst_expla" / "checkpoint_best"))
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", MODEL_PATH)
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "app.db"))

RAW_MAX_LENGTH = int(os.getenv("RAW_MAX_LENGTH", "768"))
RAW_NUM_BEAMS = int(os.getenv("RAW_NUM_BEAMS", "4"))
PROMPT_MAX_LENGTH = int(os.getenv("PROMPT_MAX_LENGTH", "900"))
PROMPT_NUM_BEAMS = int(os.getenv("PROMPT_NUM_BEAMS", "5"))

PASSWORD_HASH_ITERATIONS = int(os.getenv("PASSWORD_HASH_ITERATIONS", "200000"))
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "720"))
