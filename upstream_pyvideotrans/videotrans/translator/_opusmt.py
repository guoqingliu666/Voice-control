"""Offline English/Chinese translation with permissively licensed OPUS-MT models."""

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import List, Union

from videotrans.configure.config import ROOT_DIR
from videotrans.configure.excepts import TranslateSrtError
from videotrans.translator._base import BaseTrans


@dataclass
class OpusMTTrans(BaseTrans):
    model_id: str = field(default="", init=False)
    device: str = field(default="cpu", init=False)

    def __post_init__(self):
        super().__post_init__()
        source = (self.source_code or "").lower().split("-")[0]
        target = (self.target_code or "").lower().split("-")[0]
        pair = (source, target)
        models = {
            ("en", "zh"): "Helsinki-NLP/opus-mt-en-zh",
            ("zh", "en"): "Helsinki-NLP/opus-mt-zh-en",
        }
        if pair not in models:
            raise TranslateSrtError(
                f"OPUS-MT 本地渠道只支持 English <-> Chinese，当前为 {source} -> {target}"
            )
        self.model_id = models[pair]
        self.source_lang = source
        self.target_lang = target
        self.trans_thread = min(self.trans_thread, 12)

    def _download(self):
        import ctranslate2
        from ctranslate2.converters import TransformersConverter
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer

        # Resolve directory junctions before passing file names to SentencePiece.
        # Its Windows native library may fail on an otherwise valid path containing CJK characters.
        cache_dir = (Path(ROOT_DIR) / "models" / "opus_mt").resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        ct2_dir = (Path(ROOT_DIR) / "models" / "opus_mt_ct2" / f"{self.source_lang}-{self.target_lang}").resolve()
        last_error = None
        for attempt in range(4):
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, cache_dir=str(cache_dir))
                snapshot_dir = snapshot_download(
                    repo_id=self.model_id,
                    cache_dir=str(cache_dir),
                    allow_patterns=[
                        "config.json",
                        "generation_config.json",
                        "pytorch_model.bin",
                        "model.safetensors",
                        "source.spm",
                        "target.spm",
                        "vocab.json",
                        "tokenizer_config.json",
                        "special_tokens_map.json",
                    ],
                )
                break
            except (OSError, ConnectionError) as exc:
                last_error = exc
                if attempt == 3:
                    raise
                self.signal(text=f"OPUS-MT 模型下载中断，正在断点重试 {attempt + 2}/4")
                time.sleep(2 ** attempt)
        if not hasattr(self, "tokenizer"):
            raise last_error or OSError(f"无法加载 {self.model_id}")
        if not (ct2_dir / "model.bin").is_file():
            ct2_dir.mkdir(parents=True, exist_ok=True)
            self.signal(text="首次使用：正在将 OPUS-MT 转换为高速 int8 模型")
            TransformersConverter(snapshot_dir).convert(
                str(ct2_dir), quantization="int8_float32", force=True
            )
        self.model = ctranslate2.Translator(str(ct2_dir), device="cpu", compute_type="int8")
        self.local_dir = str(ct2_dir)
        return True

    def _item_task(self, data: Union[List[str], str]) -> str:
        texts = data if isinstance(data, list) else [data]
        if self.target_lang == "zh":
            texts = [f">>cmn_Hans<< {text}" for text in texts]
        source_tokens = [
            self.tokenizer.convert_ids_to_tokens(
                self.tokenizer.encode(text, add_special_tokens=True, truncation=True, max_length=512)
            )
            for text in texts
        ]
        results = self.model.translate_batch(
            source_tokens,
            beam_size=4,
            max_decoding_length=160,
            repetition_penalty=1.1,
        )
        translated = [
            self.tokenizer.decode(
                self.tokenizer.convert_tokens_to_ids(result.hypotheses[0]),
                skip_special_tokens=True,
            )
            for result in results
        ]
        return "\n".join(text.strip() for text in translated)

    def _unload(self):
        if hasattr(self, "model"):
            self.model.unload_model()
            del self.model
        if hasattr(self, "tokenizer"):
            del self.tokenizer
