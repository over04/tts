"""TTS API 服务 - OpenAI TTS 兼容端点"""

import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from tts import AzureTTSProvider, VolcengineTTSProvider, TTSRequest, TTSProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

providers: dict[str, TTSProvider] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    providers["azure"] = AzureTTSProvider()
    providers["volcengine"] = VolcengineTTSProvider()
    logger.info("TTS 服务已启动")
    yield
    providers.clear()
    logger.info("TTS 服务已关闭")


app = FastAPI(
    title="TTS API",
    description="OpenAI TTS 兼容接口",
    version="1.0.0",
    lifespan=lifespan,
)


class ResponseFormat(str, Enum):
    MP3 = "mp3"
    OPUS = "opus"
    AAC = "aac"
    FLAC = "flac"
    WAV = "wav"
    PCM = "pcm"


class TTSSpeechRequest(BaseModel):
    """OpenAI TTS 请求格式"""
    model: str = Field(default="azure", description="TTS 模型/提供者 (azure, volcengine)")
    input: str = Field(..., description="要合成的文本", max_length=4096)
    voice: str = Field(default="zh-CN-XiaoxiaoMultilingualNeural", description="语音名称")
    response_format: ResponseFormat = Field(default=ResponseFormat.MP3, description="输出格式")
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="语速 (0.25-4.0)")


class VoiceItem(BaseModel):
    """语音信息"""
    id: str
    name: str
    language: str
    gender: str | None
    provider: str


class VoicesResponse(BaseModel):
    """语音列表响应"""
    voices: list[VoiceItem]


def get_content_type(response_format: ResponseFormat) -> str:
    """获取响应内容类型"""
    content_types = {
        ResponseFormat.MP3: "audio/mpeg",
        ResponseFormat.OPUS: "audio/opus",
        ResponseFormat.AAC: "audio/aac",
        ResponseFormat.FLAC: "audio/flac",
        ResponseFormat.WAV: "audio/wav",
        ResponseFormat.PCM: "audio/pcm",
    }
    return content_types.get(response_format, "audio/mpeg")


async def _synthesize_speech(
    model: str,
    input_text: str,
    voice: str,
    response_format: ResponseFormat,
    speed: float,
) -> StreamingResponse:
    """合成语音的公共逻辑"""
    provider = providers.get(model)
    if not provider:
        raise HTTPException(status_code=400, detail=f"不支持的模型: {model}")

    tts_request = TTSRequest(
        text=input_text,
        voice=voice,
        speed=speed,
        response_format=response_format.value,
    )

    content_type = get_content_type(response_format)

    return StreamingResponse(
        provider.synthesize_stream(tts_request),
        media_type=content_type,
        headers={"Transfer-Encoding": "chunked"},
    )


@app.post("/v1/audio/speech", response_class=StreamingResponse)
async def create_speech_post(request: TTSSpeechRequest):
    """生成语音 (POST 请求)"""
    return await _synthesize_speech(
        model=request.model,
        input_text=request.input,
        voice=request.voice,
        response_format=request.response_format,
        speed=request.speed,
    )


@app.get("/v1/audio/speech", response_class=StreamingResponse)
async def create_speech_get(
    input: str,
    model: str = "azure",
    voice_id: str = "zh-CN-XiaoxiaoMultilingualNeural",
    response_format: ResponseFormat = ResponseFormat.MP3,
    speed: float = 1.0,
):
    """生成语音 (GET 请求)"""
    return await _synthesize_speech(
        model=model,
        input_text=input,
        voice=voice_id,
        response_format=response_format,
        speed=speed,
    )


@app.get("/v1/audio/voices", response_model=VoicesResponse)
async def list_voices(provider: str | None = None):
    """
    获取可用语音列表
    
    Args:
        provider: 可选，指定提供者过滤 (azure, volcengine)
    """
    all_voices = []

    if provider:
        p = providers.get(provider)
        if not p:
            raise HTTPException(status_code=400, detail=f"不支持的提供者: {provider}")
        voices = await p.get_voices()
        all_voices.extend(voices)
    else:
        for p in providers.values():
            voices = await p.get_voices()
            all_voices.extend(voices)

    return VoicesResponse(
        voices=[
            VoiceItem(
                id=v.id,
                name=v.name,
                language=v.language,
                gender=v.gender,
                provider=v.provider,
            )
            for v in all_voices
        ]
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "providers": list(providers.keys())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)