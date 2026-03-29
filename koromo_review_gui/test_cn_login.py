import asyncio
import hashlib
import hmac
import json
import os
import random
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "_external" / "mahjong_soul_api"))

from ms.base import MSRPCChannel
from ms.rpc import Lobby
import ms.protocol_pb2 as pb


CN_HOST = "https://game.maj-soul.com"


@dataclass
class LoginAttemptResult:
    label: str
    ok: bool
    account_id: int | None
    access_token_present: bool
    error_code: int | None
    error_json: str | None
    extra: str | None = None


async def fetch_cn_version_and_gateways() -> tuple[str, list[str]]:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{CN_HOST}/1/version.json") as res:
            version_data = await res.json()
        version = version_data["version"]
        async with session.get(f"{CN_HOST}/1/v{version}/config.json") as res:
            config = await res.json()

    ip_def = next(x for x in config["ip"] if x["name"] == "player")
    gateways = []
    if "gateways" in ip_def:
        gateways = [x["url"].replace("https://", "").replace("http://", "") for x in ip_def["gateways"] if x.get("url")]
    elif "region_urls" in ip_def:
        gateways = [x["url"].replace("https://", "").replace("http://", "") for x in ip_def["region_urls"] if x.get("url")]
    if not gateways:
        raise RuntimeError("No CN gateways found in config")
    return version, gateways


async def connect_lobby(endpoint: str, host: str) -> tuple[Lobby, MSRPCChannel]:
    channel = MSRPCChannel(endpoint)
    lobby = Lobby(channel)
    await channel.connect(host)
    return lobby, channel


def make_req_login(account: str, password: str, version: str, login_type: int | None = None) -> pb.ReqLogin:
    req = pb.ReqLogin()
    req.account = account
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
    req.client_version_string = f"web-{version.replace('.w', '')}"
    req.client_version.resource = version
    if login_type is not None:
        req.type = login_type
    return req


def make_req_email_login(email: str, password: str, version: str) -> pb.ReqEmailLogin:
    req = pb.ReqEmailLogin()
    req.email = email
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
    req.client_version = version
    return req


def to_result(label: str, response) -> LoginAttemptResult:
    error = getattr(response, "error", None)
    error_code = getattr(error, "code", None) if error is not None else None
    error_json = getattr(error, "json_param", None) if error is not None else None
    account_id = getattr(response, "account_id", None)
    access_token = getattr(response, "access_token", None)
    return LoginAttemptResult(
        label=label,
        ok=bool(account_id or access_token),
        account_id=account_id or None,
        access_token_present=bool(access_token),
        error_code=error_code or None,
        error_json=error_json or None,
    )


async def run_attempts(account: str, email: str, password: str) -> dict:
    version, gateways = await fetch_cn_version_and_gateways()
    gateway = random.choice(gateways)
    endpoint = f"wss://{gateway}/gateway"

    attempts: list[LoginAttemptResult] = []
    lobby, channel = await connect_lobby(endpoint, CN_HOST)
    try:
        req = make_req_login(account, password, version)
        attempts.append(to_result("ReqLogin(account, default type)", await lobby.login(req)))

        req = make_req_login(account, password, version, 0)
        attempts.append(to_result("ReqLogin(account, type=0)", await lobby.login(req)))

        req = make_req_login(account, password, version, 1)
        attempts.append(to_result("ReqLogin(account, type=1)", await lobby.login(req)))

        req = make_req_login(email, password, version)
        attempts.append(to_result("ReqLogin(email, default type)", await lobby.login(req)))

        req = make_req_email_login(email, password, version)
        attempts.append(to_result("ReqEmailLogin(email)", await lobby.email_login(req)))
    finally:
        await channel.close()

    return {
        "version": version,
        "endpoint": endpoint,
        "results": [asdict(x) for x in attempts],
    }


def main() -> None:
    account = os.environ.get("MS_CN_ACCOUNT") or input("CN account: ").strip()
    email = os.environ.get("MS_CN_EMAIL") or input("CN email: ").strip()
    password = os.environ.get("MS_CN_PASSWORD") or input("CN password: ").strip()
    out_path = Path("koromo_review_gui") / "cn_login_probe_result.json"
    result = asyncio.run(run_attempts(account, email, password))
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
