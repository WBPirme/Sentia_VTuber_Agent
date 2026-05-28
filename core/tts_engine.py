import os
import sherpa_onnx
import numpy as np
import re


class SentiaVoice:
    def __init__(self, base_dir, model_name="G_28300.onnx"):
        print(" 正在加载 Sherpa-ONNX 语音模型...")
        models_dir = os.path.join(base_dir, "models")
        assets_dir = os.path.join(base_dir, "assets")
        self.output_sample_rate = int(os.getenv("SENTIA_TTS_OUTPUT_SR", "44100"))
        self.output_target_peak = min(0.95, max(0.05, float(os.getenv("SENTIA_TTS_TARGET_PEAK", "0.75"))))
        self.output_gain = max(0.1, float(os.getenv("SENTIA_TTS_GAIN", "1.0")))
        self.output_max_gain = max(self.output_gain, float(os.getenv("SENTIA_TTS_MAX_GAIN", "1200.0")))
        self.output_noise_floor = max(1e-6, float(os.getenv("SENTIA_TTS_NOISE_FLOOR", "0.00005")))

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

    def _normalize_samples(self, samples):
        normalized = np.asarray(samples, dtype=np.float32)
        if normalized.ndim > 1:
            normalized = normalized.mean(axis=1)
        normalized = np.nan_to_num(normalized, nan=0.0, posinf=0.0, neginf=0.0)
        if normalized.size == 0:
            return normalized

        normalized = normalized - float(np.mean(normalized))
        peak = float(np.max(np.abs(normalized)))
        gain = self.output_gain
        if peak > self.output_noise_floor:
            gain = min(self.output_max_gain, max(self.output_gain, self.output_target_peak / peak))
        normalized *= gain
        np.clip(normalized, -1.0, 1.0, out=normalized)
        return normalized

    def generate_audio_data(self, text, speed=0.85):
        if not self.tts or not text or text.strip() == "":
            return None, None

        text = re.sub(r'[a-zA-Z\{\}\[\]\"\'\\_:=]+', '', text).strip()

        if not text:
            return None, None

        audio = self.tts.generate(text, sid=0, speed=speed)
        if audio is not None and len(audio.samples) > 0 and audio.sample_rate > 0:
            samples = self._normalize_samples(audio.samples)
            target_sr = self.output_sample_rate
            if audio.sample_rate != target_sr:
                new_len = int((len(samples) / audio.sample_rate) * target_sr)
                if new_len > 0:
                    samples = np.interp(
                        np.linspace(0, 1, new_len, dtype=np.float32),
                        np.linspace(0, 1, len(samples), dtype=np.float32),
                        samples
                    ).astype(np.float32, copy=False)
            return np.ascontiguousarray(samples, dtype=np.float32), target_sr
        return None, None
