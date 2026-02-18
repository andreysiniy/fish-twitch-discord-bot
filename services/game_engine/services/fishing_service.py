from infrastructure.repositories import UserRepository, ConfigRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.models import UserProgress

from core.action_types import ActionType
from core.game_params import GParam, resolve_param
from core.messages import MsgKey, resolve_message, format_percent_signed, format_large_number_mass
from domain.logic.formulas import calculate_xp_required
from domain.logic.stats_calculator import calculate_player_stats

from services.fishing.engine import FishingEngine
from services.fishing.presenter import FishingPresenter

from domain.schemas.fishing import RobberyResultDTO, FishStatsResponse, FishTopResponse, FishCooldownResponse

class FishingService:
    def __init__(
        self,
        user_repo: UserRepository,
        config_repo: ConfigRepository,
        cooldown_repo: CooldownRepository
    ):
        self.user_repo = user_repo
        self.config_repo = config_repo
        self.cooldown_repo = cooldown_repo
        self.engine = FishingEngine()
        self.presenter = FishingPresenter()

    def process_cast(
        self,
        twitch_id: str,
        username: str,
        channel_id: str,
        is_mod: bool = False,
        is_sub: bool = False
    ):
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)

        channel_config = user.channel.config or {}
        custom_params = channel_config.get("custom_params", {})
        cooldown_duration = self._resolve_cooldown_duration(custom_params, is_mod, is_sub)

        if cooldown_duration > 0:
            is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
            if is_active:
                return self.presenter.build_cooldown_response(
                    user=user,
                    cooldown_duration=cooldown_duration,
                    cooldown_left=seconds_left
                )
            
        location_id = user.current_location_id or "default"
        loot_pool, item_pool, rate = self.config_repo.get_dual_pool(channel_id, location_id)

        result = self.engine.calculate_result(
            user=user, 
            loot_pool=loot_pool, 
            item_pool=item_pool, 
            items_drop_rate=rate,
            custom_params=custom_params
        )

        if result.loot.get("type") == ActionType.ROBBERY:
            result.robbery_result = self._handle_robbery(result.loot, user)

        user.xp += result.xp_gained
        user.total_fish_stat += 1
        
        if result.is_level_up:
            user.level = result.new_level
            
        if result.mass_gained != 0:
            previous_mass = user.current_mass
            user.current_mass = max(previous_mass + result.mass_gained, 0.0)
            applied_mass_delta = round(user.current_mass - previous_mass, 2)
            user.total_mass_stat += max(applied_mass_delta, 0.0)
            result.mass_gained = applied_mass_delta
            
        if result.item_drop:
            self.user_repo.update_inventory(user, result.item_drop)
            location_item_id = result.item_drop.get("db_id")
            if location_item_id:
                self.config_repo.consume_location_item_stock(location_item_id, amount=1)

        self.user_repo.save_progress(user)
        if cooldown_duration > 0:
            self.cooldown_repo.set_cooldown(channel_id, twitch_id, cooldown_duration)

        response = self.presenter.build_response(user, result)
        
        return response

    def _resolve_cooldown_duration(self, custom_params: dict, is_mod: bool, is_sub: bool) -> int:
        if is_mod:
            return 0

        cooldown_key = GParam.SUBS_FISHING_COOLDOWN if is_sub else GParam.FISHING_COOLDOWN
        return max(int(resolve_param(custom_params, cooldown_key)), 0)
    
    def _handle_robbery(self, loot: dict, user: UserProgress) -> RobberyResultDTO:
        lookup_range = loot.get("range", 3)
        channel_config = user.channel.config or {}

        victim = self.user_repo.get_rich_victim(
            channel_id=user.channel.id,
            attacker_id=user.id,
            lookup_range=lookup_range
        )        

        robbery_result = self.engine.calculate_mass_robbery(
            attacker=user,
            victim=victim,
            channel_config=channel_config,
            catch=loot
        )

        if robbery_result.is_success:
            requested_stolen = max(float(robbery_result.amount_stolen or 0), 0.0)
            victim_previous_mass = max(float(victim.current_mass or 0), 0.0)
            applied_stolen = round(min(requested_stolen, victim_previous_mass), 2)

            user.current_mass += applied_stolen
            user.total_mass_stat += applied_stolen

            victim.current_mass = round(max(victim_previous_mass - applied_stolen, 0.0), 2)

            robbery_result.amount_stolen = applied_stolen
            robbery_result.victim_new_mass = victim.current_mass
            self.user_repo.save_progress(victim)
        
        return robbery_result

    def get_profile_stats(self, twitch_id: str, channel_id: str, username: str | None = None) -> FishStatsResponse:
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            return FishStatsResponse(
                success=False,
                chat_message=resolve_message({}, MsgKey.ERR_NO_PROFILE, username=username or twitch_id),
                stats={
                    "level": 1,
                    "xp": 0,
                    "xp_to_next_level": 100,
                    "current_mass": 0.0,
                    "total_fish_stat": 0,
                    "rod_name": "No rod equipped",
                    "luck_bonus": 0.0,
                    "resist_bonus": 0.0,
                    "xp_bonus_pct": 0.0,
                    "rank": 0,
                    "total_mass_stat": 0.0,
                }
            )

        stats = calculate_player_stats(user)
        channel_config = user.channel.config or {}
        custom_params = channel_config.get("custom_params", {})
        xp_base = int(resolve_param(custom_params, GParam.XP_BASE))
        xp_exponent = float(resolve_param(custom_params, GParam.XP_EXPONENT))
        xp_required = calculate_xp_required(stats["level"], base=xp_base, exponent=xp_exponent)
        stats["xp_to_next_level"] = max(int(xp_required), 0)

        rank = self.user_repo.get_user_rank(user.channel_id, user.id)
        stats["rank"] = rank

        chat_message = resolve_message(
            channel_config,
            MsgKey.PROFILE_STATS_DETAILED,
            username=user.username,
            level=stats["level"],
            xp=stats["xp"],
            xp_next=stats["xp_to_next_level"],
            rod_name=stats["rod_name"],
            luck_fmt=format_percent_signed(stats["luck_bonus"]),
            resist_fmt=format_percent_signed(stats["resist_bonus"]),
            xp_fmt=format_percent_signed(stats["xp_bonus_pct"]),
            current_mass=format_large_number_mass(stats["current_mass"]),
            total_fish_stat=stats["total_fish_stat"],
            rank=rank,
            total_mass=format_large_number_mass(stats["total_mass_stat"])
        )

        return FishStatsResponse(success=True, chat_message=chat_message, stats=stats)

    def get_channel_top(self, channel_id: str, limit: int = 10, mode: str = "current") -> FishTopResponse:
        mode = (mode or "current").lower()
        top_users = self.user_repo.get_top_users_by_channel(channel_id, limit=limit, mode=mode)
        if not top_users:
            return FishTopResponse(success=True, chat_message="No players in leaderboard yet.", top=[], mode=mode)

        top_entries = []
        top_lines = []
        for idx, player in enumerate(top_users, start=1):
            total_mass = float(player.total_mass_stat or 0.0)
            current_mass = float(player.current_mass or 0.0)
            total_fish = int(player.total_fish_stat or 0)
            top_entries.append({
                "rank": idx,
                "user_twitch_id": player.user_twitch_id,
                "username": player.username,
                "level": int(player.level or 1),
                "xp": int(player.xp or 0),
                "current_mass": current_mass,
                "total_fish_stat": total_fish,
                "total_mass_stat": total_mass
            })

            if mode == "alltime":
                score_fmt = format_large_number_mass(total_mass)
            elif mode == "catches":
                score_fmt = str(total_fish)
            elif mode == "level":
                score_fmt = f"Lvl {int(player.level or 1)} ({int(player.xp or 0)} XP)"
            else:
                score_fmt = format_large_number_mass(current_mass)

            top_lines.append(f"#{idx} {player.username} ({score_fmt})")

        channel_config = top_users[0].channel.config if top_users[0].channel else {}
        mode_label_map = {
            "alltime": "alltime",
            "catches": "catches",
            "level": "level",
            "current": "current",
        }
        chat_message = resolve_message(
            channel_config or {},
            MsgKey.PROFILE_TOP,
            mode=mode_label_map.get(mode, "current"),
            top_lines=" | ".join(top_lines)
        )
        return FishTopResponse(success=True, chat_message=chat_message, top=top_entries, mode=mode)

    def get_cooldown_status(
        self,
        channel_id: str,
        twitch_id: str,
        username: str,
        is_mod: bool = False,
        is_sub: bool = False
    ) -> FishCooldownResponse:
        channel = self.user_repo.get_channel(channel_id)
        channel_config = channel.config if channel else {}
        custom_params = (channel_config or {}).get("custom_params", {})
        cooldown_duration = self._resolve_cooldown_duration(custom_params, is_mod, is_sub)
        is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
        return self.presenter.build_cooldown_status_response(
            channel_config=channel_config or {},
            username=username,
            cooldown_duration=cooldown_duration,
            cooldown_left=seconds_left,
            is_active=is_active
        )
