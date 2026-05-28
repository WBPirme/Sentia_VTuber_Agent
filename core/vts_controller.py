import asyncio
import pyvts
import random
import math
import time
import json

from aiofiles import os


class VTSController:
    def __init__(self):
        self.plugin_info = {
            "plugin_name": "Sentia_AI_Core",
            "developer": "YourName",
            "authentication_token_path": "./vts_token.txt"
        }
        self.vts = pyvts.vts(plugin_info=self.plugin_info)
        self.is_alive = False
        self._idle_task = None
        self._reader_task = None

        self.custom_params = [
            "Sentia_AngleX", "Sentia_AngleY", "Sentia_AngleZ",
            "Sentia_EyeX", "Sentia_EyeY",
            "Sentia_EyeLOpen", "Sentia_EyeROpen",
            "Sentia_BrowLY", "Sentia_BrowRY", "Sentia_BrowLForm", "Sentia_BrowRForm",
            "Sentia_BodyX", "Sentia_BodyY", "Sentia_BodyZ",
            "Sentia_MouthOpenY", "Sentia_MouthForm"
        ]

        self.cur_head_x, self.cur_head_y, self.cur_head_z = 0.0, 0.0, 0.0
        self.cur_body_x, self.cur_body_y, self.cur_body_z = 0.0, 0.0, 0.0
        self.cur_eye_x, self.cur_eye_y = 0.0, 0.0
        self.cur_brow_y = 0.0
        self.cur_mouth_open = 0.0
        self.cur_mouth_form = 0.5

        self.focus_target_x, self.focus_target_y = 0.0, 0.0
        self.last_focus_time = time.perf_counter()
        self.blink_timer = time.perf_counter()
        self.is_blinking = False

        self.phase_x = random.uniform(0, math.pi * 2)
        self.phase_y = random.uniform(0, math.pi * 2)
        self.phase_z = random.uniform(0, math.pi * 2)
        self.phase_eye_x = random.uniform(0, math.pi * 2)
        self.phase_eye_y = random.uniform(0, math.pi * 2)

    async def connect_and_auth(self):
        print("正在连接 VTube Studio API")
        try:
            await self.vts.connect()

            await self.vts.request_authenticate_token()
            auth_response = await self.vts.request_authenticate()

            if isinstance(auth_response, dict) and "data" in auth_response:
                if auth_response["data"].get("authenticated") is False:
                    print("警告：检测到本地的 VTS Token 已过期或被撤销")
                    print("正在清理旧的通行证缓存...")

                    # 物理销毁那张过期的废纸！
                    token_path = self.plugin_info.get("authentication_token_path", "./vts_token.txt")
                    if os.path.exists(token_path):
                        os.remove(token_path)

                    print("正在重新申请授权！请立刻前往 VTube Studio 软件中，点击弹出的【允许】按钮！")

                    await self.vts.request_authenticate_token()
                    await self.vts.request_authenticate()
            print("连接成功")

            for param in self.custom_params:
                req_data = {
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "ParamInit",
                    "messageType": "ParameterCreationRequest",
                    "data": {
                        "parameterName": param,
                        "explanation": "Sentia AI Parameter",
                        "min": -30.0,
                        "max": 30.0,
                        "defaultValue": 0.0
                    }
                }
                await self.vts.request(req_data)

            self.is_alive = True
            self._reader_task = asyncio.create_task(self._blackhole_reader())
            self._idle_task = asyncio.create_task(self._procedural_soul_loop())
        except Exception as e:
            print(f"连接失败: {e}")

    async def _blackhole_reader(self):
        while self.is_alive:
            try:
                if self.vts.websocket:
                    await self.vts.websocket.recv()
                else:
                    await asyncio.sleep(0.1)
            except Exception:
                break

    # 算法
    def _math_lerp(self, a, b, t):
        return a + (b - a) * t

    def _smooth_damp(self, current, target, speed, dt):
        if dt <= 0.0: return current
        return current + (target - current) * (1.0 - math.exp(-speed * dt))

    def _organic_noise(self, t, speed_multiplier, phase_offset):
        t = t * speed_multiplier
        wave1 = math.sin(t * 0.73 + phase_offset)
        wave2 = math.sin(t * 1.37 + phase_offset * 1.3) * 0.5
        wave3 = math.sin(t * 2.11 + phase_offset * 1.7) * 0.25
        return (wave1 + wave2 + wave3) / 1.75

    # 口型
    async def animate_speech_lip_sync(self, audio_samples, sample_rate, emotion="Neutral"):
        if not self.is_alive or audio_samples is None or len(audio_samples) == 0:
            return

        fps = 60
        chunk_size = int(sample_rate / fps)
        total_chunks = len(audio_samples) // chunk_size

        start_time = time.perf_counter()

        for i in range(total_chunks):
            # 1. 提取当前音频块
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size
            chunk = audio_samples[start_idx:end_idx]

            # 2. 均方根 (RMS) 能量
            rms = math.sqrt(sum(x * x for x in chunk) / len(chunk)) if len(chunk) > 0 else 0.0

            # 3. 将 RMS 归一化放大为口型张合度 (可根据实际音量微调 3.0 这个系数)
            target_open = min(1.0, rms * 3.0)
            target_form = 0.5 + (target_open * 0.5)  # 口型形状跟随张力变化

            # 4. 赋值给 VTS 物理参数
            self.cur_mouth_open = target_open
            self.cur_mouth_form = target_form

            # 同步等待下一帧
            expected_time = (i + 1) / fps
            elapsed = time.perf_counter() - start_time
            if expected_time > elapsed:
                await asyncio.sleep(expected_time - elapsed)

        # 结束后复位口型
        self.cur_mouth_open = 0.0
        self.cur_mouth_form = 0.8


    async def _procedural_soul_loop(self):
        start_time = time.perf_counter()
        last_time = start_time
        target_fps = 60
        frame_time = 1.0 / target_fps

        while self.is_alive:
            try:
                loop_start = time.perf_counter()
                dt = loop_start - last_time
                last_time = loop_start

                t = loop_start - start_time
                current_time = loop_start

                #注意力
                if current_time - self.last_focus_time > random.uniform(1.5, 4.5):
                    fx = random.gauss(0.0, 0.5)
                    fy = random.gauss(0.0, 0.5)

                    max_radius = 1.0
                    dist = math.hypot(fx, fy)
                    if dist > max_radius:
                        fx = (fx / dist) * max_radius
                        fy = (fy / dist) * max_radius

                    self.focus_target_x = fx
                    self.focus_target_y = fy
                    self.last_focus_time = current_time

                #眼球
                eye_jitter_x = self._organic_noise(t, 3.0, self.phase_eye_x) * 0.1
                eye_jitter_y = self._organic_noise(t, 3.5, self.phase_eye_y) * 0.1

                final_tgt_eye_x = self.focus_target_x + eye_jitter_x
                final_tgt_eye_y = self.focus_target_y + eye_jitter_y

                final_eye_dist = math.hypot(final_tgt_eye_x, final_tgt_eye_y)
                if final_eye_dist > 1.0:
                    final_tgt_eye_x = (final_tgt_eye_x / final_eye_dist) * 1.0
                    final_tgt_eye_y = (final_tgt_eye_y / final_eye_dist) * 1.0

                self.cur_eye_x = self._smooth_damp(self.cur_eye_x, final_tgt_eye_x, 35.0, dt)
                self.cur_eye_y = self._smooth_damp(self.cur_eye_y, final_tgt_eye_y, 35.0, dt)

                #头部
                head_breathing_noise_x = self._organic_noise(t, 0.8, self.phase_x) * 5.0
                head_breathing_noise_y = self._organic_noise(t, 0.6, self.phase_y) * 3.0

                tgt_head_x = (self.cur_eye_x * 25.0) + head_breathing_noise_x
                tgt_head_y = (self.cur_eye_y * 18.0) + head_breathing_noise_y
                tgt_head_z = (self.cur_eye_x * 10.0) + self._organic_noise(t, 0.5, self.phase_z) * 6.0

                self.cur_head_x = self._smooth_damp(self.cur_head_x, tgt_head_x, 8.0, dt)
                self.cur_head_y = self._smooth_damp(self.cur_head_y, tgt_head_y, 8.0, dt)
                self.cur_head_z = self._smooth_damp(self.cur_head_z, tgt_head_z, 8.0, dt)

                #身体
                breathing_y = math.sin(t * 2.5 + self.phase_y) * 1.5
                tgt_body_x = self.cur_head_x * 0.4
                tgt_body_y = self.cur_head_y * 0.3 + breathing_y
                tgt_body_z = self.cur_head_z * 0.3

                self.cur_body_x = self._smooth_damp(self.cur_body_x, tgt_body_x, 4.0, dt)
                self.cur_body_y = self._smooth_damp(self.cur_body_y, tgt_body_y, 4.0, dt)
                self.cur_body_z = self._smooth_damp(self.cur_body_z, tgt_body_z, 4.0, dt)

                #眨眼
                eye_open = 1.0 + self._organic_noise(t, 5.0, self.phase_y) * 0.05
                if not self.is_blinking and current_time - self.blink_timer > random.uniform(2.0, 4.5):
                    self.is_blinking = True
                    self.blink_timer = current_time
                if self.is_blinking:
                    blink_progress = current_time - self.blink_timer
                    if blink_progress < 0.08:
                        eye_open = self._math_lerp(1.0, 0.0, blink_progress / 0.08)
                    elif blink_progress < 0.23:
                        eye_open = self._math_lerp(0.0, 1.0, (blink_progress - 0.08) / 0.15)
                    else:
                        self.is_blinking = False
                        eye_open = 1.0
                        if random.random() < 0.2:
                            self.blink_timer = current_time - random.uniform(0.3, 0.8)
                eye_open = max(0.0, min(eye_open, 1.0))

                # 眉毛
                tgt_brow_y = (self.cur_head_y * 0.08) + ((eye_open - 0.8) * 0.5)
                tgt_brow_y += self._organic_noise(t, 1.2, self.phase_z) * 0.1
                tgt_brow_y = max(-1.0, min(tgt_brow_y, 1.0))
                self.cur_brow_y = self._smooth_damp(self.cur_brow_y, tgt_brow_y, 15.0, dt)

                #打包发送
                inject_data = {
                    "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                    "requestID": "InjectParams", "messageType": "InjectParameterDataRequest",
                    "data": {
                        "faceFound": True,
                        "parameterValues": [
                            {"id": "Sentia_AngleX", "value": self.cur_head_x},
                            {"id": "Sentia_AngleY", "value": self.cur_head_y},
                            {"id": "Sentia_AngleZ", "value": self.cur_head_z},
                            {"id": "Sentia_BodyX", "value": self.cur_body_x},
                            {"id": "Sentia_BodyY", "value": self.cur_body_y},
                            {"id": "Sentia_EyeX", "value": self.cur_eye_x},
                            {"id": "Sentia_EyeY", "value": self.cur_eye_y},
                            {"id": "Sentia_EyeLOpen", "value": eye_open},
                            {"id": "Sentia_EyeROpen", "value": eye_open},
                            {"id": "Sentia_MouthOpenY", "value": self.cur_mouth_open},
                            {"id": "Sentia_MouthForm", "value": self.cur_mouth_form}
                        ]
                    }
                }
                if self.vts.websocket:
                    await self.vts.websocket.send(json.dumps(inject_data))

                elapsed = time.perf_counter() - loop_start
                await asyncio.sleep(max(0.001, frame_time - elapsed))

            except Exception as e:
                await asyncio.sleep(1)

    async def close(self):
        self.is_alive = False
        if self._idle_task: self._idle_task.cancel()
        await self.vts.close()