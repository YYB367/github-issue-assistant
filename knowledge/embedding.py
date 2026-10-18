import hashlib
import json
import os
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

from app.config import EMBEDDING_TOKEN_LIMIT, Settings
from app.errors import AppError

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL_REPOSITORY = "Qdrant/bge-small-zh-v1.5"
MODEL_REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
MODEL_FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "model_optimized.onnx"]
QUERY_PREFIX = ""


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for data in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def prepare_model(settings: Settings) -> dict:
    # Explicit admin command. Request handlers never download model weights.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import hf_hub_download
    folder = settings.embedding_model_path
    folder.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        hf_hub_download(MODEL_REPOSITORY, filename=name, revision=MODEL_REVISION,
                        local_dir=str(folder), token=False)
    report = {"model": MODEL_NAME, "repository": MODEL_REPOSITORY, "revision": MODEL_REVISION,
              "dimension": 512, "files": {name: file_hash(folder / name) for name in MODEL_FILES}}
    (folder / "model-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Prepare tiktoken's public vocabulary cache in the project runtime directory.
    os.environ["TIKTOKEN_CACHE_DIR"] = str(settings.knowledge_path.parent / "token-cache")
    import tiktoken
    tiktoken.get_encoding("cl100k_base")
    return report


class LocalEmbedding:
    def __init__(self, settings: Settings):
        folder = settings.embedding_model_path
        manifest_path = folder / "model-manifest.json"
        if not manifest_path.is_file():
            raise AppError("embedding_not_ready", "先运行 python -m scripts.kb prepare-model 下载固定版本Embedding模型。")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != MODEL_REVISION or manifest.get("model") != MODEL_NAME:
            raise AppError("embedding_version_mismatch", "Embedding模型清单版本不一致。")
        for name in MODEL_FILES:
            if not (folder / name).is_file() or file_hash(folder / name) != manifest["files"].get(name):
                raise AppError("embedding_integrity", "Embedding文件缺失或哈希不一致，请重新准备模型。")
        self.identity = f"{MODEL_NAME}@{MODEL_REVISION}:{manifest['files']['model_optimized.onnx']}"
        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        from fastembed import TextEmbedding
        self.model = TextEmbedding(MODEL_NAME, specific_model_path=str(folder),
                                   local_files_only=True, providers=["CPUExecutionProvider"], threads=2)
        os.environ["TIKTOKEN_CACHE_DIR"] = str(settings.knowledge_path.parent / "token-cache")
        import tiktoken
        self.generation_tokenizer = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self.tokenizer.encode(text).ids)

    def estimate_generation_tokens(self, text: str) -> int:
        # This is explicitly an estimate, NOT DeepSeek's exact tokenizer.
        return len(self.generation_tokenizer.encode(text, disallowed_special=()))

    def encode(self, texts: list[str]) -> list[list[float]]:
        if any(self.count(text) > EMBEDDING_TOKEN_LIMIT for text in texts):
            raise AppError("embedding_token_limit", "输入超出已验证的Embedding token预算。")
        vectors = []
        for vector in self.model.embed(texts, batch_size=8):
            data = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(data))
            if data.shape != (512,) or not np.isfinite(data).all() or norm <= 0:
                raise AppError("embedding_invalid_vector", "Embedding返回向量维度或数值不合法。")
            vectors.append((data / norm).tolist())
        return vectors

    def query(self, text: str) -> tuple[str, list[float], bool]:
        text = text.strip()
        if not text:
            raise AppError("empty_retrieval_query", "检索问题不能为空。")
        truncated = self.count(QUERY_PREFIX + text) > EMBEDDING_TOKEN_LIMIT
        if truncated:
            low, high = 0, len(text)
            while low < high:
                mid = (low + high + 1) // 2
                if self.count(QUERY_PREFIX + text[:mid]) <= EMBEDDING_TOKEN_LIMIT:
                    low = mid
                else:
                    high = mid - 1
            text = text[:low]
        return text, self.encode([QUERY_PREFIX + text])[0], truncated
