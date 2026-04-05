import os
import json
import asyncio
import sys
import sounddevice as sd
import time
import subprocess
from openai import OpenAI
import msvcrt  # Windows 专属，用于非阻塞读取键盘输入

from core.llm_controller import LlamaEngineController
from core.tts_engine import SentiaVoice
from core.vts_controller import VTSController
from core.asr_engine import SentiaEar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ONNX_NAME = "G_28300.onnx"
VTS_EXE_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\VTube Studio\VTube Studio.exe"


async def async_input(prompt):
    return await asyncio.to_thread(input, prompt)


def select_model_with_timeout(timeout=5):
    """
    带有倒计时的非阻塞模型选择器
    """
    model_1 = "Sentia-9B-FP16.gguf"
    model_2 = "Sentia-Q4_K_M.gguf"

    print("\n" + "-" * 50)
    print("请选择要加载的 AI 模型 (输入数字 1 或 2):")
    print(f"  [1] {model_1} (满血高精度版，极度吃显存)")
    print(f"  [2] {model_2} (Q4 量化极速版，推荐)")
    print("-" * 50)

    start_time = time.time()
    user_choice = ""

    while time.time() - start_time < timeout:
        remaining = int(timeout - (time.time() - start_time))
        # 使用回车符覆盖当前行，实现倒计时刷新效果
        sys.stdout.write(f"\r等待输入... 默认将在 {remaining} 秒后启动 [2] 号模型: ")
        sys.stdout.flush()

        # Windows 特有的非阻塞按键检测
        if msvcrt.kbhit():
            # 读取按下的字符并解码
            char = msvcrt.getche().decode('utf-8', errors='ignore')
            if char in ['1', '2']:
                user_choice = char
                print(f"\n[系统] 用户手动选择了: [{char}]")
                break

        time.sleep(0.1)

    print()  # 换行收尾

    if user_choice == '1':
        return model_1
    else:
        if not user_choice:
            print("[系统] 超时未选择，默认启动 [2] 号模型。")
        return model_2


