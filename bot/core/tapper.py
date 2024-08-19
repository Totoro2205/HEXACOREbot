import asyncio
import time
import aiohttp
import json
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import (
    Unauthorized,
    UserDeactivated,
    AuthKeyUnregistered,
    FloodWait,
)
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw import types
from bot.config import settings
from bot.utils import logger
from bot.exceptions import InvalidSession
from random import randint
from urllib.parse import unquote
from .agents import generate_random_user_agent
from .headers import headers
from .webapp import WebappURLs


class Tapper:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.user_id = 0
        self.username = None
        self.first_name = None
        self.last_name = None
        self.fullname = None

        self.session_ug_dict = self.load_user_agents() or []

        headers["User-Agent"] = self.check_user_agent()

    async def generate_random_user_agent(self):
        return generate_random_user_agent(device_type="android", browser_type="chrome")

    def save_user_agent(self):
        user_agents_file_name = "user_agents.json"

        if not any(
            session["session_name"] == self.session_name
            for session in self.session_ug_dict
        ):
            user_agent_str = generate_random_user_agent()

            self.session_ug_dict.append(
                {"session_name": self.session_name, "user_agent": user_agent_str}
            )

            with open(user_agents_file_name, "w") as user_agents:
                json.dump(self.session_ug_dict, user_agents, indent=4)

            logger.info(
                f"<light-yellow>{self.session_name}</light-yellow> | User agent saved successfully"
            )

            return user_agent_str

    def load_user_agents(self):
        user_agents_file_name = "user_agents.json"

        try:
            with open(user_agents_file_name, "r") as user_agents:
                session_data = json.load(user_agents)
                if isinstance(session_data, list):
                    return session_data

        except FileNotFoundError:
            logger.warning("User agents file not found, creating...")

        except json.JSONDecodeError:
            logger.warning("User agents file is empty or corrupted.")

        return []

    def check_user_agent(self):
        load = next(
            (
                session["user_agent"]
                for session in self.session_ug_dict
                if session["session_name"] == self.session_name
            ),
            None,
        )

        if load is None:
            return self.save_user_agent()

        return load

    async def get_tg_web_data(self, proxy: str | None) -> str:
        if proxy:
            proxy = Proxy.from_str(proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password,
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            with_tg = True

            if not self.tg_client.is_connected:
                with_tg = False
                try:
                    await self.tg_client.connect()
                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

            while True:
                try:
                    peer = await self.tg_client.resolve_peer("HexacoinBot")
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")

                    await asyncio.sleep(fls + 3)

            InputBotApp = types.InputBotAppShortName(bot_id=peer, short_name="wallet")

            web_view = await self.tg_client.invoke(
                RequestAppWebView(
                    peer=peer,
                    app=InputBotApp,
                    platform="android",
                    write_allowed=True,
                )
            )

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(
                    string=auth_url.split("tgWebAppData=", maxsplit=1)[1].split(
                        "&tgWebAppVersion", maxsplit=1
                    )[0]
                )
            )

            try:
                information = await self.tg_client.get_me()
                self.user_id = information.id
                self.first_name = information.first_name or ""
                self.last_name = information.last_name or ""
                self.username = information.username or ""
            except Exception as e:
                print(e)

            self.fullname = f"{self.first_name} {self.last_name}".strip()

            if with_tg is False:
                await self.tg_client.disconnect()

            return tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as _ex:
            logger.error(
                f"{self.session_name} | Unknown error during Authorization: {repr(_ex)}"
            )
            await asyncio.sleep(delay=3)

    async def auth(self, http_client: aiohttp.ClientSession):
        try:
            json_data = {"user_id": int(self.user_id), "username": str(self.username)}
            response = await http_client.post(
                url=WebappURLs.APP_AUTH, json=json_data, ssl=False
            )
            response.raise_for_status()
            response_json = await response.json()
            return response_json.get("token")
        except Exception as error:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while auth {error}"
            )

    async def register(self, http_client: aiohttp.ClientSession):
        try:
            json_data = {}

            http_client.headers["Host"] = "ago-wallet.hexacore.io"
            if (
                http_client.headers["Authorization"] is None
                or http_client.headers["Authorization"] == ""
            ):
                http_client.headers["Authorization"] = await self.auth(
                    http_client=http_client
                )

            if settings.REF_ID == "":
                referer_id = "395128614"
            else:
                referer_id = str(settings.REF_ID)  # Ensure referer_id is a string

            if self.username != "":
                json_data = {
                    "user_id": self.user_id,
                    "fullname": f"{self.fullname}",
                    "username": f"{self.username}",
                    "referer_id": f"{referer_id}",
                }
                response = await http_client.post(
                    url=WebappURLs.CREATE_USER, json=json_data, ssl=False
                )
                if response.status == 409:
                    return "registered"
                if response.status in (200, 201):
                    return True
                if response.status not in (200, 201, 409):
                    logger.critical(
                        f"<light-yellow>{self.session_name}</light-yellow> | "
                        f"Something wrong while register! {response.status}"
                    )
                    return False
            else:
                logger.critical(
                    f"<light-yellow>{self.session_name}</light-yellow> | Error while register, "
                    f"please add username to telegram account, bot will not work!!!"
                )
                return False
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | "
                f"Error while register {repr(_ex)}"
            )

    async def get_taps(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=WebappURLs.AVAILABLE_TAPS, ssl=False)
            response_json = await response.json()
            # logger.debug(f"<light-yellow>{self.session_name}</light-yellow> |
            # Available taps: {response_json.get('available_taps')}")
            return response_json.get("available_taps")
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while get taps {repr(_ex)}"
            )

    async def get_balance(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(
                url=f"{WebappURLs.BALANCE}/{self.user_id}", ssl=False
            )
            response_json = await response.json()
            return response_json
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | "
                f"Error while get balance {repr(_ex)}"
            )

    async def get_leaderboard(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(
                url=f"{WebappURLs.LEADER_BOARD}", ssl=False
            )
            response_json = await response.json()
            player_rank = response_json.get("player_rank")
            user_name = player_rank.get("username")
            tokens = player_rank.get("tokens")
            rank = player_rank.get("rank")
            return user_name, rank, tokens
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | "
                f"Error while get leaderboard {repr(_ex)}"
            )

    async def do_taps(self, http_client: aiohttp.ClientSession, taps):
        try:
            taps_chunk = randint(settings.TAPS_CHUNK[0], settings.TAPS_CHUNK[1])
            logger.info(
                f"<light-yellow>{self.session_name}</light-yellow> | "
                f"Tapping with <g>{taps_chunk}</g> taps chunks started"
            )
            full_cycles = taps // taps_chunk
            remainder = taps % taps_chunk

            for _ in range(full_cycles):
                json_data = {"taps": taps_chunk}
                response = await http_client.post(
                    url=WebappURLs.MINING_COMPLETE, json=json_data, ssl=False
                )
                response_json = await response.json()
                time.sleep(2)
                if not response_json.get("success"):
                    return False

            if remainder > 0:
                json_data = {"taps": remainder}
                response = await http_client.post(
                    url=WebappURLs.MINING_COMPLETE, json=json_data, ssl=False
                )
                response_json = await response.json()
                if not response_json.get("success"):
                    return False

            return True

        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while tapping {repr(_ex)}"
            )

    async def get_missions(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=WebappURLs.MISSIONS, ssl=False)
            response_json = await response.json()
            incomplete_mission_ids = [
                mission["id"]
                for mission in response_json
                if (not mission["isCompleted"] and mission["autocomplete"])
            ]

            return incomplete_mission_ids
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while get missions {repr(_ex)}"
            )

    async def do_mission(self, http_client: aiohttp.ClientSession, id):
        try:
            json = {"missionId": id}
            response = await http_client.post(
                url=WebappURLs.MISSION_COMPLETE, json=json, ssl=False
            )
            response_json = await response.json()
            if not response_json.get("success"):
                return False
            return True
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while doing missions {repr(_ex)}"
            )

    async def get_level_info(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=WebappURLs.LEVEL, ssl=False)
            response_json = await response.json()
            lvl = response_json.get("lvl")
            upgrade_available = response_json.get("upgrade_available")
            upgrade_price = response_json.get("upgrade_price")
            tap_size = response_json.get("tap")
            max_taps = response_json.get("taps")
            return lvl, upgrade_available, upgrade_price, tap_size, max_taps
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while get level {repr(_ex)}"
            )

    async def level_up(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.post(url=WebappURLs.UPGRADE_LEVEL, ssl=False)
            response_json = await response.json()
            if not response_json.get("success"):
                return False
            return True
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while up lvl {repr(_ex)}"
            )

    async def play_game_1(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(
                url=f"{WebappURLs.IN_GAME_REWARD_AVAILABLE}/1/" f"{self.user_id}",
                ssl=False,
            )
            response_json = await response.json()
            if response_json.get("available"):
                json_data = {"game_id": 1, "user_id": self.user_id}
                response1 = await http_client.post(
                    url=WebappURLs.IN_GAME_REWARD, json=json_data, ssl=False
                )
                if response1.status in (200, 201):
                    return True
            else:
                return False

        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 1 {repr(_ex)}"
            )

    async def play_game_2(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(
                url=f"{WebappURLs.IN_GAME_REWARD_AVAILABLE}/2/{self.user_id}", ssl=False
            )
            response_json = await response.json()
            if response_json.get("available"):
                json_data = {"game_id": 2, "user_id": self.user_id}
                response1 = await http_client.post(
                    url=WebappURLs.IN_GAME_REWARD, json=json_data, ssl=False
                )
                if response1.status in (200, 201):
                    return True
            else:
                return False

        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | "
                f"Error while play game 2 {repr(_ex)}"
            )

    async def play_game_3(self, http_client: aiohttp.ClientSession):
        try:
            http_client.headers["Host"] = "dirty-job-server.hexacore.io"

            response = await http_client.get(
                url=f"https://dirty-job-server.hexacore.io/game/start?playerId="
                f"{self.user_id}",
                ssl=False,
            )
            response.raise_for_status()
            response_json = await response.json()

            level = response_json.get("playerState").get("currentGameLevel")

            for i in range(level + 1, 173):
                json_data = {
                    "type": "EndGameLevelEvent",
                    "playerId": self.user_id,
                    "level": i,
                    "boosted": False,
                    "transactionId": None,
                }
                response1 = await http_client.post(
                    url=f"https://dirty-job-server.hexacore.io/game/end-game-level",
                    json=json_data,
                    ssl=False,
                )

                if response1.status in (200, 201):
                    logger.info(
                        f"<light-yellow>{self.session_name}</light-yellow> | Done {i} lvl in dirty job"
                    )

                elif response1.status == 400:
                    logger.warning(
                        f"<light-yellow>{self.session_name}</light-yellow> | Reached max games for today in "
                        f"dirty job"
                    )
                    break

                await asyncio.sleep(1)

            response1 = await http_client.get(
                url=f"https://dirty-job-server.hexacore.io/game/start?playerId={self.user_id}",
                ssl=False,
            )
            response1_json = await response1.json()

            balance = response1_json.get("playerState").get("inGameCurrencyCount")
            hub_items_owned = response1_json.get("playerState").get("hubItems")
            game_config_hub_items = response1_json.get("gameConfig").get("hubItems")

            logger.info(
                f"<light-yellow>{self.session_name}</light-yellow> | Trying to upgrade items in dirty job, "
                f"wait a bit"
            )
            await self.auto_purchase_upgrades(
                http_client, balance, hub_items_owned, game_config_hub_items
            )
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 3 {repr(_ex)}"
            )

    async def auto_purchase_upgrades(
        self,
        http_client: aiohttp.ClientSession,
        balance: int,
        owned_items: dict,
        available_items: dict,
    ):
        try:
            for item_name, item_info in available_items.items():
                if item_name not in owned_items:
                    upgrade_level_info = list(map(int, item_info["levels"].keys()))
                    level_str = str(upgrade_level_info[0])
                    price = item_info["levels"][level_str]["inGameCurrencyPrice"]
                    ago = item_info["levels"][level_str]["agoReward"]

                    if balance >= price:
                        purchase_data = {
                            "type": "UpgradeHubItemEvent",
                            "playerId": f"{self.user_id}",
                            "itemId": f"{item_name}",
                            "level": upgrade_level_info[0],
                        }
                        purchase_response = await http_client.post(
                            url="https://dirty-job-server.hexacore.io/game/upgrade-hub-item",
                            json=purchase_data,
                            ssl=False,
                        )

                        if purchase_response.status in (200, 201):
                            logger.success(
                                f"<light-yellow>{self.session_name}</light-yellow> | "
                                f"Purchased new item {item_name} for {price} currency in dirty job game, "
                                f"got {ago} AGO"
                            )
                            balance -= price
                            owned_items[item_name] = {"level": upgrade_level_info[0]}
                        else:
                            logger.warning(
                                f"Failed to purchase new item {item_name}. Status code: {purchase_response.status}"
                            )

                elif item_name in owned_items:
                    current_level = int(owned_items[item_name]["level"])
                    upgrade_level_info = list(map(int, item_info["levels"].keys()))

                    next_levels_to_upgrade = [
                        level for level in upgrade_level_info if level > current_level
                    ]

                    if not next_levels_to_upgrade:
                        continue

                    for level in next_levels_to_upgrade:
                        level_str = str(level)
                        price = item_info["levels"][level_str]["inGameCurrencyPrice"]
                        ago = item_info["levels"][level_str]["agoReward"]

                        if balance >= price:
                            purchase_data = {
                                "type": "UpgradeHubItemEvent",
                                "playerId": f"{self.user_id}",
                                "itemId": f"{item_name}",
                                "level": level,
                            }
                            purchase_response = await http_client.post(
                                url="https://dirty-job-server.hexacore.io/game/upgrade-hub-item",
                                json=purchase_data,
                                ssl=False,
                            )

                            if purchase_response.status in (200, 201):
                                logger.success(
                                    f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"Purchased upgrade for {item_name} for {price} currency in dirty job "
                                    f"game, got {ago} AGO"
                                )
                                balance -= price
                                owned_items[item_name]["level"] = level
                            else:
                                logger.warning(
                                    f"Failed to purchase upgrade for {item_name}. Status code: "
                                    f"{purchase_response.status}"
                                )

                await asyncio.sleep(0.5)

        except Exception as error:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error during auto-purchase upgrades {error}"
            )

    async def play_game_5(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(
                url=f"{WebappURLs.IN_GAME_REWARD_AVAILABLE}/5/" f"{self.user_id}",
                ssl=False,
            )
            response_json = await response.json()
            if response_json.get("available"):
                json_data = {"game_id": 5, "user_id": self.user_id}
                response1 = await http_client.post(
                    url=WebappURLs.IN_GAME_REWARD, json=json_data, ssl=False
                )
                if response1.status in (200, 201):
                    return True
            else:
                return False

        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 5 {repr(_ex)}"
            )

    async def daily_claim(self, http_client: aiohttp.ClientSession):
        try:
            json_data = {"user_id": self.user_id}
            response = await http_client.post(
                url=WebappURLs.DAILY_REWARD, json=json_data, ssl=False
            )
            response_json = await response.json()
            tokens = response_json.get("tokens")
            if tokens is not None:
                return tokens
            else:
                return False
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error claiming daily reward {repr(_ex)}"
            )

    async def daily_checkin(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=WebappURLs.DAILY_CHECKIN, ssl=False)
            checkin_json = await response.json()
            checkin_available = checkin_json.get("is_available")
            next_level = checkin_json.get("next")
            rewards = checkin_json.get("config")
            reward = rewards.get(f"{next_level}")
            if checkin_available:
                json_data = {"day": next_level}
                response = await http_client.post(
                    url=WebappURLs.DAILY_CHECKIN, json=json_data, ssl=False
                )
                if response.status == 200:
                    response = await http_client.get(
                        url=WebappURLs.DAILY_CHECKIN, ssl=False
                    )
                    response_json = await response.json()
                    if not response_json.get("is_available"):
                        return reward
            return False
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while daily reward {repr(_ex)}"
            )

    async def get_tap_passes(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=WebappURLs.GET_TAP_PASSES, ssl=False)
            response_json = await response.json()
            return response_json
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while getting tap passes {repr(_ex)}"
            )

    async def buy_tap_pass(self, http_client: aiohttp.ClientSession):
        try:
            json_data = {"name": "7_days"}
            response = await http_client.post(
                url=WebappURLs.BUY_TAP_PASSES, json=json_data, ssl=False
            )
            response_json = await response.json()
            if response_json.get("status") is False:
                return False
            return True
        except Exception as error:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Error while getting tap passes {error}"
            )

    async def check_proxy(
        self, http_client: aiohttp.ClientSession, proxy: Proxy
    ) -> None:
        try:
            response = await http_client.get(
                url="https://httpbin.org/ip",
                timeout=aiohttp.ClientTimeout(45),
                ssl=False,
            )
            ip = (await response.json()).get("origin")
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as _ex:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {repr(_ex)}")

    async def check_user_exists(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=WebappURLs.USER_EXISTS, ssl=False)
            response_json = await response.json()
            return response_json.get("exists")
        except Exception as _ex:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | "
                f"Error while checking registration status {repr(_ex)}"
            )

    async def run(self, proxy: str | None) -> None:
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)

        if proxy:
            await self.check_proxy(http_client=http_client, proxy=proxy)

        await self.get_tg_web_data(proxy=proxy)

        http_client.headers["Authorization"] = await self.auth(http_client=http_client)
        while True:
            try:
                registration_status = await self.check_user_exists(
                    http_client=http_client
                )
                if not registration_status:
                    status = await self.register(http_client=http_client)
                    if status is True:
                        logger.success(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Account was successfully registered!"
                        )
                    elif status == "registered":
                        pass
                lvl, available, price, tap_size, max_taps = await self.get_level_info(
                    http_client=http_client
                )
                info = await self.get_balance(http_client=http_client)
                balance = info.get("balance") or 0
                logger.info(
                    f"<light-yellow>{self.session_name}</light-yellow> | "
                    f"Balance: <g>{balance:,}</g> AGO | Level: <g>{lvl}</g> | "
                    f"Taps limit: <g>{max_taps:,}</g> | Tap size: <g>{tap_size}</g>"
                )
                username, rank, overall_tokens = await self.get_leaderboard(
                    http_client=http_client
                )
                logger.info(
                    f"<light-yellow>{self.session_name}</light-yellow> | "
                    f"User <light-yellow>{username}</light-yellow> is on <g>{rank}</g> place on liderboard"
                    f" with overall balance <g>{overall_tokens:,}</g> AGO"
                )

                tokens = await self.daily_claim(http_client=http_client)
                if tokens is not False:
                    logger.success(
                        f"<light-yellow>{self.session_name}</light-yellow> | "
                        f"Daily claimed: <g>{tokens:,}</g> AGO"
                    )

                if settings.DAILY_CHECKIN:
                    checkin_result = await self.daily_checkin(http_client=http_client)
                    if checkin_result:
                        logger.success(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Successful daily in-app checkin! Claimed <g>{checkin_result:,}</g> AGO"
                        )

                if settings.AUTO_BUY_PASS:
                    data = await self.get_tap_passes(http_client=http_client)
                    if data.get("active_tap_pass") is None and balance >= 1000:
                        status = await self.buy_tap_pass(http_client=http_client)
                        if status:
                            logger.success(
                                f"<light-yellow>{self.session_name}</light-yellow> | Bought taps pass for 7 days"
                            )

                if settings.AUTO_TAP:
                    taps = await self.get_taps(http_client=http_client)
                    if taps != 0:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | You have <g>{taps:,}</g> taps "
                            f"available, starting tapping, please wait a bit.."
                        )
                        status = await self.do_taps(http_client=http_client, taps=taps)
                        if status:
                            logger.success(
                                f"<light-yellow>{self.session_name}</light-yellow> | Successfully tapped "
                                f"{taps} times"
                            )
                        else:
                            logger.warning(
                                f"<light-yellow>{self.session_name}</light-yellow> | Problem with taps"
                            )

                if settings.AUTO_MISSION:
                    missions = await self.get_missions(http_client=http_client)
                    missions.sort()
                    for id in missions:
                        status = await self.do_mission(http_client=http_client, id=id)
                        if status:
                            logger.info(
                                f"<light-yellow>{self.session_name}</light-yellow> | "
                                f"Successfully done mission {id}"
                            )
                        await asyncio.sleep(0.75)

                if settings.AUTO_LVL_UP:
                    info = await self.get_balance(http_client=http_client)
                    balance = info.get("balance") or 0
                    lvl, available, price, tap_size, max_taps = await self.get_level_info(
                        http_client=http_client
                    )
                    if available and price <= balance:
                        status = await self.level_up(http_client=http_client)
                        if status:
                            logger.success(
                                f"<light-yellow>{self.session_name}</light-yellow> | "
                                f"Successfully level up, now {lvl + 1}"
                            )

                if settings.PLAY_WALK_GAME:
                    status = await self.play_game_1(http_client=http_client)
                    if status:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Successfully played walk game"
                        )
                    else:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Walk game cooldown"
                        )

                if settings.PLAY_SHOOT_GAME:
                    status = await self.play_game_2(http_client=http_client)
                    if status:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Successfully played shoot game"
                        )
                    else:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Shoot game cooldown"
                        )

                if settings.PLAY_RPG_GAME:
                    status = await self.play_game_5(http_client=http_client)
                    if status:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"Successfully played RPG game"
                        )
                    else:
                        logger.info(
                            f"<light-yellow>{self.session_name}</light-yellow> | "
                            f"RPG game cooldown"
                        )

                if settings.PLAY_DIRTY_JOB_GAME:
                    await self.play_game_3(http_client=http_client)

                logger.info(
                    f"<light-yellow>{self.session_name}</light-yellow> | Going sleep 1 hour"
                )

                http_client.headers["Host"] = "ago-api.hexacore.io"

                await asyncio.sleep(3600)

            except InvalidSession as error:
                raise error

            except Exception as _ex:
                logger.error(f"{self.session_name} | Unknown error: {repr(_ex)}")
                await asyncio.sleep(delay=10)
                continue


async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
