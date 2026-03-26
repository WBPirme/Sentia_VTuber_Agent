import os
import sherpa_onnx
import sounddevice as sd
import numpy as np

# ================= 1. 本地字典资源路径 =================
# 直接指向你本地已经准备好的前端字典文件夹
assets_dir = "assets"

# ================= 2. 专属模型路径 =================
# 确保你的模型和 token 文件放在了 models 文件夹下
model_path = "./models/G_28300.onnx"
tokens_path = "./models/tokens.txt"

# ================= 3. 缝合 Sherpa-onnx (纯本地无网流) =================
print("🚀 正在加载本地引擎与字典，唤醒 Sentia...")
tts_config = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=model_path,
            tokens=tokens_path,
            # 直接读取本地实体文件
            lexicon=os.path.join(assets_dir, "lexicon.txt"),
            dict_dir=os.path.join(assets_dir, "dict"),
        ),
        provider="cpu",
        num_threads=4, # 榨干 CPU 多核性能
    ),
    # VFFT 架构不需要 rule_fars，留空
)

tts = sherpa_onnx.OfflineTts(tts_config)

def speak(text, sid=0, speed=1.0):
    print(f"🗣️ Sentia 正在思考怎么读: {text}")
    audio = tts.generate(text, sid=sid, speed=speed)
    
    if audio is None:
        print("❌ 合成失败！请检查字典是否覆盖了这些字词。")
        return
        
    print("🎵 正在播放...")
    # 直接推流到本地扬声器/虚拟声卡
    sd.play(np.array(audio.samples), samplerate=audio.sample_rate)
    sd.wait()

if __name__ == "__main__":
    speak("你好呀，我是虚拟主播 Sentia！主人，我的纯本地断网版声带终于搞定啦！", sid=0, speed=1.0)