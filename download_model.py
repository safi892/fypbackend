from huggingface_hub import snapshot_download





snapshot_download(
    repo_id="saffi892/fybmodel",
    repo_type="dataset",
    allow_patterns="checkpoint_best/*",
    local_dir="./codet5_commenst_expla"
)