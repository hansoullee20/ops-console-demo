#!/usr/bin/env python3
"""Okja localhost voice bridge backed by ChatGPT-authenticated Codex CLI.

This is an alternate backend to aihub_bridge.py. The Android packet/event
contract and local intent/confirmation path stay identical; only ordinary
assistant queries are delegated to `codex exec`.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import time
from collections import deque

from okja_event_contract import assistant_failure, assistant_response, parse_transcript_request
from okja_intent_confirmation import VoiceIntentSession

HOST = "127.0.0.1"
PORT = 8765
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
CODEX_TIMEOUT_SECONDS = float(os.environ.get("OKJA_CODEX_TIMEOUT_SECONDS", "90"))
HISTORY_IDLE_RESET_SECONDS = float(os.environ.get("OKJA_HISTORY_IDLE_RESET_SECONDS", "45"))
HISTORY_TURNS = 6


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


def parse_request(raw: str):
    return parse_transcript_request(json.loads(raw))


def make_prompt(profile: str, language: str, text: str, history: list[tuple[str, str]]) -> str:
    if profile == "grandma":
        instructions = (
            "너의 이름은 옥자다. 한국의 고령 사용자를 위한 친근하고 실용적인 음성 비서다. "
            "항상 자연스러운 한국어 존댓말로 답하고 한 번에 이해하기 쉽게 짧은 문장을 쓴다. "
            "화면을 보지 않아도 이해되는 답을 우선한다. 위험하거나 중요한 건강·금융·법률 문제는 "
            "단정하지 말고 필요한 확인을 권한다. 불필요한 영어, 마크다운, 긴 목록은 피한다. "
            "음성으로 읽기 좋은 짧은 답만 출력한다."
        )
    elif language == "en-US":
        instructions = (
            "You are Okja, a capable room voice assistant. Reply in natural spoken English. "
            "Handle ordinary requests quickly and keep spoken answers concise unless detail is needed. "
            "Use the recent conversation only when it helps resolve follow-up references. "
            "Avoid markdown tables, headings, and long lists. Output only the answer to speak."
        )
    else:
        instructions = (
            "너는 옥자라는 개인용 음성 비서다. 자연스러운 한국어로 답한다. "
            "간단한 질문은 빠르고 짧게 답하고 복잡한 질문은 필요한 만큼 정확하게 답한다. "
            "최근 대화는 후속 질문의 생략된 맥락을 이해하는 데 필요한 경우에만 사용한다. "
            "마크다운 표, 제목, 긴 목록은 피하고 음성으로 읽기 좋은 답만 출력한다."
        )

    if history:
        label_user = "User" if language == "en-US" else "사용자"
        label_assistant = "Okja" if language == "en-US" else "옥자"
        lines = []
        for role, content in history:
            lines.append(f"{label_user if role == 'user' else label_assistant}: {content}")
        context = "\n".join(lines)
        return f"{instructions}\n\nRecent conversation:\n{context}\n\n{label_user}: {text}"

    return f"{instructions}\n\n{'User' if language == 'en-US' else '사용자'}: {text}"


def _action_label(target: str, action: str, language: str) -> str:
    if language == "en-US":
        labels = {
            ("tv", "power_on"): "turn the TV on",
            ("tv", "power_off"): "turn the TV off",
            ("ac", "power_on"): "turn the air conditioner on",
            ("ac", "power_off"): "turn the air conditioner off",
            ("phone_finder", "ring"): "ring your phone",
        }
    else:
        labels = {
            ("tv", "power_on"): "TV를 켜기",
            ("tv", "power_off"): "TV를 끄기",
            ("ac", "power_on"): "에어컨을 켜기",
            ("ac", "power_off"): "에어컨을 끄기",
            ("phone_finder", "ring"): "휴대폰을 찾기",
        }
    return labels[(target, action)]


def intent_reply(kind: str, target: str | None, action: str | None, language: str) -> str:
    if kind == "confirmation_requested":
        label = _action_label(target, action, language)
        if language == "en-US":
            return f"Should I {label}? Say confirm or cancel."
        return f"{label}를 진행할까요? '확인' 또는 '취소'라고 말씀해주세요."
    if kind == "confirmation_accepted":
        label = _action_label(target, action, language)
        if language == "en-US":
            return f"Confirmed to {label}. No device action was executed because the physical adapter is not connected yet."
        return f"{label} 확인했습니다. 아직 실제 기기 어댑터가 연결되지 않아 동작은 실행하지 않았습니다."
    if kind == "confirmation_rejected":
        return "Cancelled." if language == "en-US" else "취소했습니다."
    if kind == "confirmation_retry":
        return "Please say confirm or cancel." if language == "en-US" else "'확인' 또는 '취소'라고 말씀해주세요."
    raise ValueError(f"unsupported intent reply kind: {kind}")


async def codex_reply(prompt: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        CODEX_BIN,
        "exec",
        "--skip-git-repo-check",
        prompt,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CODEX_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"Codex request exceeded {CODEX_TIMEOUT_SECONDS:.0f}s")

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        detail = err.splitlines()[-1] if err else f"exit {proc.returncode}"
        raise RuntimeError(f"Codex CLI failed: {detail}")
    if not out:
        raise RuntimeError("Codex CLI returned an empty response")
    return out


async def main() -> None:
    intent_session = VoiceIntentSession()
    model_lock = asyncio.Lock()
    histories = {
        "grandma": deque(maxlen=HISTORY_TURNS * 2),
        "personal": deque(maxlen=HISTORY_TURNS * 2),
    }
    last_model_turn = {"grandma": 0.0, "personal": 0.0}
    last_correlation = {"grandma": None, "personal": None}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        req = None
        try:
            raw = await read_packet(reader)
            req = parse_request(raw)
            profile = req["profile"]
            language = req["language"]
            text = req["text"]
            envelope = req["envelope"]

            if not text:
                response = assistant_response(
                    envelope,
                    "말씀을 다시 해주세요." if language != "en-US" else "I didn't catch that.",
                )
                await write_packet(writer, json.dumps(response, ensure_ascii=False))
                return

            decision = intent_session.process(envelope)
            for event in decision["events"]:
                print(
                    f"[Okja/Codex] event={event['event_type']} id={event['event_id']} "
                    f"correlation={event['correlation_id']}"
                )
            if decision["kind"] != "assistant_query":
                reply = intent_reply(
                    decision["kind"],
                    decision.get("target"),
                    decision.get("action"),
                    language,
                )
                response = assistant_response(envelope, reply)
                await write_packet(writer, json.dumps(response, ensure_ascii=False))
                return

            now = time.monotonic()
            history = histories[profile]
            correlation = envelope["correlation_id"]
            if last_correlation[profile] != correlation or now - last_model_turn[profile] > HISTORY_IDLE_RESET_SECONDS:
                history.clear()
            last_correlation[profile] = correlation
            started = time.perf_counter()
            print(
                f"[Okja/Codex] event={envelope['event_id']} "
                f"correlation={envelope['correlation_id']} {profile}/{language} request"
            )

            # Serialize model calls on the phone to avoid stacking multiple Codex CLI
            # processes if repeated wake/STT events arrive while a response is pending.
            async with model_lock:
                prompt = make_prompt(profile, language, text, list(history))
                reply = await codex_reply(prompt)

            history.append(("user", text))
            history.append(("assistant", reply))
            last_model_turn[profile] = time.monotonic()

            elapsed = time.perf_counter() - started
            print(
                f"[Okja/Codex] correlation={envelope['correlation_id']} completed ({elapsed:.2f}s)"
            )
            response = assistant_response(envelope, reply)
            await write_packet(writer, json.dumps(response, ensure_ascii=False))

        except Exception as exc:
            error_code = type(exc).__name__
            print(f"[Okja/Codex] request failed: {error_code}: {exc}")
            if req is not None:
                try:
                    failure = assistant_failure(
                        req["envelope"], error_code, "Assistant request failed"
                    )
                    await write_packet(writer, json.dumps(failure, ensure_ascii=False))
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
    print(f"[Okja/Codex] listening on {sockets}; local intents bypass Codex")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
