"""TTS 模块"""

from tts.base import TTSProvider, TTSRequest, VoiceInfo
from tts.azure import AzureTTSProvider
from tts.volcengine import VolcengineTTSProvider

__all__ = [
    "TTSProvider",
    "TTSRequest", 
    "VoiceInfo",
    "AzureTTSProvider",
    "VolcengineTTSProvider",
]