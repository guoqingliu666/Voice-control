import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import json
from videotrans import translator
from videotrans.configure._i18n import tr
from videotrans.configure.config import ROOT_DIR,params,defaulelang,TEMP_DIR
from videotrans.tts._base import BaseTTS
from videotrans.util.help_misc import vail_file, is_connect_hf


@dataclass
class QwenttsLocal(BaseTTS):
    target_language: str = None
    
    def __post_init__(self):
        super().__post_init__()
        self.model_name="1.7B"
        _langnames = translator.LANG_CODE.get(self.language, [])
        self.target_language = _langnames[9].capitalize() if _langnames and len(_langnames) >= 10 else 'Auto'

    
    def _download(self):
        from videotrans.util import help_down
        custom_voices = {"Vivian", "Serena", "Uncle_fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_anna", "Sohee"}
        roles = {item.get('role') for item in self.queue_tts if item.get('role')}
        variants = []
        if not roles or roles - custom_voices:
            variants.append('Base')
        if roles & custom_voices:
            variants.append('CustomVoice')

        for variant in variants:
            repo_id = f'Qwen/Qwen3-TTS-12Hz-{self.model_name}-{variant}'
            model_id = f'Qwen3-TTS-12Hz-{self.model_name}-{variant}'
            self.local_dir = f'{ROOT_DIR}/models/models--Qwen--{model_id}'
            model_file = Path(self.local_dir) / 'model.safetensors'
            speech_tokenizer_file = Path(self.local_dir) / 'speech_tokenizer' / 'model.safetensors'
            required_files = tuple(
                Path(self.local_dir) / relative_path
                for relative_path in (
                    'config.json',
                    'generation_config.json',
                    'merges.txt',
                    'model.safetensors',
                    'preprocessor_config.json',
                    'speech_tokenizer/config.json',
                    'speech_tokenizer/configuration.json',
                    'speech_tokenizer/model.safetensors',
                    'speech_tokenizer/preprocessor_config.json',
                    'tokenizer_config.json',
                    'vocab.json',
                )
            )
            if all(item.is_file() and item.stat().st_size > 0 for item in required_files):
                continue

            if not is_connect_hf():
                help_down.check_and_down_ms(repo_id, callback=self._process_callback, local_dir=self.local_dir)
            else:
                help_down.check_and_down_hf(
                    model_id=model_id,
                    repo_id=repo_id,
                    local_dir=self.local_dir,
                    callback=self._process_callback,
                )

            # As with Whisper, a partial directory can be mistaken for a complete
            # snapshot. Resume from Hugging Face and verify the main weight file.
            if not all(item.is_file() and item.stat().st_size > 0 for item in required_files):
                os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
                from huggingface_hub import snapshot_download

                last_error = None
                for attempt in range(4):
                    try:
                        self._process_callback(
                            f'Qwen3-TTS model incomplete; resume download {attempt + 1}/4'
                        )
                        missing_patterns = [
                            item.relative_to(self.local_dir).as_posix()
                            for item in required_files
                            if not item.is_file() or item.stat().st_size == 0
                        ]
                        snapshot_download(
                            repo_id=repo_id,
                            local_dir=self.local_dir,
                            local_files_only=False,
                            endpoint=os.environ.get('HF_ENDPOINT'),
                            max_workers=1,
                            allow_patterns=missing_patterns,
                            ignore_patterns=['*.md', '.git*'],
                        )
                        if all(item.is_file() and item.stat().st_size > 0 for item in required_files):
                            break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 3:
                            time.sleep(2 ** attempt)
                missing = [str(item) for item in required_files if not item.is_file() or item.stat().st_size == 0]
                if missing:
                    from videotrans.configure.excepts import DownloadModelsError
                    raise DownloadModelsError(
                        f'Qwen3-TTS model download is incomplete: {", ".join(missing)}\n{last_error or "required weight missing"}'
                    )
        return True


    def _exec(self):

        logs_file = f'{TEMP_DIR}/{self.uuid}/qwen3tts-{time.time()}.log'
        queue_tts_file = f'{TEMP_DIR}/{self.uuid}/queuetts-{time.time()}.json'
        Path(queue_tts_file).write_text(json.dumps(self.queue_tts),encoding='utf-8')
        title="Qwen3-TTS dubbing..."
        kwargs = {
            "queue_tts_file":queue_tts_file,
            "language": self.target_language,
            "logs_file": logs_file,
            "is_cuda": self.is_cuda,
            "model_name":self.model_name,
            "prompt":params.get('qwenttslocal_prompt', ''),
            "is_redubb":self.is_redubb
        }
        from videotrans.process.qwen_tts import qwen3tts_fun
        self._new_process(callback=qwen3tts_fun,title=title,is_cuda=self.is_cuda,kwargs=kwargs)

        if self.is_redubb:return
        self.signal(text=tr('Standardized dubbing segment processing'))
        all_task = []

        with ThreadPoolExecutor(max_workers=min(4,len(self.queue_tts),os.cpu_count())) as pool:
            for item in self.queue_tts:
                if vail_file(item['filename']):continue
                filename=item.get('filename','')+"-24k.wav"
                if  vail_file(filename):
                    all_task.append(pool.submit(self.convert_to_wav, filename,item['filename']))
            if len(all_task) > 0:
                _ = [i.result() for i in all_task]



