"""Azure TTS Provider 实现"""

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, UTC
from typing import AsyncIterator
from urllib.parse import quote

import httpx

from tts.base import TTSProvider, TTSRequest, VoiceInfo

logger = logging.getLogger(__name__)

ENDPOINT_URL = "https://dev.microsofttranslator.com/apps/endpoint?api-version=1.0"
VOICES_LIST_URL = "https://eastus.api.speech.microsoft.com/cognitiveservices/voices/list"
USER_AGENT = "okhttp/4.5.0"
CLIENT_VERSION = "4.0.530a 5fe1dc6c"
USER_ID = "0f04d16a175c411e"
HOME_GEOGRAPHIC_REGION = "zh-Hans-CN"
CLIENT_TRACE_ID = "aab069b9-70a7-4844-a734-96cd78d94be9"
VOICE_DECODE_KEY = "oik6PdDdMnOXemTbwvMn9de/h9lFnfBaCWbGMMZqqoSaQaqUOqjVGm5NqsmjcBI1x+sS9ugjB55HEJWRiFXYFw=="
DEFAULT_VOICE_NAME = "zh-CN-XiaoxiaoMultilingualNeural"
DEFAULT_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
DEFAULT_STYLE = "general"


def _sign(url_str: str) -> str:
    """生成请求签名"""
    u = url_str.split("://")[1]
    encoded_url = quote(u, safe="")
    uuid_str = str(uuid.uuid4()).replace("-", "")
    formatted_date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S").lower() + "gmt"
    bytes_to_sign = f"MSTranslatorAndroidApp{encoded_url}{formatted_date}{uuid_str}".lower().encode("utf-8")

    decode = base64.b64decode(VOICE_DECODE_KEY)
    hmac_sha256 = hmac.new(decode, bytes_to_sign, hashlib.sha256)
    secret_key = hmac_sha256.digest()
    sign_base64 = base64.b64encode(secret_key).decode()

    return f"MSTranslatorAndroidApp::{sign_base64}::{formatted_date}::{uuid_str}"


def _build_ssml(text: str, voice_name: str, rate: str, pitch: str, style: str) -> str:
    """构建 SSML"""
    return f"""<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" version="1.0" xml:lang="zh-CN">
<voice name="{voice_name}">
    <mstts:express-as style="{style}" styledegree="1.0" role="default">
        <prosody rate="{rate}%" pitch="{pitch}%">
            {text}
        </prosody>
    </mstts:express-as>
</voice>
</speak>"""


class AzureTTSProvider(TTSProvider):
    """Azure TTS 服务提供者"""

    @property
    def provider_name(self) -> str:
        return "azure"

    def __init__(self) -> None:
        super().__init__()
        self._endpoint: dict | None = None
        self._expired_at: int | None = None

    async def _get_endpoint(self) -> dict:
        """获取 TTS 端点"""
        current_time = int(time.time())
        if self._expired_at and current_time < self._expired_at - 60:
            return self._endpoint

        signature = _sign(ENDPOINT_URL)
        headers = {
            "Accept-Language": "zh-Hans",
            "X-ClientVersion": CLIENT_VERSION,
            "X-UserId": USER_ID,
            "X-HomeGeographicRegion": HOME_GEOGRAPHIC_REGION,
            "X-ClientTraceId": CLIENT_TRACE_ID,
            "X-MT-Signature": signature,
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": "0",
            "Accept-Encoding": "gzip",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(ENDPOINT_URL, headers=headers)
            response.raise_for_status()
            self._endpoint = response.json()

        jwt = self._endpoint["t"].split(".")[1]
        padding = 4 - len(jwt) % 4
        if padding != 4:
            jwt += "=" * padding
        decoded_jwt = json.loads(base64.b64decode(jwt).decode("utf-8"))
        self._expired_at = decoded_jwt["exp"]

        return self._endpoint

    async def synthesize(self, request: TTSRequest) -> bytes:
        """合成语音（完整返回）"""
        endpoint = await self._get_endpoint()
        voice_name = request.voice or DEFAULT_VOICE_NAME
        rate = str(int((request.speed - 1) * 100))
        pitch = "0"
        output_format = self._get_output_format(request.response_format)

        url = f"https://{endpoint['r']}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Authorization": endpoint["t"],
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
        }
        ssml = _build_ssml(request.text, voice_name, rate, pitch, DEFAULT_STYLE)

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, content=ssml.encode())
            response.raise_for_status()
            return response.content

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """流式合成语音"""
        endpoint = await self._get_endpoint()
        voice_name = request.voice or DEFAULT_VOICE_NAME
        rate = str(int((request.speed - 1) * 100))
        pitch = "0"
        output_format = self._get_output_format(request.response_format)

        url = f"https://{endpoint['r']}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Authorization": endpoint["t"],
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
        }
        ssml = _build_ssml(request.text, voice_name, rate, pitch, DEFAULT_STYLE)

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, content=ssml.encode()) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    yield chunk

    async def _fetch_voices(self) -> list[VoiceInfo]:
        """从远程获取语音列表"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Ms-Useragent": "SpeechStudio/2021.05.001",
            "Content-Type": "application/json",
            "Origin": "https://azure.microsoft.com",
            "Referer": "https://azure.microsoft.com",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(VOICES_LIST_URL, headers=headers)
            response.raise_for_status()
            data = response.json()

        return [
            VoiceInfo(
                id=v["ShortName"],
                name=v["DisplayName"],
                language=v["Locale"],
                gender=v.get("Gender"),
                provider=self.provider_name,
            )
            for v in data
        ]

    def _get_output_format(self, response_format: str) -> str:
        """转换输出格式"""
        format_map = {
            "mp3": "audio-24khz-48kbitrate-mono-mp3",
            "opus": "ogg-24khz-16bit-mono-opus",
            "aac": "audio-24khz-96kbitrate-mono-mp3",
            "flac": "audio-24khz-48kbitrate-mono-mp3",
            "wav": "riff-24khz-16bit-mono-pcm",
            "pcm": "raw-24khz-16bit-mono-pcm",
        }
        return format_map.get(response_format, DEFAULT_OUTPUT_FORMAT)