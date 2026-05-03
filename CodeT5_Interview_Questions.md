# CodeT5 Model Training & Testing - Interview Q&A 📚

---

## Round 1: Model & Task Overview

### Q1: What model is being used in these notebooks?

**Answer:** `Salesforce/codet5p-220m` (CodeT5+ with 220 million parameters). It's a pre-trained code understanding model from Hugging Face.

---

### Q2: What is the task being performed?

**Answer:** **Code Comment Generation** - Given C++ code WITHOUT comments as input, the model generates C++ code WITH comments added, plus explanations.

---

### Q3: What is the difference between the two notebooks?

**Answer:**
- **codet5-commenst-explanation-2.ipynb**: Training notebook - fine-tunes the model on labeled data
- **test-commenstexpla-2.ipynb**: Testing notebook - loads the trained model and runs inference on new code

---

## Round 2: Data Preparation

### Q4: What is the data format expected?

**Answer:** JSON format with:
- `input`: Code WITHOUT comments
- `output`: Code WITH comments + explanation
- `explanation`: (optional) Additional explanation text

---

### Q5: How is the dataset split?

**Answer:**
- 80% training
- 10% validation
- 10% testing

---

### Q6: What does the `clean_code()` function do?

**Answer:** It cleans the input text by:
- Removing markdown code fences (` ```cpp `)
- Stripping leading/trailing whitespace
- Removing inline code markers
- Collapsing excessive blank lines

---

### Q7: What does `validate_records()` check?

**Answer:** It validates each record:
- Must have `input` and `output` keys
- Both must be non-empty strings
- Returns count of valid vs skipped records with reasons

---

## Round 3: Tokenization

### Q8: What is tokenization?

**Answer:** Converting text (code) into numerical tokens (numbers) that the model can understand. Each unique word/symbol gets a unique number.

---

### Q9: Why are there two different MAX_LENGTH values?

**Answer:**
- `MAX_SOURCE_LEN = 512`: For input code (without comments)
- `MAX_TARGET_LEN = 512`: For output (code with comments + explanation)

Longer code needs larger values.

---

### Q10: What does `labels = -100` mean in tokenization?

**Answer:** Padding tokens in labels are replaced with -100 so they are ignored during loss calculation. The model only learns from actual tokens, not padding.

---

### Q11: What is `DataCollatorForSeq2Seq`?

**Answer:** It dynamically pads each batch to the longest sequence in that batch (better GPU usage) and handles the seq2seq format for training.

---

## Round 4: Model Architecture

### Q12: What is `AutoModelForSeq2SeqLM`?

**Answer:** It's a sequence-to-sequence language model - takes one text (code) as input and generates another text (commented code) as output. Perfect for translation-like tasks.

---

### Q13: What is gradient checkpointing?

**Answer:** A technique to save 30-40% VRAM by not storing all intermediate activations during forward pass, recalculating them during backward pass. Slight speed cost but allows bigger models.

---

### Q14: What is DataParallel?

**Answer:** Wraps model across multiple GPUs automatically. If you have 2+ GPUs, it splits the data and runs in parallel for faster training.

---

### Q15: How many parameters does the model have?

**Answer:** ~220 million parameters (for codet5p-220m). Only parameters with `requires_grad=True` are trained (fine-tuned).

---

## Round 5: Training Configuration

### Q16: What is AdamW optimizer?

**Answer:** An optimizer that combines Adam (adaptive learning rates) with weight decay (L2 regularization). Better than standard SGD for deep learning.

---

### Q17: Why use weight decay only on certain parameters?

**Answer:** Biases and LayerNorm weights don't benefit from weight decay. The code applies weight decay to all parameters EXCEPT `bias` and `LayerNorm.weight`.

---

### Q18: What is learning rate scheduler?

**Answer:** `get_linear_schedule_with_warmup` gradually increases learning rate for 10% of training (warmup), then decreases linearly. Helps stable training.

---

### Q19: What is mixed precision (FP16) training?

**Answer:** Uses 16-bit floating point instead of 32-bit for faster computation and less memory. Enabled automatically if CUDA is available.

---

### Q20: What is GradScaler?

**Answer:** Handles mixed precision training - scales loss to prevent underflow with FP16, skips updates if NaN/Inf gradients detected.

---

## Round 6: Training Process

### Q21: What is gradient accumulation?

**Answer:** Instead of updating after each batch, accumulate gradients over several batches (GRAD_ACCUM), then update once. Simulates larger batch size with less memory.

---

### Q22: What is gradient clipping?

**Answer:** `nn.utils.clip_grad_norm_` prevents gradients from becoming too large (exploding gradients), which can destabilize training. Max norm set to 1.0.

---

### Q23: What happens on OutOfMemory (OOM) error?

**Answer:** The training loop catches OOM errors, clears GPU cache, and skips that batch to continue training without crashing.

---

### Q24: How does the model learn?

**Answer:** 
1. Forward pass: Input code → model → predicts output
2. Compare prediction with actual output (calculate loss)
3. Backward pass: Adjust weights to reduce loss
4. Repeat for many epochs

---

## Round 7: Validation & Evaluation

### Q25: What is BLEU score?

**Answer:** Bilingual Evaluation Understudy - measures how similar generated text is to reference text. Score 0-100, higher is better. Used for translation/comment generation quality.

---

### Q26: What is the validation loop doing?

**Answer:** 
1. Sets model to eval mode
2. Runs forward pass to get loss
3. Generates predictions using beam search
4. Compares with references using BLEU metric

---

### Q27: What is beam search?

**Answer:** Instead of choosing just one word at each step, keeps top `NUM_BEAMS` (4) possibilities. Produces better quality output than greedy decoding.

---

### Q28: When is the best checkpoint saved?

**Answer:** Every time validation BLEU score improves over the previous best. Keeps the highest-performing model.

---

## Round 8: Checkpointing

### Q29: What is a checkpoint?

**Answer:** A saved snapshot containing:
- Model weights
- Optimizer state
- Scheduler state
- Current epoch number
- Best BLEU score
- Training history

Allows resuming training from where it stopped.

---

### Q30: What does `training_state.pt` contain?

**Answer:** All training state needed to resume:
- Epoch number
- Optimizer state
- Scheduler state
- Scaler state
- Best BLEU
- History (loss curves)

---

## Round 9: Inference / Testing

### Q31: How does inference work?

**Answer:**
1. Load best trained checkpoint
2. Tokenize input code
3. Call model.generate() with beam search
4. Decode tokens back to text
5. Return commented code

---

### Q32: What is the prompt engineering in test notebook?

**Answer:** The `build_prompt()` function creates a detailed prompt telling the model to:
- Analyze logic, not just function names
- Explain conditions step-by-step
- Report bugs if function name contradicts logic
- Add inline comments

---

### Q33: What does `clean_duplicate_code()` do?

**Answer:** Removes duplicate function blocks if the model repeats itself in output. Keeps only the last occurrence.

---

### Q34: What is max_target_len in inference?

**Answer:** Set to 768 (larger than training's 512) to allow longer outputs with comments and explanations during inference.

---

## Round 10: Output Format

### Q35: What does the final output contain?

**Answer:**
```
### COMMENTED CODE
<code with inline comments>

### LOGIC ANALYSIS
<step-by-step explanation>

### ISSUES
<bugs or "None">

### EXPLANATION
<final summary>
```

---

## Round 11: Hardware & Performance

### Q36: How many GPUs are used?

**Answer:** Automatically detected. If CUDA available, uses all GPUs via DataParallel. Single GPU also works.

---

### Q37: What affects training speed?

**Answer:**
- Batch size (larger = faster but needs more memory)
- Gradient accumulation (simulates bigger batches)
- Mixed precision (FP16 = faster)
- Gradient checkpointing (slower but saves memory)

---

### Q38: Why clear GPU cache before validation?

**Answer:** Validation uses beam search which needs lots of memory. Clearing cache ensures maximum available memory for generation.

---

## Round 12: Key Hyperparameters

### Q39: What are the key hyperparameters?

| Parameter | Value | Purpose |
|-----------|-------|---------|
| BATCH_SIZE | 24 | Training batch size |
| EPOCHS | 8 | Number of training passes |
| LEARNING_RATE | 5e-5 | How fast model learns |
| WARMUP_RATIO | 0.1 | 10% steps for warmup |
| MAX_SOURCE_LEN | 512 | Input max tokens |
| MAX_TARGET_LEN | 512 | Output max tokens |
| NUM_BEAMS | 4 | Beam search width |
| WEIGHT_DECAY | 0.01 | Regularization |

---

## Challenge Questions

### Q40: If you run out of GPU memory, what 3 things can you do?

**Answer:**
1. Reduce batch size
2. Enable gradient checkpointing (already on)
3. Reduce MAX_SOURCE_LEN/MAX_TARGET_LEN
4. Use gradient accumulation (smaller batches)
5. Use FP16 (already enabled)

---

### Q41: Why save both checkpoint_last AND checkpoint_best?

**Answer:**
- `checkpoint_last`: Always saved - can resume if training interrupted
- `checkpoint_best`: Only saved when BLEU improves - best model for inference

---

### Q42: Can you use this model for languages other than C++?

**Answer:** Yes, but it was fine-tuned on C++ data. For other languages, you'd need to train on that language's dataset or use the original CodeT5 model.

---

## Score Yourself

| Score | Grade |
|-------|-------|
| 35-42 | 🌟 AI/ML Expert |
| 25-34 | 🎯 Great |
| 15-24 | 👍 Good |
| 5-14 | 📚 Keep Learning |
| 0-4 | 🔄 Review Again |

---

*Good luck! 🚀*