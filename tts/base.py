"""TTS Provider 抽象基类定义"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import AsyncIterator

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_TTL = 86400 * 7  # 缓存有效期：7天


@dataclass
class TTSRequest:
    """TTS 请求参数"""
    text: str
    voice: str
    speed: float = 1.0
    response_format: str = "mp3"


@dataclass
class VoiceInfo:
    """语音信息"""
    id: str
    name: str
    language: str
    gender: str | None = None
    provider: str = ""


class VoiceCache:
    """语音列表缓存管理器"""

    def __init__(self, provider_name: str, ttl: int = CACHE_TTL) -> None:
        self._provider = provider_name
        self._ttl = ttl
        self._cache_file = CACHE_DIR / f"{provider_name}_voices.json"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get(self) -> list[VoiceInfo] | None:
        """从缓存读取语音列表"""
        if not self._cache_file.exists():
            return None

        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            if time.time() - data.get("timestamp", 0) > self._ttl:
                logger.info(f"[{self._provider}] 缓存已过期")
                return None
            return [VoiceInfo(**v) for v in data.get("voices", [])]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[{self._provider}] 缓存读取失败: {e}")
            return None

    def set(self, voices: list[VoiceInfo]) -> None:
        """写入语音列表缓存"""
        data = {
            "timestamp": time.time(),
            "voices": [asdict(v) for v in voices],
        }
        self._cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[{self._provider}] 已缓存 {len(voices)} 个语音")

    def clear(self) -> None:
        """清除缓存"""
        if self._cache_file.exists():
            self._cache_file.unlink()


class TTSProvider(ABC):
    """TTS 服务提供者抽象基类"""

    def __init__(self) -> None:
        self._voice_cache = VoiceCache(self.provider_name)
        self._voices: list[VoiceInfo] | None = None

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """返回提供者名称"""
        ...

    @abstractmethod
    async def synthesize(self, request: TTSRequest) -> bytes:
        """
        合成语音（完整返回）
        
        Args:
            request: TTS请求参数
            
        Returns:
            音频数据字节
        """
        ...

    @abstractmethod
    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """
        流式合成语音
        
        Args:
            request: TTS请求参数
            
        Yields:
            音频数据块
        """
        ...

    @abstractmethod
    async def _fetch_voices(self) -> list[VoiceInfo]:
        """
        从远程获取语音列表（子类实现）
        
        Returns:
            语音信息列表
        """
        ...

    async def get_voices(self, force_refresh: bool = False) -> list[VoiceInfo]:
        """
        获取可用语音列表（带缓存）
        
        Args:
            force_refresh: 是否强制刷新缓存
            
        Returns:
            语音信息列表
        """
        if not force_refresh and self._voices:
            return self._voices

        if not force_refresh:
            cached = self._voice_cache.get()
            if cached:
                self._voices = cached
                return cached

        self._voices = await self._fetch_voices()
        self._voice_cache.set(self._voices)
        return self._voices

    def supports_voice(self, voice_id: str) -> bool:
        """检查是否支持指定语音"""
        return True