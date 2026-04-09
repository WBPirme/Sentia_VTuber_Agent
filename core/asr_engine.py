import os
import queue
import time
import sounddevice as sd
import sherpa_onnx
import keyboard


class SentiaEar:
    def __init__(self, base_dir):
        print(" 正在加载 Sherpa-ONNX 听觉模型...")
        model_dir = os.path.join(base_dir, "models", "asr")

        try:
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=os.path.join(model_dir, "tokens.txt"),
                encoder=os.path.join(model_dir, "encoder-epoch-99-avg-1.onnx"),
                decoder=os.path.join(model_dir, "decoder-epoch-99-avg-1.onnx"),
                joiner=os.path.join(model_dir, "joiner-epoch-99-avg-1.onnx"),
                num_threads=2,
                sample_rate=16000,
                feature_dim=80,
                rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=1.2,
                rule3_min_utterance_length=30.0,
                provider="cpu"
            )
            print(" ASR 加载成功！")
        except Exception as e:
            print(f" ASR 加载失败！请检查 models 目录。\n报错: {e}")
            self.recognizer = None

        self.sample_rate = 16000
        self.audio_queue = queue.Queue()

    def _audio_callback(self, indata, frames, time_info, status):
        self.audio_queue.put(indata[:, 0].copy())

    def _clear_audio_queue(self):
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

    def _get_stream_text(self, stream):
        text = self.recognizer.get_result(stream)
        return text.strip() if text else ""

    def listen(self, stop_event=None):
        if not self.recognizer:
            return ""

        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return ""
                if keyboard.is_pressed('space'):
                    break
                time.sleep(0.05)

            self._clear_audio_queue()
            print("\n [录音中... 请保持按住空格，松开发送]")
            stream = self.recognizer.create_stream()
            last_text = ""

            with sd.InputStream(channels=1, dtype="float32", samplerate=self.sample_rate, callback=self._audio_callback):
                while keyboard.is_pressed('space'):
                    if stop_event is not None and stop_event.is_set():
                        break
                    try:
                        chunk = self.audio_queue.get_nowait()
                        stream.accept_waveform(self.sample_rate, chunk)
                        while self.recognizer.is_ready(stream):
                            self.recognizer.decode_stream(stream)

                        current_text = self._get_stream_text(stream)
                        if current_text and current_text != last_text:
                            print(f"\r 听到: {current_text}", end="", flush=True)
                            last_text = current_text
                    except queue.Empty:
                        time.sleep(0.001)

            if stop_event is not None and stop_event.is_set():
                return ""

            print("\n [松开按键，录音结束]")
            stream.input_finished()
            while self.recognizer.is_ready(stream):
                self.recognizer.decode_stream(stream)

            return self._get_stream_text(stream)
        except Exception as e:
            print(f"\n[ASR Warning] 语音输入失败，已回退为键盘输入: {e}")
            return ""
