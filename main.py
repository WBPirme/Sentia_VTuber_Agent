import os
import asyncio
import sounddevice as sd
import time
from openai import OpenAI
from core.llm_controller import LlamaEngineController
from core.tts_engine import SentiaVoice
from core.vts_controller import VTSController

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GGUF_NAME = "Sentia-9B-FP16.gguf"
ONNX_NAME = "G_28300.onnx"


async def main():
    total_start_time = time.perf_counter()

    print("连接VTube Studio")
    body = VTSController()
    await body.connect_and_auth()
    print("完成\n")

    print("加载Sherpa-ONNX")
    voice = SentiaVoice(BASE_DIR, model_name=ONNX_NAME)
    if voice.tts is None: return
    print("完成\n")

    print(f"加载模型 ({GGUF_NAME})")
    llm_controller = LlamaEngineController(BASE_DIR, model_name=GGUF_NAME)
    await asyncio.to_thread(llm_controller.start)

    client = OpenAI(base_url="http://localhost:8099/v1", api_key="sentia-local")

    system_prompt = "你是沈析璃，一个虚拟主播，只说中文。"
    chat_history = [{"role": "system", "content": system_prompt}]

    print(f"\n 加载 Sentia 总耗时: {time.perf_counter() - total_start_time:.2f}秒\n")

    try:
        while True:
            user_input = await asyncio.to_thread(input, "你对 Sentia 说: ")

            if user_input.lower() in ['exit', 'quit']:
                print("Sentia: 哼，再见！")
                audio_data, sr = voice.generate_audio_data("哼，再见！")
                if audio_data is not None:
                    sd.play(audio_data, samplerate=sr)
                    await body.animate_speech_lip_sync(audio_data, sr)
                    await asyncio.sleep(len(audio_data) / sr)
                    sd.wait()
                break

            chat_history.append({"role": "user", "content": user_input})

            try:
                t_llm_start = time.perf_counter()
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model="Sentia",
                    messages=chat_history,
                    temperature=1.2,
                    max_tokens=100
                )

                t_llm_end = time.perf_counter()
                llm_cost = (t_llm_end - t_llm_start) # 转为毫秒

                reply_text = response.choices[0].message.content
                chat_history.append({"role": "assistant", "content": reply_text})
                print(f" Sentia: {reply_text}")

                t_tts_start = time.perf_counter()

                audio_data, sr = await asyncio.to_thread(voice.generate_audio_data, reply_text)

                t_tts_end = time.perf_counter()
                tts_cost = (t_tts_end - t_tts_start)

                if audio_data is not None:
                    audio_duration = (len(audio_data) / sr)

                    print(f"LLM思考: {llm_cost:.1f}ms | TTS合成: {tts_cost:.1f}ms | 音频时长: {audio_duration:.1f}ms")

                    sd.play(audio_data, samplerate=sr)
                    await body.animate_speech_lip_sync(audio_data, sr)
                    await asyncio.sleep(0.1)


            except Exception as err:
                print(f"系统运行异常：{err}")

    except KeyboardInterrupt:
        print("\n强制退出...")
    finally:
        await body.close()
        llm_controller.stop()


if __name__ == "__main__":
    asyncio.run(main())