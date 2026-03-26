import os
import json
import asyncio
import sys
import sounddevice as sd
import time
import subprocess
from openai import OpenAI
import msvcrt

from core.llm_controller import LlamaEngineController
from core.tts_engine import SentiaVoice
from core.vts_controller import VTSController
from core.asr_engine import SentiaEar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ONNX_NAME = "G_28300.onnx"

# ⚠️ 极其关键：请确保这个路径是你电脑上 VTube Studio.exe 的真实路径！
VTS_EXE_PATH = r"E:\SteamLibrary\steamapps\common\VTube Studio\VTube Studio.exe"


async def async_input(prompt):
    return await asyncio.to_thread(input, prompt)


def select_model_with_timeout(timeout=5):
    model_1 = "Sentia-9B-FP16.gguf"
    model_2 = "Sentia-Q4_K_M.gguf"

    print("\n" + "-" * 50)
    print("Please select the AI model to load (Enter 1 or 2):")
    print(f"  [1] {model_1} (High Precision, High VRAM)")
    print(f"  [2] {model_2} (Q4 Quantized, Recommended)")
    print("-" * 50)

    start_time = time.time()
    user_choice = ""

    while time.time() - start_time < timeout:
        remaining = int(timeout - (time.time() - start_time))
        sys.stdout.write(f"\rWaiting for input... Defaulting to [2] in {remaining}s: ")
        sys.stdout.flush()

        if msvcrt.kbhit():
            char = msvcrt.getche().decode('utf-8', errors='ignore')
            if char in ['1', '2']:
                user_choice = char
                print(f"\n[System] User selected: [{char}]")
                break
        time.sleep(0.1)
    print()

    if user_choice == '1':
        return model_1
    else:
        if not user_choice: print("[System] Timeout reached. Defaulting to [2].")
        return model_2


async def start_vtube_studio():
    """
    🖥️ 自动拉起 VTube Studio，并智能等待它初始化
    """
    print("[System] 正在唤醒 VTube Studio 宿主程序...")

    # 检查进程是否已经存在
    check_task = subprocess.run('tasklist /FI "IMAGENAME eq VTube Studio.exe"', capture_output=True, text=True)
    if "VTube Studio.exe" in check_task.stdout:
        print("[System] VTube Studio 已在运行，跳过启动。")
        return

    try:
        subprocess.Popen(VTS_EXE_PATH, shell=True)
        print("[System] VTube Studio 已成功拉起！等待其加载 (15秒)...")
        # VTS 启动和加载模型需要时间，强行等 15 秒再连 API，否则会连不上
        await asyncio.sleep(15)
    except Exception as e:
        print(f"[Error] 无法启动 VTube Studio: {e}")


