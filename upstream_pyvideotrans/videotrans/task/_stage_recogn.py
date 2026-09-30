import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os

from videotrans.configure.config import tr, ROOT_DIR, settings, logger
from videotrans.configure.contants import DENOISE_URL_MS, PUNC_RESTORE_MS, DENOISE_URL_HF, PUNC_RESTORE_HF
from videotrans.configure.excepts import SpeechToTextError
from videotrans.recognition import run as run_recogn, is_allow_lang as recogn_allow_lang, FASTER_WHISPER
from videotrans.util.help_ffmpeg import conver_to_16k, runffmpeg, cut_from_audio
from videotrans.util.help_misc import vail_file, is_connect_hf
from videotrans.util.help_srt import get_subtitle_from_srt, delete_punc


class RecognMixin:

    def recogn(self) -> None:
        _st=time.time()
        if self._exit(): return
        if not self.should_recogn: return
        self.precent += 3
        self.signal(text=tr("kaishishibie"))
        if vail_file(self.cfg.source_sub):
            self.source_srt_list = get_subtitle_from_srt(self.cfg.source_sub, is_file=True)
            if Path(self.cfg.target_dir + "/speaker.json").exists():
                shutil.copy2(self.cfg.target_dir + "/speaker.json", self.cfg.cache_folder + "/speaker.json")
            self._recogn_succeed()
            return

        if not vail_file(self.cfg.source_wav):
            raise SpeechToTextError(tr("Failed to separate audio, please check the log or retry"))
        # 未分离人声背景时才降噪，已分离则不再降噪
        if self.cfg.remove_noise and not self.cfg.is_separate:
            from videotrans.util.help_down import down_file_from_hf
            _remove_noise_wav = f"{self.cfg.cache_folder}/remove_noise.wav"
            if vail_file(_remove_noise_wav):
                self.cfg.source_wav = _remove_noise_wav
                self.clone_ref = _remove_noise_wav
                logger.debug(f'复用已存在的降噪缓存文件')
            else:
                title = tr("Starting to process speech noise reduction, which may take a long time, please be patient")
                kw = {
                    "input_file": self.cfg.source_wav if not self.cfg.vocal or not Path(self.cfg.vocal).exists() else self.cfg.vocal,
                    "output_file": _remove_noise_wav,
                    "is_cuda": self.cfg.is_cuda
                }
                try:
                    down_file_from_hf(f'{ROOT_DIR}/models/onnx', urls=DENOISE_URL_MS if not is_connect_hf() else DENOISE_URL_HF,
                                            callback=self._process_callback)
                    from videotrans.process.prepare_audio import remove_noise
                    _rs = self._new_process(callback=remove_noise, title=title, is_cuda=self.cfg.is_cuda, kwargs=kw)
                    if _rs:
                        self.clone_ref = _remove_noise_wav
                        self.cfg.source_wav = _remove_noise_wav
                    self.signal(text='remove noise end')
                except Exception as e:
                    logger.exception(f'降噪失败，跳过 {e}', exc_info=True)

        self.signal(text=tr("Speech Recognition to Word Processing"))
        raw_subtitles = run_recogn(
            recogn_type=self.cfg.recogn_type,
            uuid=self.uuid,
            model_name=self.cfg.model_name,
            audio_file=self.cfg.source_wav,
            detect_language=self.cfg.detect_language,
            cache_folder=self.cfg.cache_folder,
            is_cuda=self.cfg.is_cuda,
            subtitle_type=self.cfg.subtitle_type,
            max_speakers=self.max_speakers,
            llm_post=self.cfg.rephrase==1
        )
        if self._exit(): return
        if not raw_subtitles:
            raise SpeechToTextError(self.cfg.basename + tr('recogn result is empty'))

        if self.cfg.app_mode=='tiqu' and not self.should_trans and self.cfg.fix_punc==2:
            logger.debug('仅提取不翻译模式下，移除所有标点')
            for it in raw_subtitles:
                it['text'] = delete_punc(it['text'])

        self._save_srt_target(raw_subtitles, self.cfg.source_sub)
        self.source_srt_list = raw_subtitles
        # 恢复标点
        if self.cfg.fix_punc==1 and self.cfg.detect_language.split('-')[0] in ['zh', 'en']:
            try:
                down_file_from_hf(f'{ROOT_DIR}/models/puntc', PUNC_RESTORE_MS if not is_connect_hf() else PUNC_RESTORE_HF, callback=self._process_callback)
                from videotrans.process.prepare_audio import fix_punc
                text_dict = {f'{it["line"]}': re.sub(r'[,.?!，。？！]', ' ', it["text"]) for it in self.source_srt_list}
                text_dict_file=f'{self.cfg.cache_folder}/text_dict_file_{time.time()}.json'
                Path(text_dict_file).write_text(json.dumps(text_dict),encoding="utf-8")
                kw = {"text_dict_file": text_dict_file, "is_cuda": self.cfg.is_cuda}
                _rs = self._new_process(callback=fix_punc, title=tr("Restoring punct"), is_cuda=self.cfg.is_cuda,
                                        kwargs=kw)
                if _rs:
                    text_dict_obj=json.loads(Path(text_dict_file).read_text(encoding='utf-8'))
                    for it in self.source_srt_list:
                        it['text'] = text_dict_obj.get(f'{it["line"]}', it['text'])
                        if self.cfg.detect_language.split('-')[0] == 'en':
                            it['text'] = it['text'].replace('，', ',').replace('。', '. ').replace('？', '?').replace('！','!')
                    self._save_srt_target(self.source_srt_list, self.cfg.source_sub)
                else:
                    logger.error('标点恢复出错了，跳过')
            except Exception as e:
                logger.exception(f'标点恢复失败，跳过 {e}', exc_info=True)

        self.signal(text=Path(self.cfg.source_sub).read_text(encoding='utf-8'), type='replace_subtitle')
        if Path(self.cfg.cache_folder + "/speaker.json").exists():
            self._recogn_succeed()
            self.signal(text=tr('endtiquzimu'))
            return
        
        # 未选中说话人识别时，才重新断句
        if self.cfg.rephrase==1 and (not self.do_diarize or not self.cfg.enable_diariz):
            try:
                from videotrans.translator._openaicompat import OpenAICampat
                ob = OpenAICampat(
                    ainame='chatgpt' if settings.get('llm_ai_type', 'chatgpt') != 'deepseek' else 'deepseek',
                    uuid=self.uuid)

                self.signal(text=tr("Re-segmenting..."))
                srt_list = ob.llm_segment(self.source_srt_list )
                if srt_list and len(srt_list) > len(self.source_srt_list) / 2:
                    self.source_srt_list = srt_list
                    self._save_srt_target(self.source_srt_list, self.cfg.source_sub)
                else:
                    logger.error(f'重新断句失败，已恢复原样,原始字幕行:{len(self.source_srt_list)}, 重新断句后字幕行:{len(srt_list)}\n断句结果:\n{srt_list=}')
            except Exception as e:
                self.signal(text=tr("Re-segmenting Error"))
                logger.exception(f"重新断句失败，已恢复原样 {e}", exc_info=True)
        
        self._recogn_succeed()
        self.signal(text=tr('endtiquzimu'))
        logger.debug(f'[语音识别阶段结束耗时]:{time.time()-_st}s')

    def _recogn_succeed(self) -> None:
        self.precent += 5
        if self.cfg.app_mode == 'tiqu' and not self.should_trans:
            shutil.copy2(self.cfg.source_sub,  f"{self.cfg.target_dir}/{self.cfg.noextname}.srt")
        self.signal(text=tr('endtiquzimu'))

    def recogn2pass(self) -> None:
        _st=time.time()
        if not self.should_recogn2 or self._exit():
            return
        if not vail_file(self.cfg.target_wav):
            logger.debug(f'跳过二次识别，因无配音音频文件')
            return

        self.precent += 3
        self.signal(text=tr("Secondary speech recognition of dubbing files"))

        shibie_audio = f'{self.cfg.cache_folder}/recogn2pass-{time.time()}.wav'
        outsrt_file = f'{self.cfg.cache_folder}/recogn2pass-{time.time()}.srt'
        try:
            conver_to_16k(self.cfg.target_wav, shibie_audio)
        except Exception as e:
            logger.exception(f'二次识别配音音频生成字幕时，预处理音频失败，静默跳过 {e}', exc_info=True)
            return

        if not vail_file(shibie_audio):
            logger.error(f'二次识别配音音频生成字幕时，预处理音频失败，静默跳过')
            return

        try:
            recogn_type = self.cfg.recogn_type
            model_name = self.cfg.model_name
            detect_language = self.cfg.target_language_code.split('-')[0]

            if recogn_allow_lang(langcode=self.cfg.target_language_code,
                                 recogn_type=recogn_type,
                                 model_name=model_name) is not True:
                recogn_type = FASTER_WHISPER
                model_name = 'large-v3-turbo'

            raw_subtitles = run_recogn(
                recogn_type=recogn_type,
                uuid=self.uuid,
                model_name=model_name,
                audio_file=shibie_audio,
                detect_language=detect_language,
                cache_folder=self.cfg.cache_folder,
                is_cuda=self.cfg.is_cuda,
                recogn2pass=True
            )
            if self._exit(): return
            if not raw_subtitles:
                logger.error('二次识别出错：' + tr('recogn result is empty'))
                return

            if self.cfg.rephrase==1 or Path(f'{ROOT_DIR}/recogn2-llm-resegment.txt').exists():
                try:
                    from videotrans.translator._openaicompat import OpenAICampat
                    ob = OpenAICampat(
                        ainame='chatgpt' if settings.get('llm_ai_type', 'chatgpt') != 'deepseek' else 'deepseek',
                        uuid=self.uuid)

                    self.signal(text=tr("Re-segmenting..."))
                    srt_list = ob.llm_segment(raw_subtitles,step="2")
                    if srt_list and len(srt_list) > len(raw_subtitles) / 2:
                        raw_subtitles = srt_list
                    else:
                        logger.error(f'二次识别后LLM重新断句失败，已恢复原样,原始字幕行:{len(raw_subtitles)}, 重新断句后字幕行:{len(srt_list)}\n断句结果:\n{srt_list=}')
                except Exception as e:
                    self.signal(text=tr("Re-segmenting Error"))
                    logger.exception(f"二次识别后重新断句失败，已恢复原样 {e}", exc_info=True)

            if self.cfg.fix_punc==2:
                logger.debug('二次识别后，移除所有标点')
                for it in raw_subtitles:
                    it['text']=delete_punc(it['text'])
            self._save_srt_target(raw_subtitles, outsrt_file)

            if not vail_file(outsrt_file):
                logger.error(f'二次识别配音文件失败，原因未知')
                return
            shutil.copy2(outsrt_file, self.cfg.target_sub)
            self.signal(text='STT 2 pass end')
            logger.debug('二次识别成功完成')
        except Exception as e:
            logger.exception(f'二次识别配音音频生成字幕时失败，静默跳过 {e}', exc_info=True)
            return
        logger.debug(f'[二次识别阶段结束耗时]:{time.time()-_st}s')

    def _create_ref_from_vocal(self):
        # Prefer the separated/denoised vocal track. The previous code always
        # fell back to the mixed video audio when clone_ref was unset.
        vocal = None
        for candidate in (self.clone_ref, getattr(self.cfg, 'vocal', None), self.cfg.source_wav):
            if candidate and Path(candidate).is_file():
                vocal = candidate
                break
        if not vocal:
            try:
                tmpfile = self.cfg.cache_folder + "/clone_ref_44100.wav"
                runffmpeg([
                    "-y",
                    "-i",
                    self.cfg.name,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                    "-c:a",
                    "pcm_s16le",
                    tmpfile
                ])
                vocal=tmpfile
            except Exception as e:
                logger.exception(f'克隆语音前分离出 44.1k 的原始音频失败',exc_info=True)

        logger.debug(f'语音克隆模式下，所用参考音频为:{vocal}')
        if not vocal or not Path(vocal).is_file():
            return

        from pydub import AudioSegment

        audio = AudioSegment.from_file(vocal).set_channels(1)
        candidates_by_speaker = getattr(self, '_voice_ref_candidates', {})
        queue_by_speaker = {}
        for item in self.queue_tts:
            if item.get('ref_wav'):
                queue_by_speaker.setdefault(str(item.get('speaker_id') or 'spk0'), []).append(item)

        def _dbfs(segment):
            value = segment.dBFS
            return -100.0 if value == float('-inf') else float(value)

        for speaker_id, queue_items in queue_by_speaker.items():
            candidates = sorted(candidates_by_speaker.get(speaker_id, []), key=lambda value: value['index'])
            candidates = [
                value for value in candidates
                if value['end_time'] - value['start_time'] >= 350 and value.get('text', '').strip()
            ]
            if not candidates:
                continue

            # First look for a real continuous 8-15 second excerpt. Score it by
            # speech coverage and vocal loudness, both measured over the whole film.
            windows = []
            for start_index, first in enumerate(candidates):
                covered = 0
                previous_index = first['index'] - 1
                previous_end = first['start_time']
                window_text = []
                for candidate in candidates[start_index:]:
                    if candidate['index'] != previous_index + 1 or candidate['start_time'] - previous_end > 1200:
                        break
                    span = candidate['end_time'] - first['start_time']
                    if span > 15000:
                        break
                    covered += candidate['end_time'] - candidate['start_time']
                    window_text.append(candidate['text'])
                    previous_index = candidate['index']
                    previous_end = candidate['end_time']
                    if span >= 8000:
                        clip = audio[first['start_time']:candidate['end_time']]
                        score = (covered / max(span, 1)) * 20 + _dbfs(clip) - abs(span - 11000) / 5000
                        windows.append((score, first['start_time'], candidate['end_time'], list(window_text)))

            if windows:
                _, start_ms, end_ms, text_parts = max(windows, key=lambda value: value[0])
                reference_audio = audio[start_ms:end_ms]
                reference_text = self._join_paragraph_text(text_parts, self.cfg.detect_language, reference=True)
                selection = f'连续片段 {start_ms / 1000:.2f}-{end_ms / 1000:.2f}s'
            else:
                # Fast dialogue or multi-person cuts may contain no continuous
                # 8-second same-speaker window. Build one stable per-speaker
                # reference from the clearest original utterances instead.
                ranked = []
                for candidate in candidates:
                    segment = audio[candidate['start_time']:candidate['end_time']]
                    ranked.append((_dbfs(segment), candidate, segment))
                selected = []
                total_ms = 0
                for _, candidate, segment in sorted(ranked, key=lambda value: value[0], reverse=True):
                    separator_ms = 120 if selected else 0
                    if total_ms + separator_ms + len(segment) > 15000:
                        continue
                    selected.append((candidate, segment))
                    total_ms += separator_ms + len(segment)
                    if total_ms >= 10000:
                        break
                selected.sort(key=lambda value: value[0]['index'])
                reference_audio = AudioSegment.empty()
                text_parts = []
                for candidate, segment in selected:
                    if len(reference_audio):
                        reference_audio += AudioSegment.silent(duration=120, frame_rate=audio.frame_rate)
                    reference_audio += segment
                    text_parts.append(candidate['text'])
                reference_text = self._join_paragraph_text(text_parts, self.cfg.detect_language, reference=True)
                selection = f'清晰语句组合 {len(reference_audio) / 1000:.2f}s'

            ref_wav = queue_items[0]['ref_wav']
            reference_audio.set_frame_rate(24000).set_channels(1).export(ref_wav, format='wav')
            for item in queue_items:
                item['ref_wav'] = ref_wav
                item['ref_text'] = reference_text
            logger.info(f'固定音色参考 [{speaker_id}]: {selection}; 全片复用 {ref_wav}')
