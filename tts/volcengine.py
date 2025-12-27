"""Volcengine TTS Provider 实现"""

import base64
import logging
from typing import AsyncIterator

import httpx

from tts.base import TTSProvider, TTSRequest, VoiceInfo

logger = logging.getLogger(__name__)

LANG_DETECT_URL = "https://translate.volcengine.com/web/langdetect/v1/"
TTS_URL = "https://translate.volcengine.com/crx/tts/v1/"

DEFAULT_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Origin": "chrome-extension://klgfhbiooeogdfodpopgppeadghjjemk",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "none",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}

VOLCENGINE_VOICES = [
    {"id": "zh_female_story", "name": "少儿故事 中英混", "language": "zh-CN", "gender": "Female"},
    {"id": "zh_female_qingxin", "name": "清新女声 中英混", "language": "zh-CN", "gender": "Female"},
    {"id": "zh_female_zhubo", "name": "女主播 中英混", "language": "zh-CN", "gender": "Female"},
    {"id": "zh_male_zhubo", "name": "男主播 中英混", "language": "zh-CN", "gender": "Male"},
    {"id": "zh_male_xiaoming", "name": "影视男解说 中英混", "language": "zh-CN", "gender": "Male"},
    {"id": "zh_female_sichuan", "name": "四川女声 川英混", "language": "zh-CN", "gender": "Female"},
    {"id": "zh_male_rap", "name": "嘻哈男歌手 中英混", "language": "zh-CN", "gender": "Male"},
    {"id": "en_female_sarah", "name": "澳英女声 澳洲英语", "language": "en-AU", "gender": "Female"},
    {"id": "jp_male_satoshi", "name": "活力男青年 日语", "language": "ja-JP", "gender": "Male"},
    {"id": "jp_female_hana", "name": "温柔女声 日语", "language": "ja-JP", "gender": "Female"},
]

DEFAULT_VOICE = "zh_female_qingxin"


class VolcengineTTSProvider(TTSProvider):
    """火山引擎 TTS 服务提供者"""

    @property
    def provider_name(self) -> str:
        return "volcengine"

    def __init__(self) -> None:
        super().__init__()

    async def _detect_language(self, text: str) -> str | None:
        """检测文本语言"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    LANG_DETECT_URL,
                    headers=DEFAULT_HEADERS,
                    json={"text": text},
                )
                return response.json().get("language")
        except Exception:
            return None

    async def synthesize(self, request: TTSRequest) -> bytes:
        """合成语音（完整返回）"""
        language = await self._detect_language(request.text)
        voice = request.voice or DEFAULT_VOICE
        json_data = {"text": request.text, "speaker": voice}
        if language:
            json_data["language"] = language

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TTS_URL, headers=DEFAULT_HEADERS, json=json_data)
            response.raise_for_status()

        resp = response.json()
        audio = resp.get("audio")
        if not audio:
            logger.error(f"火山语音响应: {resp}")
            raise ValueError(f"火山语音服务 {voice} 生成失败: {resp.get('message', '未知错误')}")

        audio_data = audio.get("data")
        if not audio_data:
            logger.error(f"火山语音响应: {resp}")
            raise ValueError(f"火山语音服务 {voice} 数据生成失败")

        return base64.b64decode(audio_data)

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """流式合成语音（火山引擎不支持真正的流式，模拟分块返回）"""
        audio_data = await self.synthesize(request)
        chunk_size = 4096
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i : i + chunk_size]

    async def _fetch_voices(self) -> list[VoiceInfo]:
        """获取可用语音列表"""
        return [
            VoiceInfo(
                id=v["id"],
                name=v["name"],
                language=v["language"],
                gender=v["gender"],
                provider=self.provider_name,
            )
            for v in VOLCENGINE_VOICES
        ]