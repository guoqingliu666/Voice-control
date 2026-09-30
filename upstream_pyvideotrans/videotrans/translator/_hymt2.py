import logging
import re
from dataclasses import dataclass
from typing import List, Union

from videotrans.configure.config import tr, logger, settings, ROOT_DIR, app_cfg
from videotrans.translator._base import BaseTrans
import torch


@dataclass
class HYMT2(BaseTrans):

    def __post_init__(self):
        super().__post_init__()
        self.model_name = 'Hy-MT2-1.8B-subtitle-v2'
        self.local_dir=f'{ROOT_DIR}/models/models--tencent--Hy-MT2-1.8B'
        
    def _download(self):
        from videotrans.util.help_down import check_and_down_hf,check_and_down_ms
        from videotrans.util.help_misc import is_connect_hf
        if is_connect_hf():
            check_and_down_hf(
                "Hy-MT2-1.8B",
                'tencent/Hy-MT2-1.8B',
                self.local_dir,
                callback=self._process_callback)        
        else:
            check_and_down_ms(
                'Tencent-Hunyuan/Hy-MT2-1.8B',
                local_dir=self.local_dir,
                callback=self._process_callback)        
                
        return True

    def _item_task(self,data: Union[List[str], str]) -> str:
        if self._exit(): return
        delimiter = "<|SUB_LINE|>"
        if isinstance(data, list):
            text = f" {delimiter} ".join(i.strip() for i in data)
            prompt = f"""Please accurately translate the following spoken video subtitles into {self.target_language_name} in a natural conversational style. Preserve the speaker's intended meaning instead of translating fragments word-for-word. Infer unfamiliar expressions from the surrounding context; never transliterate a word as a personal name unless it is clearly a name. You must retain the exact same number of {delimiter} delimiters in the translation. Strictly do not omit, escape, or translate this delimiter. Output only the translated result without explanation.\n\n{text}"""
        else:
            text = data
            prompt = f"""Translate the following spoken video subtitles into natural {self.target_language_name}. Output only the translated result without explanation, and preserve the subtitle structure exactly.\n\n{text}"""


        messages = [{"role": "user", "content": prompt}]
        inputs = app_cfg.hymt2_tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(app_cfg.hymt2_model.device)

        with torch.no_grad():
            outputs = app_cfg.hymt2_model.generate(
                **inputs,
                max_new_tokens=4096,
                temperature=0.7,
                top_p=0.6,
                top_k=20,
                repetition_penalty=1.05,
            )
        response = app_cfg.hymt2_tokenizer.decode(outputs[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
        if isinstance(data, list):
            response = re.sub(r'\s*<\|SUB_LINE\|>\s*', '\n', response)
        return response.strip()
