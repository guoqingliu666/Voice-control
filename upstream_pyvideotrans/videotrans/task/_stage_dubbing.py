import copy
import json
import re
import shutil
import time
from pathlib import Path

from videotrans.configure._paths import DUBBING_CACHE
from videotrans.configure.config import tr, app_cfg, settings, logger
from videotrans.configure.excepts import DubbingSrtError
from videotrans.tts import run as run_tts, SUPPORT_CLONE
from videotrans.util.help_misc import get_md5, vail_file
from videotrans.util.help_srt import get_subtitle_from_srt, delete_punc


class DubbingMixin:

    @staticmethod
    def _join_paragraph_text(parts, language_code, reference=False):
        """Join adjacent subtitle lines without creating a pause at every line."""
        clean = [str(part or '').strip() for part in parts if str(part or '').strip()]
        if not clean:
            return ''
        is_cjk = str(language_code or '').lower().split('-')[0] in {'zh', 'ja', 'ko'}
        if reference:
            return ('' if is_cjk else ' ').join(clean)

        result = clean[0]
        for part in clean[1:]:
            # A light comma asks the TTS model for a natural intra-paragraph
            # breath when ASR/translation omitted punctuation at a line break.
            if not re.search(r'[,.!?;:，。！？；：…]$', result):
                result += '，' if is_cjk else ','
            result += '' if is_cjk else ' '
            result += part
        return result

    def _build_semantic_groups(self, target_subs, source_subs, speakers, line_roles, default_role):
        """Group nearby same-speaker lines into natural 6-15 second paragraphs."""
        records = []
        for i, target in enumerate(target_subs):
            source = source_subs[i] if i < len(source_subs) else target
            if (
                target['end_time'] < target['start_time']
                or (not target['text'].strip() and not source['text'].strip())
            ):
                continue
            role = line_roles.get(f'{target["line"]}', default_role) if line_roles else default_role
            speaker = str(speakers[i] if i < len(speakers) and speakers[i] else 'spk0')
            records.append({
                'index': i,
                'target': target,
                'source': source,
                'role': role,
                'speaker': speaker,
            })

        if self.cfg.tts_type != 1 or len(records) < 2:
            return [[record] for record in records]

        groups = []
        current = []
        strong_end = re.compile(r'[.!?。！？…][\"\'”’）)]*$')
        for record in records:
            if current:
                previous = current[-1]
                group_start = current[0]['source']['start_time']
                group_duration = previous['source']['end_time'] - group_start
                gap = record['source']['start_time'] - previous['source']['end_time']
                proposed_duration = record['source']['end_time'] - group_start
                same_voice = (
                    record['speaker'] == previous['speaker']
                    and record['role'] == previous['role']
                )
                # Prefer sentence boundaries once a paragraph is long enough,
                # but never cross a long pause, a speaker change, or 15 seconds.
                should_split = (
                    not same_voice
                    or gap > 1200
                    or proposed_duration > 15000
                    or len(current) >= 5
                    or (group_duration >= 6000 and strong_end.search(previous['target']['text'].strip()))
                )
                if should_split:
                    groups.append(current)
                    current = []
            current.append(record)
            duration = current[-1]['source']['end_time'] - current[0]['source']['start_time']
            if duration >= 12000 and strong_end.search(record['target']['text'].strip()):
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        # Avoid leaving a tiny final fragment when it can safely share the prior
        # paragraph without crossing speaker/voice or the 15-second ceiling.
        if len(groups) >= 2:
            tail = groups[-1]
            previous = groups[-2]
            tail_duration = tail[-1]['source']['end_time'] - tail[0]['source']['start_time']
            combined_duration = tail[-1]['source']['end_time'] - previous[0]['source']['start_time']
            gap = tail[0]['source']['start_time'] - previous[-1]['source']['end_time']
            if (
                tail_duration < 3000
                and combined_duration <= 15000
                and gap <= 1200
                and tail[0]['speaker'] == previous[-1]['speaker']
                and tail[0]['role'] == previous[-1]['role']
                and len(previous) + len(tail) <= 5
            ):
                groups[-2].extend(groups.pop())
        return groups

    def dubbing(self) -> None:
        _st=time.time()
        if self._exit() or self.cfg.app_mode == 'tiqu':
            return
        if self.should_dubbing:
            self.signal(text=tr('kaishipeiyin'))
        self.precent += 3
        self._tts()
        
        if  Path(self.cfg.source_sub).exists():
            logger.debug('配音结束后，移除原始字幕中所有标点')
            subs = get_subtitle_from_srt(self.cfg.source_sub)
            for it in subs:
                if self.cfg.fix_punc==2:
                    it['text']=delete_punc(it['text'])
                it['text']=it['text'].strip('...')
            self._save_srt_target(subs, self.cfg.source_sub)
        if self.should_dubbing:
            self.signal(text=tr('The dubbing is finished'))
            logger.debug(f'[语音合成阶段结束耗时]:{time.time()-_st}s')

    def _tts(self) -> None:
        if not self.should_dubbing:
            self.signal(text='Skip tts')
            return
        queue_tts = []
        subs = get_subtitle_from_srt(self.cfg.target_sub)
        source_subs = get_subtitle_from_srt(self.cfg.source_sub)
        if len(subs) < 1:
            raise DubbingSrtError(f"SRT file error:{self.cfg.target_sub}")
        try:
            rate = int(str(self.cfg.voice_rate).replace('%', ''))
        except (ValueError,TypeError):
            rate = 0

        rate = f"+{rate}%" if rate >= 0 else f"{rate}%"

        line_roles = app_cfg.line_roles
        voice_role = self.cfg.voice_role
        logger.debug(f'{line_roles=}')
        _lang=self.cfg.detect_language.split('-')[0]
        speakers = []
        speaker_file = Path(self.cfg.cache_folder) / 'speaker.json'
        if speaker_file.is_file():
            try:
                speakers = json.loads(speaker_file.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError) as exc:
                logger.warning(f'读取说话人标记失败，按单人视频处理: {exc}')

        groups = self._build_semantic_groups(subs, source_subs, speakers, line_roles, voice_role)
        self._voice_ref_candidates = {}
        grouped_source_subs = []
        for i, group in enumerate(groups):
            it = group[0]['target']
            source_first = group[0]['source']
            source_last = group[-1]['source']
            voice = group[0]['role']
            speaker_id = group[0]['speaker']
            target_text = self._join_paragraph_text(
                [record['target']['text'] for record in group],
                self.cfg.target_language_code,
            )
            source_text = self._join_paragraph_text(
                [record['source']['text'] for record in group],
                self.cfg.detect_language,
                reference=True,
            )

            for record in group:
                self._voice_ref_candidates.setdefault(speaker_id, []).append({
                    'index': record['index'],
                    'start_time': record['source']['start_time'],
                    'end_time': record['source']['end_time'],
                    'text': record['source']['text'],
                })

            # Include the local Qwen integration revision so audio generated by
            # older decoding rules is never silently reused after an upgrade.
            cache_revision = 'qwen3local-v3-fixed-voice-paragraphs' if self.cfg.tts_type == 1 else ''
            _key = get_md5(f"{self.cfg.target_language_code}-{target_text}-{voice}-{speaker_id}-{rate}-{self.cfg.volume}-{self.cfg.pitch}-{self.cfg.tts_type}-{cache_revision}")

            tmp_dict = {
                "text": target_text,
                "line": i + 1,
                "start_time": it['start_time'],
                "end_time": group[-1]['target']['end_time'],
                "startraw": it['startraw'],
                "endraw": group[-1]['target']['endraw'],
                "ref_text": source_text,
                "start_time_source": source_first['start_time'],
                "end_time_source": source_last['end_time'],
                "speaker_id": speaker_id,
                "role": voice,
                "rate": rate,
                "volume": self.cfg.volume,
                "pitch": self.cfg.pitch,
                "tts_type": self.cfg.tts_type,
                "filename": f"{self.cfg.cache_folder}/{i}-{_key}.wav"
            }
            _dubbing_cache=f'{DUBBING_CACHE}/{_key}.wav'
            if vail_file(_dubbing_cache):
                # 直接使用缓存
                shutil.copy2(_dubbing_cache,tmp_dict['filename'])
            if str(voice).strip().lower() == 'clone' and self.cfg.tts_type in SUPPORT_CLONE:
                safe_speaker = re.sub(r'[^0-9A-Za-z_-]+', '_', speaker_id) or 'spk0'
                tmp_dict['ref_wav'] = f"{self.cfg.cache_folder}/clone-speaker-{safe_speaker}.wav"
                tmp_dict['ref_language'] = _lang
            queue_tts.append(tmp_dict)
            grouped_source_subs.append({
                'line': i + 1,
                'start_time': source_first['start_time'],
                'end_time': source_last['end_time'],
                'startraw': source_first['startraw'],
                'endraw': source_last['endraw'],
                'text': source_text,
            })

        if self.cfg.tts_type == 1 and len(groups) != len(subs):
            logger.info(f'Qwen3-TTS 语义段落合并: {len(subs)} 条字幕 -> {len(groups)} 个配音段')
            self._save_srt_target(grouped_source_subs, self.cfg.source_sub)

        self.queue_tts = copy.deepcopy(queue_tts)

        if not self.queue_tts or len(self.queue_tts) < 1:
            raise RuntimeError(f'字幕长度为0，无法继续配音')

        if len([it.get("ref_wav") for it in self.queue_tts if it.get("ref_wav")]) > 0:
            self._create_ref_from_vocal()

        run_tts(
            queue_tts=self.queue_tts,
            language=self.cfg.target_language_code,
            uuid=self.uuid,
            tts_type=self.cfg.tts_type,
            is_cuda=self.cfg.is_cuda
        )
        outname=None
        if settings.get('save_segment_audio', False):
            outname = self.cfg.target_dir + f'/segment_audio_{self.cfg.noextname}'
            Path(outname).mkdir(parents=True, exist_ok=True)
        for it in self.queue_tts:
            it['text']=it['text'].strip('...')
            if self.cfg.fix_punc==2:
                it['text']=delete_punc(it['text'])
            if Path(it['filename']).exists():
                # 保存缓存
                shutil.copy2(it['filename'],f'{DUBBING_CACHE}/'+Path(it['filename']).name.split('-')[-1])
                if outname:
                    text = re.sub(r'["\'*?\\/|:<>\r\n\t]+', '', it['text'], flags=re.I | re.S)
                    name = f'{outname}/{it["line"]}-{text[:60]}.wav'
                    shutil.copy2(it['filename'], name)
        
        self._save_srt_target(self.queue_tts, self.cfg.target_sub)
