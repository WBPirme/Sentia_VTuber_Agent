import asyncio
import websockets
import json
import time
import os

# VTube Studio 本地 API 地址
VTS_WS_URL = "ws://localhost:8001"
TOKEN_FILE = "vts_token.txt"
MOCAP_FILE = "core/my_soul.json"

# 我们要录制的核心面捕参数（避免录制物理参数导致回放时发生冲突）
TARGET_PARAMS = [
    "ParamAngleX", "ParamAngleY", "ParamAngleZ",  # 头部旋转
    "ParamEyeLOpen", "ParamEyeROpen",  # 眼睛开合
    "ParamEyeBallX", "ParamEyeBallY",  # 眼球位置
    "ParamBrowLY", "ParamBrowRY", "ParamBrowLForm", "ParamBrowRForm",  # 眉毛
    "ParamBodyAngleX", "ParamBodyAngleY", "ParamBodyAngleZ"  # 身体旋转
]


class VTSMocapEngine:
    def __init__(self):
        self.ws = None
        self.auth_token = None

    async def connect(self):
        """连接 VTS 并完成鉴权"""
        print("🔄 正在连接 VTube Studio...")
        self.ws = await websockets.connect(VTS_WS_URL, max_size=None, ping_interval=None)
        await self.authenticate()

    async def send_request(self, message_type, data=None):
        """发送标准 VTS 请求并等待响应"""
        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "MocapEngine",
            "messageType": message_type,
        }
        if data:
            request["data"] = data

        await self.ws.send(json.dumps(request))
        response = await self.ws.recv()
        return json.loads(response)

    async def authenticate(self):
        """VTS 插件鉴权流程"""
        # 1. 尝试读取本地 Token
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                self.auth_token = f.read().strip()

        # 2. 如果没有 Token，向 VTS 申请一个（此时 VTS 软件内会弹出授权窗口）
        if not self.auth_token:
            print("⚠️ 首次运行，请在 VTube Studio 软件内点击【允许】！")
            auth_req_data = {
                "pluginName": "SoulCatcher",
                "pluginDeveloper": "MyMocapEngine"
            }
            res = await self.send_request("AuthenticationTokenRequest", auth_req_data)
            self.auth_token = res.get("data", {}).get("authenticationToken")

            if self.auth_token:
                with open(TOKEN_FILE, "w") as f:
                    f.write(self.auth_token)
                print("✅ 授权成功！Token 已保存。")
            else:
                raise Exception("❌ 授权失败或被拒绝！")

        # 3. 使用 Token 登录
        login_data = {
            "pluginName": "SoulCatcher",
            "pluginDeveloper": "MyMocapEngine",
            "authenticationToken": self.auth_token
        }
        res = await self.send_request("AuthenticationRequest", login_data)
        if res.get("data", {}).get("authenticated"):
            print("✅ 成功连接到 VTube Studio！\n")
        else:
            raise Exception("❌ Token 无效，请删除 vts_token.txt 重试。")

    async def record_mocap(self, duration=10.0):
        """🎬 录像机：高频抓取参数"""
        print(f"🔴 开始录制你的面捕！倒计时 3 秒后开始...")
        await asyncio.sleep(3)
        print(f"🎬 [录制中] 请尽情表演！(时长: {duration}秒)")

        start_time = time.time()
        recorded_data = []

        while time.time() - start_time < duration:
            current_time = time.time() - start_time

            try:
                # 发送请求获取当前所有参数
                res = await self.send_request("Live2DParameterListRequest")
                all_params = res.get("data", {}).get("parameters", [])

                frame_data = {"time": current_time, "params": {}}

                # 过滤出我们需要录制的参数
                for param in all_params:
                    if param["name"] in TARGET_PARAMS:
                        frame_data["params"][param["name"]] = param["value"]

                recorded_data.append(frame_data)

            except websockets.exceptions.ConnectionClosedError:
                print("\n⚠️ VTS 觉得你请求太快，强行断开了连接！正在保存已录制的数据...")
                break  # 发生断连时跳出循环，去执行后面的保存代码

            # 【修改这里】将 0.03 改为 0.06 (约 15-16 FPS)，给 VTS 喘息的时间
            await asyncio.sleep(0.06)

        # 保存到 JSON
        with open(MOCAP_FILE, 'w', encoding='utf-8') as f:
            json.dump(recorded_data, f, indent=4)

        print(f"⏹️ [录制完成] 共抓取 {len(recorded_data)} 帧，已保存至 {MOCAP_FILE}！\n")

    async def play_mocap(self):
        """▶️ 放像机：批量注入参数回放"""
        if not os.path.exists(MOCAP_FILE):
            print("❌ 找不到动捕数据文件，请先录制！")
            return

        with open(MOCAP_FILE, 'r', encoding='utf-8') as f:
            mocap_data = json.load(f)

        print("▶️ [回放中] 正在将你的灵魂注入皮套...")
        print("⚠️ 提示：回放期间，请尽量保持头部离开摄像头范围，以免真实面捕与回放数据打架！")

        start_time = time.time()

        for frame in mocap_data:
            target_time = start_time + frame["time"]
            current_time = time.time()

            # 对齐时间轴
            if target_time > current_time:
                await asyncio.sleep(target_time - current_time)

            # 将字典转换成 VTS 注入请求需要的格式
            param_values = []
            for name, value in frame["params"].items():
                param_values.append({"id": name, "value": value})

            inject_data = {
                "faceFound": False,  # 告诉 VTS 覆盖掉摄像头的面捕
                "mode": "set",
                "parameterValues": param_values
            }

            # 这里的发送不等待 recv，直接异步发包，保证极度流畅
            request = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "InjectParams",
                "messageType": "InjectParameterDataRequest",
                "data": inject_data
            }
            await self.ws.send(json.dumps(request))

        print("✅ [回放结束]！")


async def main():
    engine = VTSMocapEngine()
    await engine.connect()

    while True:
        print("========================")
        print("1. 🔴 录制动捕 (10秒)")
        print("2. ▶️ 回放动捕")
        print("3. ❌ 退出")
        choice = input("请选择操作 (1/2/3): ")

        if choice == '1':
            # 可以自行修改录制时长
            await engine.record_mocap(duration=10.0)
        elif choice == '2':
            await engine.play_mocap()
        elif choice == '3':
            break
        else:
            print("无效输入！")


if __name__ == "__main__":
    asyncio.run(main())