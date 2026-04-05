import os
import sherpa_onnx
import numpy as np


class SentiaVoice:
    def __init__(self, base_dir, model_name="G_28300.onnx"):
        print(" 正在加载 Sherpa-ONNX 语音模型...")
        models_dir = os.path.join(base_dir, "models")
        assets_dir = os.path.join(base_dir, "assets")

        lexicon_path = os.path.join(assets_dir, "lexicon.txt")
        dict_path = os.path.join(assets_dir, "dict")

        if not os.path.exists(lexicon_path):
            print(f" 找不到字典文件 {lexicon_path}！")
            self.tts = None
            return

        try:
            tts_config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=os.path.join(models_dir, model_name),
                        tokens=os.path.join(models_dir, "tokens.txt"),
                        lexicon=lexicon_path,
                        dict_dir=dict_path,
                    ),
                    provider="cpu", num_threads=4,
                ),
            )
            self.tts = sherpa_onnx.OfflineTts(tts_config)
            print(" TTS 加载成功！")
        except Exception as e:
            print(f" TTS 加载失败！报错: {e}")
            self.tts = None

    def generate_audio_data(self, text, speed=1.1):
        if not self.tts or not text or text.strip() == "":
            return None, None

        audio = self.tts.generate(text, sid=0, speed=speed)
        if audio is not None and len(audio.samples) > 0 and audio.sample_rate > 0:
            samples = np.array(audio.samples)
            target_sr = 44100
            if audio.sample_rate != target_sr:
                new_len = int((len(samples) / audio.sample_rate) * target_sr)
                samples = np.interp(np.linspace(0, 1, new_len), np.linspace(0, 1, len(samples)), samples)
            return samples, target_sr
        return None, None