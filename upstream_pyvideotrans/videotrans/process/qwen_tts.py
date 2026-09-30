# 语音合成，新进程执行
# 返回元组
# 失败：第一个值为False，则为失败，第二个值存储失败原因
# 成功，第一个值存在需要的返回值，不需要时返回True，第二个值为None
import time
from pathlib import Path
import traceback, json
from typing import Tuple, Union
from videotrans.configure.config import logger,ROOT_DIR,REDUBB_QUEUE_FILE,REDUBB_STATUS_FILE
from ._utils import _write_log,convert_to_wav


def qwen3tts_fun(
        queue_tts_file=None,# 配音数据存在 json文件下，根据文件路径获取
        language='Auto',#语言
        logs_file=None,
        is_cuda=False,
        prompt=None,
        model_name='1.7B',
        device_index=0, # gpu索引
        is_redubb=False#是否处于单视频校对配音流程
)->Tuple[bool,Union[str,None]]:
    from videotrans.util.help_role import get_qwenttslocal_rolelist
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    from videotrans.util.help_misc import vail_file
    CUSTOM_VOICE= {"Vivian", "Serena", "Uncle_fu", "Dylan", "Eric", "Ryan", "Aiden", "Ono_anna", "Sohee"}
    

    atten=None
    if is_cuda:
        device_map = f'cuda:{device_index}'
        # qwen_tts 在cuda加速时可能遇到 device-side assert triggered 报错，改为 float32 或  bfloat16 类型可解决
        dtype=torch.float16 if not torch.cuda.is_bf16_supported() else torch.bfloat16
    else:
        device_map = 'cpu'
        dtype=torch.float32

    logger.debug(f'Qwen-TTS本地内置渠道使用 {model_name} 模型，{device_map=},{is_cuda=}')

    BASE_OBJ=None
    CUSTOM_OBJ=None
    voice_prompt_cache={}
    if is_redubb:
        queue_tts_file=REDUBB_QUEUE_FILE
    try:
        while 1:
            if is_redubb and Path(REDUBB_STATUS_FILE).exists():
                return True,None
            queue_tts=json.loads(Path(queue_tts_file).read_text(encoding='utf-8'))
            all_roles={ r.get('role') for r in queue_tts}
            if (all_roles & CUSTOM_VOICE) and not CUSTOM_OBJ:
                # 存在自定义音色
                CUSTOM_OBJ=Qwen3TTSModel.from_pretrained(
                    f"{ROOT_DIR}/models/models--Qwen--Qwen3-TTS-12Hz-{model_name}-CustomVoice",
                    device_map=device_map,
                    dtype=dtype,
                    attn_implementation=atten
                )
                logger.debug(f'存在内置自定义音色，加载 {model_name} 模型')
            if ("clone" in all_roles or all_roles-CUSTOM_VOICE) and not BASE_OBJ:
                # 存在克隆音色
                BASE_OBJ=Qwen3TTSModel.from_pretrained(
                    f"{ROOT_DIR}/models/models--Qwen--Qwen3-TTS-12Hz-{model_name}-Base",
                    device_map=device_map,
                    dtype=dtype,
                    attn_implementation=atten
                )
                logger.debug(f'需要克隆音色，加载 {model_name} 模型')

            _len=len(queue_tts)
            ok,err=0,0
            last_error=''
            roledict=get_qwenttslocal_rolelist()
            for i,it in enumerate(queue_tts):
                if is_redubb and Path(REDUBB_STATUS_FILE).exists():
                    return True,None
                output_filename=it.get('filename','')+"-24k.wav"
                if vail_file(it.get('filename','')):
                    ok+=1
                    continue
                text=it.get('text')
                if not text:
                    err+=1
                    last_error="No text for dubbing"
                    continue
                role=it.get('role')
                _write_log(logs_file, json.dumps({"type": "logs", "text": f'Qwen3-TTS {i+1}/{_len} {role}'}))
                if role in CUSTOM_VOICE and CUSTOM_OBJ:
                    wavs, sr = CUSTOM_OBJ.generate_custom_voice(
                        text=text,
                        language=language, # Pass `Auto` (or omit) for auto language adaptive; if the target language is known, set it explicitly.
                        speaker=role,
                        instruct=prompt
                    )
                    sf.write(output_filename, wavs[0], sr)
                    ok+=1
                    continue
                if not BASE_OBJ:
                    err+=1
                    last_error='load model failed: not BASE_OBJ'
                    continue
                if role == 'clone':
                    wavfile = it.get('ref_wav', '')
                    ref_text = it.get('ref_text', '')
                else:
                    # 使用 f5-tts文件夹内音频
                    wavfile = f'{ROOT_DIR}/f5-tts/{role}'
                    ref_text = roledict.get(role,{}).get('ref_text') if roledict  else None

                if not wavfile or not Path(wavfile).is_file():
                    # 仍然不存在，无参考音频不可用
                    msg = f"No ref_audio: {role=},{wavfile=}"
                    _write_log(logs_file, json.dumps({"type": "logs", "text": msg}))
                    err+=1
                    last_error=msg
                    continue
                kw={
                    "text":text,
                    "language":language,
                }
                # Qwen3-TTS defaults to 2048 codec tokens. A rare missed EOS on
                # a short subtitle can therefore synthesize minutes of audio
                # and appear to hang. The tokenizer runs at roughly 12 Hz, so
                # allow about 2.5x the subtitle duration plus a generous margin.
                # This still accommodates cross-language length differences
                # while bounding pathological generations.
                duration_ms = max(
                    1000,
                    int(it.get('end_time', 0) or 0) - int(it.get('start_time', 0) or 0),
                )
                kw['max_new_tokens'] = max(128, min(2048, int(duration_ms * 0.03) + 64))
                # ICL cloning needs enough reference speech to align the audio
                # codes with ref_text. For very short clips it can miss EOS and
                # run to the token cap; speaker-vector cloning is stable there.
                x_vector_only = not bool(ref_text)
                speaker_key = str(it.get('speaker_id') or role or wavfile)
                prompt_key = (speaker_key, str(wavfile), str(ref_text), x_vector_only)
                if prompt_key not in voice_prompt_cache:
                    voice_prompt_cache[prompt_key] = BASE_OBJ.create_voice_clone_prompt(
                        ref_audio=wavfile,
                        ref_text=ref_text or None,
                        x_vector_only_mode=x_vector_only,
                    )
                    logger.info(f'Qwen3-TTS 已创建固定音色特征: {speaker_key}; 后续句段全部复用')
                    _write_log(logs_file, json.dumps({
                        "type": "logs",
                        "text": f'固定音色已建立 [{speaker_key}]，全片复用',
                    }, ensure_ascii=False))
                kw['voice_clone_prompt'] = voice_prompt_cache[prompt_key]
                wavs, sr = BASE_OBJ.generate_voice_clone(**kw)
                sf.write(output_filename, wavs[0], sr)
                ok+=1
                if is_redubb:
                    convert_to_wav(output_filename,it['filename'])

            # 是重新配音，继续轮询
            if is_redubb:
                time.sleep(1)
                continue
            break
        if ok<1:
            logger.error(f'配音全部失败：{last_error}')
            return False,"Dubbing failed"+last_error
        logger.debug(f'配音成功{ok}个，失败{err}个')
        _write_log(logs_file, json.dumps({"type": "logs", "text": f'{ok=},{err=} {last_error}'}))
        return True,None
    except BaseException as e:
        msg = traceback.format_exc()
        logger.error(msg)
        return False, f'{e},{msg}'
