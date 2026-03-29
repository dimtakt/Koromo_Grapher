import asyncio
import hashlib
import hmac
import json
import random
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from google.protobuf.json_format import MessageToDict

from .runtime_paths import mahjong_soul_api_root

sys.path.insert(0, str(mahjong_soul_api_root()))

from ms.base import MSRPCChannel
from ms.rpc import Lobby
import ms.protocol_pb2 as pb


CN_HOST = "https://game.maj-soul.com"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=8, sock_read=20)


@dataclass
class CnFetchResult:
    game_uuid: str
    head_path: Path
    record_data_path: Path
    account_id: int
    endpoint: str
    version: str


@dataclass
class CnSession:
    lobby: Lobby
    channel: MSRPCChannel
    version: str
    endpoint: str
    account_id: int


async def fetch_cn_version_and_gateways() -> tuple[str, list[str]]:
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        async with session.get(f"{CN_HOST}/1/version.json") as res:
            version_data = await res.json()
        version = version_data["version"]
        async with session.get(f"{CN_HOST}/1/v{version}/config.json") as res:
            config = await res.json()

    ip_def = next(x for x in config["ip"] if x["name"] == "player")
    if "gateways" in ip_def:
        gateways = [
            x["url"].replace("https://", "").replace("http://", "")
            for x in ip_def["gateways"]
            if x.get("url")
        ]
    else:
        gateways = [
            x["url"].replace("https://", "").replace("http://", "")
            for x in ip_def["region_urls"]
            if x.get("url")
        ]
    if not gateways:
        raise RuntimeError("No CN gateways found")
    return version, gateways


async def connect_lobby(endpoint: str) -> tuple[Lobby, MSRPCChannel]:
    channel = MSRPCChannel(endpoint)
    lobby = Lobby(channel)
    await channel.connect(CN_HOST)
    return lobby, channel


def build_login_request(email: str, password: str, version: str) -> pb.ReqLogin:
    req = pb.ReqLogin()
    req.account = email
    req.password = hmac.new(b"lailai", password.encode(), hashlib.sha256).hexdigest()
    req.reconnect = False
    req.device.platform = "pc"
    req.device.hardware = "pc"
    req.device.os = "windows"
    req.device.os_version = "win10"
    req.device.is_browser = True
    req.device.software = "Chrome"
    req.device.sale_platform = "web"
    req.random_key = str(uuid.uuid4())
    req.gen_access_token = True
    req.currency_platforms.append(2)
    req.client_version.resource = version
    req.client_version_string = f"web-{version.replace('.w', '')}"
    return req


async def login_cn(email: str, password: str) -> tuple[Lobby, MSRPCChannel, str, str, int]:
    version, gateways = await fetch_cn_version_and_gateways()
    shuffled_gateways = list(gateways)
    random.shuffle(shuffled_gateways)
    errors: list[str] = []

    for gateway in shuffled_gateways:
        endpoint = f"wss://{gateway}/gateway"
        channel: MSRPCChannel | None = None
        try:
            lobby, channel = await connect_lobby(endpoint)
            req = build_login_request(email, password, version)
            res = await asyncio.wait_for(lobby.login(req), timeout=30)
            if not res.account_id:
                error = getattr(res, "error", None)
                code = getattr(error, "code", None) if error is not None else None
                json_param = getattr(error, "json_param", None) if error is not None else None
                errors.append(f"{endpoint}: code={code} json={json_param}")
                await channel.close()
                continue
            return lobby, channel, version, endpoint, res.account_id
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
            if channel is not None:
                try:
                    await channel.close()
                except Exception:
                    pass

    raise RuntimeError("CN login failed across gateways:\n" + "\n".join(errors[:8]))


async def open_cn_session(email: str, password: str) -> CnSession:
    lobby, channel, version, endpoint, account_id = await login_cn(email, password)
    return CnSession(
        lobby=lobby,
        channel=channel,
        version=version,
        endpoint=endpoint,
        account_id=account_id,
    )


async def close_cn_session(session: CnSession) -> None:
    await session.channel.close()


async def fetch_game_record_with_session(
    session: CnSession,
    game_uuid: str,
    output_dir: str | Path,
) -> CnFetchResult:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    req = pb.ReqGameRecord()
    req.game_uuid = game_uuid
    req.client_version_string = f"web-{session.version.replace('.w', '')}"
    res = await session.lobby.fetch_game_record(req)

    head_path = out_dir / f"{game_uuid}.head.json"
    head_path.write_text(
        json.dumps(
            MessageToDict(res.head, preserving_proto_field_name=True),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    record_data_path = out_dir / f"{game_uuid}.recordData"
    data = b""
    if getattr(res, "data", None):
        data = res.data
    elif getattr(res, "data_url", None):
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as http_session:
            async with http_session.get(res.data_url) as data_res:
                data = await data_res.read()
    record_data_path.write_bytes(data)
    return CnFetchResult(
        game_uuid=game_uuid,
        head_path=head_path,
        record_data_path=record_data_path,
        account_id=session.account_id,
        endpoint=session.endpoint,
        version=session.version,
    )


async def fetch_game_record(email: str, password: str, game_uuid: str, output_dir: str | Path) -> CnFetchResult:
    session = await open_cn_session(email, password)
    try:
        return await fetch_game_record_with_session(session, game_uuid, output_dir)
    finally:
        await close_cn_session(session)


def fetch_game_record_sync(email: str, password: str, game_uuid: str, output_dir: str | Path) -> CnFetchResult:
    return asyncio.run(fetch_game_record(email, password, game_uuid, output_dir))


class CnSessionClientSync:
    def __init__(self, email: str, password: str):
        self._loop = asyncio.new_event_loop()
        self._closed = False
        asyncio.set_event_loop(self._loop)
        self._session = self._loop.run_until_complete(open_cn_session(email, password))

    def fetch_game_record(self, game_uuid: str, output_dir: str | Path) -> CnFetchResult:
        if self._closed:
            raise RuntimeError("CN session client is already closed")
        asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(
            fetch_game_record_with_session(self._session, game_uuid, output_dir)
        )

    def close(self) -> None:
        if self._closed:
            return
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(close_cn_session(self._session))
        self._loop.close()
        self._closed = True
