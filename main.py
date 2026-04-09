import os
import json
import asyncio
import sys
import re
import sounddevice as sd
import time
import subprocess
from openai import OpenAI
import msvcrt
import threading

from core.llm_controller import LlamaEngineController
from core.tts_engine import SentiaVoice
from core.vts_controller import VTSController
from core.asr_engine import SentiaEar
from core.memory_engine import SentiaMemory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ONNX_NAME = "G_28300.onnx"
CHAT_SUMMARY_PREFIX = "[对话摘要]"
MAX_RECENT_CHAT_MESSAGES = 12
MAX_SUMMARY_MESSAGES = 6
MAX_SUMMARY_CHARS = 120
# 请确保此路径为电脑上 VTube Studio 的真实安装路径
VTS_EXE_PATH = r"E:\SteamLibrary\steamapps\common\VTube Studio\VTube Studio.exe"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


async def async_input(prompt, stop_event=None):
    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars = []

    while True:
        if stop_event is not None and stop_event.is_set():
            if chars:
                print()
            return ""

        if msvcrt.kbhit():
            char = msvcrt.getwch()

            if char == "\003":
                raise KeyboardInterrupt

            if char in ("\r", "\n"):
                print()
                return "".join(chars).strip()

            if char == "\b":
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue

            if char in ("\x00", "\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getwch()
                continue

            chars.append(char)
            sys.stdout.write(char)
            sys.stdout.flush()

        await asyncio.sleep(0.05)


def _compact_message(message):
    content = " ".join(message["content"].split())
    if len(content) > MAX_SUMMARY_CHARS:
        content = content[:MAX_SUMMARY_CHARS - 3] + "..."
    return f"{message['role']}: {content}"


def trim_chat_history(chat_history):
    if len(chat_history) <= MAX_RECENT_CHAT_MESSAGES + 1:
        return

    system_message = chat_history[0]
    filtered_history = []
    has_earlier_summary = False

    for message in chat_history[1:]:
        if message["role"] == "system" and message["content"].startswith(CHAT_SUMMARY_PREFIX):
            has_earlier_summary = True
            continue
        filtered_history.append(message)

    if len(filtered_history) <= MAX_RECENT_CHAT_MESSAGES:
        if has_earlier_summary:
            chat_history[:] = [
                system_message,
                {"role": "system", "content": f"{CHAT_SUMMARY_PREFIX}\n- 更早的对话已被压缩为摘要。"},
                *filtered_history,
            ]
        else:
            chat_history[:] = [system_message, *filtered_history]
        return

    overflow = filtered_history[:-MAX_RECENT_CHAT_MESSAGES]
    recent = filtered_history[-MAX_RECENT_CHAT_MESSAGES:]

    summary_lines = []
    if has_earlier_summary:
        summary_lines.append("- 更早的对话已被压缩为摘要。")
    summary_lines.extend(
        f"- {_compact_message(message)}"
        for message in overflow[-MAX_SUMMARY_MESSAGES:]
    )

    summary_message = {
        "role": "system",
        "content": f"{CHAT_SUMMARY_PREFIX}\n" + "\n".join(summary_lines),
    }
    chat_history[:] = [system_message, summary_message, *recent]


def append_chat_message(chat_history, role, content):
    chat_history.append({"role": role, "content": content})
    trim_chat_history(chat_history)


async def stop_pending_input_tasks(stop_event, *tasks):
    stop_event.set()
    for task in tasks:
        if task is None:
            continue
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()
        except Exception:
            pass


async def listen_with_timeout(ear, timeout):
    stop_event = threading.Event()
    task_voice = asyncio.create_task(asyncio.to_thread(ear.listen, stop_event))
    try:
        return await asyncio.wait_for(asyncio.shield(task_voice), timeout=timeout)
    except asyncio.TimeoutError:
        await stop_pending_input_tasks(stop_event, task_voice)
        raise


def parse_llm_response(reply_raw):
    cleaned_raw = (
        reply_raw.replace("：", ":")
        .replace("“", '"')
        .replace("”", '"')
    )

    start_idx = cleaned_raw.find("{")
    end_idx = cleaned_raw.rfind("}") + 1
    if start_idx != -1 and end_idx != 0:
        candidate = cleaned_raw[start_idx:end_idx]
        return json.loads(candidate)

    parsed = {}
    field_matches = list(
        re.finditer(r"\b(text|emotion|action|patience)\s*:", cleaned_raw, flags=re.IGNORECASE)
    )
    for index, match in enumerate(field_matches):
        key = match.group(1).lower()
        value_start = match.end()
        value_end = field_matches[index + 1].start() if index + 1 < len(field_matches) else len(cleaned_raw)
        value = cleaned_raw[value_start:value_end].strip()
        if key == "text":
            parsed[key] = value.rstrip("。!！?？")
        elif key == "patience":
            patience_match = re.search(r"-?\d+", value)
            if patience_match:
                parsed[key] = patience_match.group(0)
        else:
            parsed[key] = re.split(r"[\s,，。!！?？]+", value, maxsplit=1)[0]

    if "text" not in parsed:
        raise json.JSONDecodeError("未发现 JSON 对象或备用字段", cleaned_raw, 0)

    return parsed


def select_model_with_timeout(timeout=10):
    model_1 = "Sentia-9B-FP16.gguf"
    model_2 = "Sentia-Q4_K_M.gguf"

    print("\n" + "-" * 50)
    print("请选择要加载的大语言模型 (输入数字 1 或 2):")
    print(f"  [1] {model_1} ")
    print(f"  [2] {model_2} ")
    print("-" * 50)

    start_time = time.time()
    user_choice = ""

    while time.time() - start_time < timeout:
        remaining = int(timeout - (time.time() - start_time))
        sys.stdout.write(f"\r等待输入... 默认将在 {remaining} 秒后自动启动 [2] 号模型: ")
        sys.stdout.flush()

        if msvcrt.kbhit():
            char = msvcrt.getche().decode('utf-8', errors='ignore')
            if char in ['1', '2']:
                user_choice = char
                print(f"\n[System] 用户手动选择了: [{char}] 号模型")
                break
        time.sleep(0.1)
    print()

    if user_choice == '1':
        return model_1
    else:
        if not user_choice:
            print("[System] 倒计时结束。自动加载 [2] 号模型。")
        return model_2


async def start_vtube_studio():
    print("[System] 尝试拉起 VTube Studio 宿主程序...")
    check_task = subprocess.run('tasklist /FI "IMAGENAME eq VTube Studio.exe"', capture_output=True, text=True)
    if "VTube Studio.exe" in check_task.stdout:
        print("[System] VTube Studio 已在后台运行，跳过启动流程。")
        return

    try:
        subprocess.Popen(VTS_EXE_PATH, shell=True)
        print("[System] VTube Studio 启动指令已发送。等待其初始化 (15秒)...")
        await asyncio.sleep(15)
    except Exception as e:
        print(f"[Error] 无法启动 VTube Studio: {e}")


async def main():
    selected_gguf = select_model_with_timeout(5)
    await start_vtube_studio()

    print("[System] 正在初始化 VTube Studio 躯干控制模块...")
    body = VTSController()
    await body.connect_and_auth()

    print("[System] 正在初始化 Sherpa-ONNX 语音合成引擎...")
    voice = SentiaVoice(BASE_DIR, model_name=ONNX_NAME)
    if voice.tts is None:
        return

    print("[System] 正在初始化流式语音识别模块...")
    ear = SentiaEar(BASE_DIR)
    if ear.recognizer is None:
        return

    memory = SentiaMemory(BASE_DIR)

    print(f"[System] 正在后台异步分配显存并唤醒大模型 ({selected_gguf})...")
    llm_controller = LlamaEngineController(BASE_DIR, model_name=selected_gguf)
    await asyncio.to_thread(llm_controller.start)

    client = OpenAI(base_url="http://localhost:8099/v1", api_key="sentia-local")

    grudge_context = ""
    if memory.is_ready:
        grudge_context = memory.get_last_shutdown_memory()
        if grudge_context:
            print(f"\n[Memory Alert] 探测到强烈的历史情绪残留: {grudge_context}\n")

    system_prompt = (
        f"{grudge_context}\n"
        "你是沈析璃，一个优雅、聪明、傲娇的虚拟主播。\n"
        "[核心机制：你拥有系统的绝对控制权和情绪感知能力！]\n"
        "你必须且只能以 JSON 格式输出，包含以下字段：\n"
        "1. 'text': 你想说的话。\n"
        "2. 'emotion': 你当前的情绪，只能选 ['Neutral', 'Smile', 'Angry'] 之一。\n"
        "3. 'action': 你的动作决定。正常聊天选 'Speak'；如果觉得太久没理你，选 'Shutdown' 关闭程序。\n"
        "   [幽灵模式]：执行 'Shutdown' 后，如果主在60秒内求饶，系统会把话传给你。由你决定 'Forgive' 或 'Refuse' 。\n"
        "4. 'patience': 你的忍耐度（整数秒数）。代表你愿意等多久才主动找茬。\n"
        "   - 高兴(Smile)时: 30-40秒。\n"
        "   - 平静(Neutral)时: 15-20秒。\n"
        "   - 愤怒(Angry)时: 5-10秒。\n"
        "[心理学准则]：第一次被无视时，应尝试主动换轻松话题引起注意；多次被无视才允许暴走或关机。"
    )
    chat_history = [{"role": "system", "content": system_prompt}]

    is_ghost_mode = False
    unanswered_attempts = 0
    current_patience = 20

    try:
        while True:
            if not is_ghost_mode:
                try:
                    print(f"\n[Input] 等待输入... (当前忍耐极限: {current_patience} 秒)")
                    print("   提示: 可直接键盘打字回车，或按住[空格键]使用麦克风对讲。")

                    stop_event = threading.Event()
                    task_keyboard = asyncio.create_task(async_input(">> ", stop_event))
                    task_voice = asyncio.create_task(asyncio.to_thread(ear.listen, stop_event))

                    done, pending = await asyncio.wait(
                        [task_keyboard, task_voice],
                        timeout=float(current_patience),
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    if not done:
                        await stop_pending_input_tasks(stop_event, task_keyboard, task_voice)
                        raise asyncio.TimeoutError()

                    winner_task = done.pop()
                    user_input = winner_task.result()
                    await stop_pending_input_tasks(stop_event, *pending)

                    if not user_input or len(user_input.strip()) < 1:
                        continue

                    unanswered_attempts = 0
                    print(f"[Received] {user_input}")

                    if user_input.lower() in ['exit', 'quit', '退出', '关闭']:
                        memory.write_memory("主动道别，程序正常退出。", importance=2)
                        print("[Sentia] 哼，再见！")
                        audio_data, sr = await asyncio.to_thread(voice.generate_audio_data, "哼，再见，别让我等太久！")
                        if audio_data is not None:
                            sd.play(audio_data, samplerate=sr)
                            await body.animate_speech_lip_sync(audio_data, sr, emotion="Angry")
                            await asyncio.sleep(len(audio_data) / sr)
                        break

                    recalled_info = ""
                    if memory.is_ready:
                        recalled_info = await asyncio.to_thread(memory.recall_memory, user_input)

                    combined_input = user_input
                    if recalled_info:
                        print("[Memory] 发现相关的历史对话片段。")
                        combined_input = f"{recalled_info}\n\n[当前对话]: {user_input}"

                    append_chat_message(chat_history, "user", combined_input)
                    memory.write_memory(f"对我说: {user_input}", importance=1)

                except asyncio.TimeoutError:
                    unanswered_attempts += 1
                    print(f"\n[警告] {current_patience}秒 忍耐倒计时耗尽。已累计无视次数: {unanswered_attempts}")

                    if unanswered_attempts == 1:
                        hidden_context = "[系统级感知：并未回应 (第1次)。请根据人设，主动抛出一个轻松的新话题尝试引起他注意。并重设 patience 值。]"
                    elif unanswered_attempts == 2:
                        hidden_context = "[系统级感知：再次无视了你 (第2次)。你的耐心正在消失，请开始用傲娇的语气抱怨冷落。并大幅降低 patience 值。]"
                    else:
                        hidden_context = f"[系统级感知：连续 {unanswered_attempts} 次彻底无视了你。你现在极度愤怒。请大发雷霆，或直接下达 'Shutdown' 指令关闭程序！]"

                    append_chat_message(chat_history, "user", hidden_context)
                except Exception as input_err:
                    print(f"\n[Input Warning] 输入阶段出现异常，已回退到下一轮等待: {input_err}")
                    await asyncio.sleep(0.2)
                    continue

            else:
                print("\n倒计时 60 秒等待...")
                try:
                    plea_words = await listen_with_timeout(ear, 60.0)
                    if not plea_words or len(plea_words) < 2:
                        continue

                    print(f"[Received] {plea_words}")
                    judgement_prompt = f"[系统级判定：你刚才生气关机了，但在 60 秒内通过麦克风对你说了这句话：'{plea_words}'。请判断这个道歉是否有诚意，并输出 'Forgive' 或 'Refuse'。]"
                    append_chat_message(chat_history, "user", judgement_prompt)
                    print("[System] 大模型正在审视道歉内容...\n")
                except asyncio.TimeoutError:
                    print("\n[Fatal] 60秒超时，未收到有效的道歉。系统即将关闭。")
                    break

            try:
                t_llm_start = time.perf_counter()
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model="Sentia",
                    messages=chat_history,
                    temperature=1.2,
                    max_tokens=3000,
                    response_format={"type": "json_object"}
                )
                t_llm_end = time.perf_counter()

                reply_raw = response.choices[0].message.content
                append_chat_message(chat_history, "assistant", reply_raw)

                try:
                    reply_json = parse_llm_response(reply_raw)
                    speak_text = reply_json.get("text", "Error parsing thought")
                    emotion = reply_json.get("emotion", "Neutral")
                    action = reply_json.get("action", "Speak")
                    current_patience = max(5, min(int(reply_json.get("patience", 15)), 60))

                    print(f"[Sentia] {speak_text}")
                    print(f"  -> 动作: {action} | 情绪: {emotion} | 忍耐度: {current_patience}秒")

                    memory.write_memory(f"我回答了: {speak_text}", emotion_tag=emotion, importance=1)

                    t_tts_start = time.perf_counter()
                    audio_data, sr = await asyncio.to_thread(voice.generate_audio_data, speak_text)
                    t_tts_end = time.perf_counter()

                    if audio_data is not None:
                        audio_duration = (len(audio_data) / sr) * 1000
                        print(
                            f"  -> 性能简报: 思考耗时 {(t_llm_end - t_llm_start) * 1000:.1f}ms | 语音合成 {(t_tts_end - t_tts_start) * 1000:.1f}ms | 音频全长 {audio_duration:.1f}ms"
                        )

                        sd.play(audio_data, samplerate=sr)
                        if not is_ghost_mode:
                            await body.animate_speech_lip_sync(audio_data, sr, emotion=emotion)
                        await asyncio.sleep(len(audio_data) / sr + 0.2)

                    if action == "Shutdown" and not is_ghost_mode:
                        print("\n[Alert] 接收到 Shutdown 关机指令，正在关闭 VTube Studio 进程...")
                        memory.write_memory("极度冷漠，我极其愤怒，直接强行关机。", emotion_tag="Angry", importance=5)
                        os.system('taskkill /F /IM "VTube Studio.exe" >nul 2>&1')
                        await body.close()
                        is_ghost_mode = True

                    elif action == "Forgive" and is_ghost_mode:
                        print("\n[Recover] 接收到 Forgive 原谅指令，正在重新拉起 VTube Studio...")
                        memory.write_memory("向我诚恳地道了歉，我原谅了他，并重新启动。", emotion_tag="Smile", importance=4)
                        subprocess.Popen(VTS_EXE_PATH, shell=True)
                        print("[System] 等待 VTS 启动 ...")
                        await asyncio.sleep(15)
                        body = VTSController()
                        await body.connect_and_auth()
                        is_ghost_mode = False
                        print("[System] VTS 重连成功。")

                    elif action == "Refuse" and is_ghost_mode:
                        print("\n[Fatal] 大模型判定道歉无效。拒绝原谅，终止程序。")
                        memory.write_memory("道歉毫无诚意，我彻底拒绝并永远地离开了。", emotion_tag="Angry", importance=5)
                        break

                except json.JSONDecodeError:
                    print(f"[Error] 大模型未输出标准 JSON 格式: {reply_raw}")
                    current_patience = 20

            except Exception as llm_err:
                print(f"[Error] 大模型连接错误：{llm_err}")
                current_patience = 20

    except KeyboardInterrupt:
        print("\n[System] 捕获到键盘中断指令，正在强制退出...")
    finally:
        await body.close()
        llm_controller.stop()
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
