from __future__ import annotations

from bslfs.terps.frames import FrameFormat, FrameParser, crc16_ccitt


def build_body(
    *,
    ts=1,
    f_hz_x1e4=300000000,
    tau_ms=100,
    v_uv=500000,
    adc_gain=16,
    flags=0,
    ppm=0,
    mode=1,
):
    return (
        ts.to_bytes(4, "little")
        + int(f_hz_x1e4).to_bytes(4, "little", signed=True)
        + tau_ms.to_bytes(2, "little")
        + int(v_uv).to_bytes(4, "little", signed=True)
        + adc_gain.to_bytes(1, "little")
        + flags.to_bytes(1, "little")
        + int(ppm).to_bytes(2, "little", signed=True)
        + mode.to_bytes(1, "little")
    )


def build_packet(body: bytes, *, crc_override: int | None = None, length_override: int | None = None) -> bytes:
    crc = crc_override if crc_override is not None else crc16_ccitt(body)
    length = length_override if length_override is not None else len(body)
    return b"\x55\xAA" + bytes([length]) + body + crc.to_bytes(2, "little")


def feed(parser: FrameParser, packet: bytes) -> list:
    return list(parser.parse_binary([packet]))


def test_binary_frame_crc_failure():
    parser = FrameParser(FrameFormat.BINARY)
    body = build_body()
    good_packet = build_packet(body)
    frames = feed(parser, good_packet)
    assert len(frames) == 1
    stats = parser.stats()
    assert stats["frames"] == 1
    assert stats["crc_errors"] == 0

    bad_crc = (crc16_ccitt(body) ^ 0xFFFF) & 0xFFFF
    bad_packet = build_packet(body, crc_override=bad_crc)
    frames = feed(parser, bad_packet)
    assert frames == []
    stats = parser.stats()
    assert stats["crc_errors"] == 1


def test_binary_frame_length_error():
    parser = FrameParser(FrameFormat.BINARY)
    body = build_body()
    wrong_packet = build_packet(body, length_override=len(body) - 1)
    frames = feed(parser, wrong_packet)
    assert frames == []
    stats = parser.stats()
    assert stats["length_errors"] == 1

    # Parser recovers when the next packet is correct
    good_packet = build_packet(body)
    frames = feed(parser, good_packet)
    assert len(frames) == 1
    stats = parser.stats()
    assert stats["frames"] == 1