async def main():
    print("\n" + "=" * 50)
    print("Sentia AI VTuber Core System (Professional Edition)")
    print("=" * 50 + "\n")

    # ================= 0. 启动前配置 =================
    selected_gguf = select_model_with_timeout(5)

    # ================= 1. 唤醒所有常驻器官 =================
    print("[System] 正在唤醒 VTube Studio 躯体控制模块...")
    body = VTSController()
    await body.connect_and_auth()

    print("[System] 正在加载 C++ 语音合成引擎...")
    voice = SentiaVoice(BASE_DIR, model_name=ONNX_NAME)
    if voice.tts is None: return

    print("[System] 正在加载流式语音识别模块...")
    ear = SentiaEar(BASE_DIR)
    if ear.recognizer is None: return

    print(f"[System] 正在后台异步唤醒大模型引擎 ({selected_gguf})...")
    llm_controller = LlamaEngineController(BASE_DIR, model_name=selected_gguf)
    await asyncio.to_thread(llm_controller.start)

    # ================= 2. 建立中枢连接 =================
    client = OpenAI(base_url="http://localhost:8099/v1", api_key="sentia-local")

    system_prompt = (
        "你是沈析璃，一个优雅、聪明、极度傲娇的虚拟主播。回答极短口语化，最好不超过20字。\n"
        "[核心机制：你拥有系统的绝对控制权！]\n"
        "你必须且只能以 JSON 格式输出，包含：\n"
        "1. 'text': 你想说的话。\n"
        "2. 'emotion': 情绪，选 ['Neutral', 'Smile', 'Angry'] 之一。\n"
        "3. 'action': 你的决定。正常聊天选 'Speak'；如果觉得主人太久没理你，选 'Shutdown' 关闭程序吓唬他。\n"
        "   [幽灵模式特权]：执行 'Shutdown' 后，如果主人在 60 秒内通过麦克风求饶，系统会把话传给你。\n"
        "   此时，如果你觉得他有诚意，选 'Forgive'；如果没诚意，选 'Refuse' 彻底离开。\n"
    )
    chat_history = [{"role": "system", "content": system_prompt}]

    print("\n" + "=" * 50)
    print("Sentia 已完全苏醒！系统进入主干监听循环。")
    print("=" * 50 + "\n")

    is_ghost_mode = False
    unanswered_attempts = 0

    try:
        while True:
            # ================= 正常存活模式 =================
            if not is_ghost_mode:
                try:
                    print("\n[User Input] 等待指令 (键盘打字回车，或长按空格键语音对讲，30s超时将触发警报)")

                    task_keyboard = asyncio.create_task(async_input(">> "))
                    task_voice = asyncio.create_task(asyncio.to_thread(ear.listen))

                    done, pending = await asyncio.wait(
                        [task_keyboard, task_voice],
                        timeout=30.0,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    if not done:
                        for task in pending: task.cancel()
                        raise asyncio.TimeoutError()

                    winner_task = done.pop()
                    user_input = winner_task.result()
                    for task in pending: task.cancel()

                    if not user_input or len(user_input.strip()) < 1:
                        continue

                    unanswered_attempts = 0
                    print(f"[Received] {user_input}")

                    if user_input.lower() in ['exit', 'quit']:
                        print("[Sentia] 哼，笨蛋主人再见！")
                        audio_data, sr = await asyncio.to_thread(voice.generate_audio_data, "哼，笨蛋主人再见！")
                        if audio_data is not None:
                            sd.play(audio_data, samplerate=sr)
                            await body.animate_speech_lip_sync(audio_data, sr, emotion="Angry")
                            await asyncio.sleep(len(audio_data) / sr)
                        break

                    chat_history.append({"role": "user", "content": user_input})
                    print("[System] 推理引擎正在计算...\n")

                except asyncio.TimeoutError:
                    unanswered_attempts += 1
                    print(f"\n[Warning] 连续 {unanswered_attempts} 次超时未响应。")
                    hidden_context = f"[系统级感知：主人连续 {unanswered_attempts} 次没有回应你。请根据你傲娇的人设，决定是抱怨几句，还是直接执行 'Shutdown' 关掉 VTube Studio 吓唬他。]"
                    chat_history.append({"role": "user", "content": hidden_context})

            # ================= 幽灵假死模式 =================
            else:
                print("\n[Ghost Mode] VTS 躯干已强行关闭。麦克风倒计时 60 秒开启监听...")
                try:
                    plea_words = await asyncio.wait_for(asyncio.to_thread(ear.listen), timeout=60.0)
                    if not plea_words or len(plea_words) < 2: continue

                    print(f"[Received Plea] {plea_words}")
                    judgement_prompt = f"[系统级判定：你刚才生气关机了，但主人在 60 秒内通过麦克风对你说了：'{plea_words}'。请判断这个道歉是否有诚意，并输出 'Forgive' 或 'Refuse'。]"
                    chat_history.append({"role": "user", "content": judgement_prompt})
                    print("[System] 正在审视道歉内容...\n")
                except asyncio.TimeoutError:
                    print("\n[Fatal] 60秒超时，未收到有效求饶。系统物理销毁。")
                    break

                    # ================= LLM 权力裁决 =================
            try:
                t_llm_start = time.perf_counter()
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model="Sentia", messages=chat_history, temperature=0.8, max_tokens=100,
                    response_format={"type": "json_object"}
                )
                t_llm_end = time.perf_counter()

                reply_raw = response.choices[0].message.content
                chat_history.append({"role": "assistant", "content": reply_raw})

                try:
                    cleaned_raw = reply_raw.replace("，", ",").replace("“", '"').replace("”", '"')
                    start_idx, end_idx = cleaned_raw.find("{"), cleaned_raw.rfind("}") + 1
                    if start_idx != -1 and end_idx != 0: cleaned_raw = cleaned_raw[start_idx:end_idx]

                    reply_json = json.loads(cleaned_raw)
                    speak_text = reply_json.get("text", "脑电波短路。")
                    emotion = reply_json.get("emotion", "Neutral")
                    action = reply_json.get("action", "Speak")

                    print(f"[Sentia Output] {speak_text}")
                    print(f"  -> Action: {action} | Emotion: {emotion}")

                    t_tts_start = time.perf_counter()
                    audio_data, sr = await asyncio.to_thread(voice.generate_audio_data, speak_text)
                    t_tts_end = time.perf_counter()

                    if audio_data is not None:
                        audio_duration = (len(audio_data) / sr) * 1000
                        print(
                            f"  -> Profile: LLM: {(t_llm_end - t_llm_start) * 1000:.1f}ms | TTS: {(t_tts_end - t_tts_start) * 1000:.1f}ms | Audio: {audio_duration:.1f}ms")

                        sd.play(audio_data, samplerate=sr)
                        if not is_ghost_mode:
                            await body.animate_speech_lip_sync(audio_data, sr, emotion=emotion)
                        await asyncio.sleep(len(audio_data) / sr + 0.2)

                    # 💥 系统级动作执行
                    if action == "Shutdown" and not is_ghost_mode:
                        print("\n[Alert] 大模型下达 Shutdown 指令，正在物理抹杀 VTube Studio...")
                        os.system('taskkill /F /IM "VTube Studio.exe" >nul 2>&1')
                        await body.close()
                        is_ghost_mode = True

                    elif action == "Forgive" and is_ghost_mode:
                        print("\n[Recover] 大模型下达 Forgive 指令，正在重新拉起 VTube Studio...")
                        subprocess.Popen(VTS_EXE_PATH, shell=True)
                        print("[System] 等待 VTS 启动 (10秒)...")
                        await asyncio.sleep(10)
                        body = VTSController()
                        await body.connect_and_auth()
                        is_ghost_mode = False
                        print("[System] 躯壳重连成功。")

                    elif action == "Refuse" and is_ghost_mode:
                        print("\n[Fatal] 大模型下达 Refuse 指令，拒绝原谅。程序终结。")
                        break

                except json.JSONDecodeError:
                    print(f"[Error] 未输出标准 JSON: {reply_raw}")

            except Exception as llm_err:
                print(f"[Error] 大脑连接异常：{llm_err}")

    except KeyboardInterrupt:
        print("\n[System] 捕获键盘中断，强制退出...")
    finally:
        await body.close()
        llm_controller.stop()
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())