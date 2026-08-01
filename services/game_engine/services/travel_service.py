import re
from decimal import Decimal
from typing import Any

from core.messages import MsgKey, resolve_message
from domain.logic.mass import ZERO_MASS, quantize_mass
from domain.schemas.fishing import (
    FishTravelRequest,
    FishTravelResponse,
    LocationRequirementDTO,
    TravelLocationDTO,
)
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.user_repo import UserRepository


class TravelService:
    def __init__(self, user_repo: UserRepository, config_repo: ConfigRepository):
        self.user_repo = user_repo
        self.config_repo = config_repo

    def process_travel(self, request: FishTravelRequest) -> FishTravelResponse:
        user = self.user_repo.get_progress(request.user_id, request.channel_id)
        if not user:
            return FishTravelResponse(
                success=False,
                chat_message=resolve_message({}, MsgKey.ERR_NO_PROFILE, username=request.username),
                current_location_id="default",
                locations=[],
            )

        channel_conf = user.channel.config or {}
        pools = self.config_repo.get_locations(request.channel_id)
        if not pools:
            return FishTravelResponse(
                success=False,
                chat_message=resolve_message(
                    channel_conf, MsgKey.TRAVEL_NO_LOCATIONS, username=user.username
                ),
                current_location_id=user.current_location_id or "default",
                locations=[],
            )

        locations = self._build_locations(user, pools)
        location_number = self._extract_location_number(request)

        if location_number is None:
            return FishTravelResponse(
                success=True,
                chat_message=self._build_location_list_message(
                    channel_conf,
                    user.current_location_id or "default",
                    locations,
                    include_current_location=True,
                    include_hint=True,
                ),
                current_location_id=user.current_location_id or "default",
                locations=locations,
            )

        if location_number < 1 or location_number > len(locations):
            return FishTravelResponse(
                success=False,
                chat_message=resolve_message(
                    channel_conf, MsgKey.TRAVEL_FAIL_INVALID_NUMBER, location_number=location_number
                ),
                current_location_id=user.current_location_id or "default",
                locations=locations,
            )

        selected = locations[location_number - 1]
        if not selected.is_available:
            if selected.requirements.level > 0 and len(selected.missing_requirements) == 1:
                only_missing = selected.missing_requirements[0]
                if only_missing.startswith("Level "):
                    return FishTravelResponse(
                        success=False,
                        chat_message=resolve_message(
                            channel_conf,
                            MsgKey.TRAVEL_FAIL_LEVEL,
                            req_level=selected.requirements.level,
                            location_name=selected.location_name,
                            level=user.level,
                        ),
                        current_location_id=user.current_location_id or "default",
                        selected_location_id=selected.location_id,
                        locations=locations,
                    )

            return FishTravelResponse(
                success=False,
                chat_message=resolve_message(
                    channel_conf,
                    MsgKey.TRAVEL_FAIL_REQUIREMENTS,
                    location_name=selected.location_name,
                    requirements=", ".join(selected.missing_requirements),
                ),
                current_location_id=user.current_location_id or "default",
                selected_location_id=selected.location_id,
                locations=locations,
            )

        user.current_location_id = selected.location_id
        self.user_repo.save_progress(user)
        updated_locations = self._build_locations(user, pools)

        success_message = resolve_message(
            channel_conf, MsgKey.TRAVEL_SUCCESS, location_name=selected.location_name
        )
        return FishTravelResponse(
            success=True,
            chat_message=(
                f"{success_message} "
                f"{self._build_location_list_message(channel_conf, user.current_location_id, updated_locations)}"
            ),
            current_location_id=user.current_location_id,
            selected_location_id=selected.location_id,
            locations=updated_locations,
        )

    def _extract_location_number(self, request: FishTravelRequest) -> int | None:
        if request.location_number is not None:
            return int(request.location_number)

        if not request.user_input:
            return None

        match = re.search(r"(-?\d+)", request.user_input)
        if not match:
            return None
        return int(match.group(1))

    def _build_locations(self, user, pools: list[Any]) -> list[TravelLocationDTO]:
        locations: list[TravelLocationDTO] = []
        for index, pool in enumerate(pools, start=1):
            requirements = self._sanitize_requirements(pool.requirements)
            missing = self._get_missing_requirements(user, requirements)
            location_id = str(pool.location_id)
            location_name = self._resolve_pool_location_name(pool)
            locations.append(
                TravelLocationDTO(
                    number=index,
                    location_id=location_id,
                    location_name=location_name,
                    is_current=(location_id == (user.current_location_id or "default")),
                    is_available=len(missing) == 0,
                    requirements=LocationRequirementDTO(**requirements),
                    missing_requirements=missing,
                )
            )
        return locations

    def _sanitize_requirements(self, requirements: Any) -> dict[str, Decimal | int]:
        if not isinstance(requirements, dict):
            return {"level": 0, "total_fish_stat": 0, "total_mass_stat": ZERO_MASS}

        return {
            "level": max(int(requirements.get("level", 0) or 0), 0),
            "total_fish_stat": max(int(requirements.get("total_fish_stat", 0) or 0), 0),
            "total_mass_stat": max(
                quantize_mass(requirements.get("total_mass_stat", 0)),
                ZERO_MASS,
            ),
        }

    def _get_missing_requirements(
        self,
        user,
        requirements: dict[str, Decimal | int],
    ) -> list[str]:
        missing: list[str] = []
        req_level = int(requirements["level"])
        req_total_fish = int(requirements["total_fish_stat"])
        req_total_mass = quantize_mass(requirements["total_mass_stat"])

        if user.level < req_level:
            missing.append(f"Level {req_level} (current {user.level})")
        if user.total_fish_stat < req_total_fish:
            missing.append(f"Total fish {req_total_fish} (current {user.total_fish_stat})")
        current_total_mass = quantize_mass(user.total_mass_stat)
        if current_total_mass < req_total_mass:
            missing.append(f"Total mass {req_total_mass:.2f} (current {user.total_mass_stat:.2f})")
        return missing

    def _build_location_list_message(
        self,
        channel_conf: dict,
        current_location_id: str,
        locations: list[TravelLocationDTO],
        include_current_location: bool = False,
        include_hint: bool = False,
    ) -> str:
        location_parts = []
        for loc in locations:
            status = "CURRENT" if loc.is_current else ("OPEN" if loc.is_available else "LOCKED")
            req_parts = []
            if not loc.is_available and loc.requirements.level > 0:
                req_parts.append(f"lvl>={loc.requirements.level}")
            if not loc.is_available and loc.requirements.total_fish_stat > 0:
                req_parts.append(f"fish>={loc.requirements.total_fish_stat}")
            if not loc.is_available and loc.requirements.total_mass_stat > 0:
                req_parts.append(f"mass>={loc.requirements.total_mass_stat:.2f}")
            req_text = f" | req: {', '.join(req_parts)}" if req_parts else ""
            location_parts.append(f"{loc.number}. {loc.location_name} [{status}]{req_text}")

        list_message_key = MsgKey.TRAVEL_LIST if include_hint else MsgKey.TRAVEL_LIST_COMPACT
        list_message = resolve_message(
            channel_conf, list_message_key, locations=" | ".join(location_parts)
        )

        if include_current_location:
            current_location_name = next(
                (loc.location_name for loc in locations if loc.location_id == current_location_id),
                self._format_location_name(current_location_id),
            )
            current_location_message = resolve_message(
                channel_conf, MsgKey.CURRENT_LOCATION, location_name=current_location_name
            )
            return f"{current_location_message} {list_message}"

        return list_message

    def _resolve_pool_location_name(self, pool: Any) -> str:
        name = getattr(pool, "location_name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return self._format_location_name(str(getattr(pool, "location_id", "default")))

    def _format_location_name(self, location_id: str) -> str:
        raw = (location_id or "default").strip()
        if not raw:
            return "Default"
        return raw.replace("_", " ").replace("-", " ").title()
