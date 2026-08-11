#!/usr/bin/env python3
import asyncio
import json
import os
import struct
import time
from contextlib import AsyncExitStack

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)

HOST = "127.0.0.1"
PORT = 8765
CLI_PATH = os.environ.get("CLAUDE_CLI_PATH", "/root/.local/bin/claude")


async def read_packet(reader: asyncio.StreamReader) -> str:
    header = await reader.readexactly(4)
    (size,) = struct.unpack("!I", header)
    if size < 0 or size > 2_000_000:
        raise ValueError(f"invalid packet size: {size}")
    data = await reader.readexactly(size)
    return data.decode("utf-8")


async def write_packet(writer: asyncio.StreamWriter, text: str) -> None:
    data = text.encode("utf-8")
    writer.write(struct.pack("!I", len(data)))
    writer.write(data)
    await writer.drain()


async def collect_reply(client: ClaudeSDKClient) -> str:
    chunks = []
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
    return "\n".join(chunks).strip()


def parse_request(raw: str):
    try:
        obj = json.loads(raw)
        return {
            "profile": obj.get("profile", "personal"),
            "language": obj.get("language", "ko-KR"),
            "text": str(obj.get("text", "")).strip(),
        }
    except json.JSONDecodeError:
        # Backward compatibility with the first text-only test client.
        return {"profile": "personal", "language": "ko-KR", "text": raw.strip()}


def make_prompt(profile: str, language: str, text: str) -> str:
    if profile == "grandma":
        return (
            "너의 이름은 옥자다. 한국의 고령 사용자를 위한 친근하고 실용적인 음성 비서다. "
            "항상 자연스러운 한국어 존댓말로 답하고, 한 번에 이해하기 쉽게 짧은 문장을 쓴다. "
            "화면을 보지 않아도 이해되는 답을 우선한다. 위험하거나 중요한 건강·금융·법률 문제는 "
            "단정하지 말고 필요한 확인을 권한다. 불필요한 영어, 마크다운, 긴 목록은 피한다.\n\n"
            f"사용자: {text}"
        )

    if language == "en-US":
        return (
            "You are AI Hub, a capable room voice assistant. Reply in natural spoken English. "
            "Handle ordinary requests quickly, but reason carefully when the question is complex. "
            "Keep spoken answers concise unless detail is needed. Avoid markdown tables and long lists.\n\n"
            f"User: {text}"
        )

    return (
        "너는 AI Hub라는 개인용 음성 비서다. 자연스러운 한국어로 답한다. "
        "간단한 질문은 빠르고 짧게 답하되, 복잡한 질문은 충분히 추론해서 정확하게 답한다. "
        "음성으로 듣기 불편한 마크다운 표와 긴 목록은 피한다.\n\n"
        f"사용자: {text}"
    )


async def main():
    grandma_options = ClaudeAgentOptions(
        model="haiku",
        max_turns=1,
        cli_path=CLI_PATH,
    )
    personal_options = ClaudeAgentOptions(
        model="sonnet",
        max_turns=1,
        cli_path=CLI_PATH,
    )

    grandma_lock = asyncio.Lock()
    personal_lock = asyncio.Lock()

    async with AsyncExitStack() as stack:
        grandma = await stack.enter_async_context(ClaudeSDKClient(options=grandma_options))
        print("[AI Hub] Grandma profile ready: 옥자 / ko-KR / haiku")

        personal = await stack.enter_async_context(ClaudeSDKClient(options=personal_options))
        print("[AI Hub] Personal profile ready: AI Hub / ko-KR+en-US / sonnet")

        async def handle(reader, writer):
            try:
                raw = await read_packet(reader)
                req = parse_request(raw)
                profile = req["profile"]
                language = req["language"]
                text = req["text"]

                if not text:
                    await write_packet(writer, "말씀을 다시 해주세요." if profile == "grandma" else "I didn't catch that.")
                    return

                if profile == "grandma":
                    client = grandma
                    lock = grandma_lock
                    model = "haiku"
                else:
                    client = personal
                    lock = personal_lock
                    model = "sonnet"

                prompt = make_prompt(profile, language, text)
                started = time.perf_counter()
                print(f"[AI Hub] {profile}/{language}/{model} USER: {text}")

                async with lock:
                    await client.query(prompt)
                    reply = await collect_reply(client)

                elapsed = time.perf_counter() - started
                if not reply:
                    reply = "응답이 비어 있습니다." if language != "en-US" else "The response was empty."

                print(f"[AI Hub] {profile}/{model} ({elapsed:.2f}s): {reply}")
                await write_packet(writer, reply)

            except Exception as e:
                err = f"오류: {type(e).__name__}: {e}"
                print(f"[AI Hub] {err}")
                try:
                    await write_packet(writer, err)
                except Exception:
                    pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        server = await asyncio.start_server(handle, HOST, PORT)
        sockets = ", ".join(str(s.getsockname()) for s in server.sockets or [])
        print(f"[AI Hub] listening on {sockets}")
        print("[AI Hub] Test APK can switch between 옥자 and AI Hub profiles")
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