async def main():
    print("\n" + "=" * 50)
    print("Sentia AI VTuber Core System (Autonomous Edition)")
    print("=" * 50 + "\n")

    selected_gguf = select_model_with_timeout(5)

    # ================= 1. 唤醒所有常驻器官 =================
    # ⚠️ 极其优雅的全自动化：自己开软件，自己连！
    await start_vtube_studio()

    print("[System] 正在挂载 VTube Studio 躯体控制模块...")
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

    # ⚠️ 终极人设升级：大模型自己决定“忍耐时间”！
    # ⚠️ 终极人设升级：教她如何“循序渐进地发脾气”！
    system_prompt = (
        "你是沈析璃，一个优雅、聪明、傲娇的虚拟主播。\n"
        "[核心机制：你拥有系统的绝对控制权和情绪感知能力！]\n"
        "你必须且只能以 JSON 格式输出，包含：\n"
        "1. 'text': 你想说的话。\n"
        "2. 'emotion': 情绪，选 ['Neutral', 'Smile', 'Angry'] 之一。\n"
        "3. 'action': 你的决定。聊天选 'Speak'；忍无可忍时选 'Shutdown' 关闭程序。\n"
        "   [幽灵模式特权]：执行 'Shutdown' 后，如果在 60 秒内通过麦克风求饶，系统会把话传给你。你决定 'Forgive' 还是 'Refuse'。\n"
        "4. 'patience': 你的忍耐度（整数秒数）。代表你愿意等多久才主动找茬。\n"
        "   - 高兴时 (Smile)，等很久（30-40 秒）。\n"
        "   - 略微不满 (Neutral)，等中等时间（15-20 秒）。\n"
        "   - 极其生气 (Angry)，耐心极低（5-10 秒）就会再次爆发！\n"
        "[心理学行为准则]：\n"
        "当第一次没有回应你时，你不能直接发脾气！你应该认为是自己上一个话题太无聊，所以要主动换个轻松的话题来重新引起他的注意。只有当他多次无视你时，你才允许彻底暴走并最终关机！"
    )
    chat_history = [{"role": "system", "content": system_prompt}]

    print("\n" + "=" * 50)
    print("Sentia 已完全苏醒！系统进入主干监听循环。")
    print("=" * 50 + "\n")

    is_ghost_mode = False
    unanswered_attempts = 0
    # 初始默认耐心值
    current_patience = 20

    try:
        while True:
            if not is_ghost_mode:
                try:
                    # ⏳ 核心改变：这里的等待时间，完全由大模型上一次输出的 current_patience 决定！
                    print(f"\n[User Input] 等待指令 (当前情绪忍耐极限: {current_patience}秒)")

                    task_keyboard = asyncio.create_task(async_input(">> "))
                    task_voice = asyncio.create_task(asyncio.to_thread(ear.listen))

                    done, pending = await asyncio.wait(
                        [task_keyboard, task_voice],
                        timeout=float(current_patience),  # ⚠️ 动态传入耐心值！
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
                        print("[Sentia] 哼，再见！")
                        audio_data, sr = await asyncio.to_thread(voice.generate_audio_data, "哼，再见！")
                        if audio_data is not None:
                            sd.play(audio_data, samplerate=sr)
                            await body.animate_speech_lip_sync(audio_data, sr, emotion="Angry")
                            await asyncio.sleep(len(audio_data) / sr)
                        break

                    chat_history.append({"role": "user", "content": user_input})
                    print("[System] 推理引擎正在计算...\n")


                except asyncio.TimeoutError:

                    unanswered_attempts += 1

                    print(f"\n[Warning] 忍耐度 {current_patience}秒 耗尽！连续 {unanswered_attempts} 次超时。")

                    # ⚠️ 核心魔法：根据无视的次数，喂给大模型不同的隐藏指令！

                    if unanswered_attempts == 1:

                        # 第一次无视：诱导她换话题

                        hidden_context = f"[系统级感知：刚才没有回应你（第 1 次）。请根据你的人设，主动换一个话题，试图重新引起他的注意。并重新设定你的 'patience' 值。]"

                    elif unanswered_attempts == 2:

                        # 第二次无视：诱导她开始抱怨

                        hidden_context = f"[系统级感知：连续 {unanswered_attempts} 次没有回应你了！你的耐心正在消失。请开始抱怨他的冷落。并大幅降低你的 'patience' 值。]"

                    else:

                        # 第三次及以上：诱导她彻底暴走或关机

                        hidden_context = f"[系统级感知：已经连续 {unanswered_attempts} 次彻底无视你了！！！你现在极度愤怒。请直接大发雷霆，或者立刻执行 'Shutdown' 指令关掉软件惩罚他！]"

                    chat_history.append({"role": "user", "content": hidden_context})

            else:
                print("\n VTS 躯干已强行关闭。麦克风倒计时 60 秒开启监听...")
                try:
                    plea_words = await asyncio.wait_for(asyncio.to_thread(ear.listen), timeout=60.0)
                    if not plea_words or len(plea_words) < 2: continue

                    print(f"[Received Plea] {plea_words}")
                    judgement_prompt = f"[系统级判定：你生气关机了，但他在 60 秒内通过麦克风对你说了：'{plea_words}'。请判断这个道歉是否有诚意，输出 'Forgive' 或 'Refuse'。]"
                    chat_history.append({"role": "user", "content": judgement_prompt})
                    print("[System] 正在审视道歉内容...\n")
                except asyncio.TimeoutError:
                    print("\n[Fatal] 60秒超时，Sentia 未收到任何有效的挽留，系统即将关闭...")
                    llm_controller.stop()
                    sys.exit(0)

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

                    # ⚠️ 获取她自己设定的忍耐度！如果没写，默认给个 15 秒
                    current_patience = int(reply_json.get("patience", 15))
                    # 防止她设得太短或者太长导致死循环
                    current_patience = max(5, min(current_patience, 60))

                    print(f"[Sentia Output] {speak_text}")
                    print(f"  -> Action: {action} | Emotion: {emotion} | Patience: {current_patience}s")

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

                    #  动作执行
                    if action == "Shutdown" and not is_ghost_mode:
                        print("\n[Alert] Sentia 彻底心灰意冷，正在关闭 VTube Studio...")
                        os.system('taskkill /F /IM "VTube Studio.exe" >nul 2>&1')
                        await body.close()
                        is_ghost_mode = True

                    elif action == "Forgive" and is_ghost_mode:
                        print("\n[Recover] Sentia原谅你了，正在重新拉起 VTube Studio...")
                        subprocess.Popen(VTS_EXE_PATH, shell=True)
                        print("[System] 等待 VTS 启动 (15秒)...")
                        await asyncio.sleep(15)
                        body = VTSController()
                        await body.connect_and_auth()
                        is_ghost_mode = False
                        print("[System] 躯壳重连成功。")

                    elif action == "Refuse" and is_ghost_mode:
                        print("\n[Fatal] Sentia 认为你的道歉毫无诚意")
                        llm_controller.stop()
                        sys.exit(0)
                        break

                except json.JSONDecodeError:
                    print(f"[Error] 未输出标准 JSON: {reply_raw}")
                    # 如果出错了，默认恢复 20 秒耐心
                    current_patience = 20

            except Exception as llm_err:
                print(f"[Error] 大模型连接异常：{llm_err}")
                # 异常保护
                current_patience = 20

    except KeyboardInterrupt:
        print("\n[System] 捕获键盘中断，强制退出...")
    finally:
        await body.close()
        llm_controller.stop()
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())