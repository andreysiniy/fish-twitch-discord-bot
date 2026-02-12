from typing import Any, Dict, List


class ActionHandler:
    async def handle_engine_response(self, ctx, response: Dict[str, Any]) -> None:
        actions = response.get("actions") or []
        for action in actions:
            await self._execute_action(ctx, action)

        chat_message = response.get("chat_message")
        if chat_message and not actions:
            await ctx.send(chat_message)

    async def _execute_action(self, ctx, action: Dict[str, Any]) -> None:
        action_type = action.get("type", "")
        action_message = action.get("action_message")

        if action_message:
            await ctx.send(action_message)

        if action_type == "timeout":
            await self._handle_timeout(ctx, action)
        elif action_type == "play_sound":
            await self._handle_sound(action)
        elif action_type == "trigger_overlay":
            await self._handle_overlay(action)

    async def _handle_timeout(self, ctx, action: Dict[str, Any]) -> None:
        duration = action.get("duration", 60)
        target_user = action.get("target_user", "")
        reason = action.get("reason", "Fishing timeout")
        # Placeholder for Helix moderation call.
        print(f"[timeout] target={target_user} duration={duration} reason={reason}")

    async def _handle_sound(self, action: Dict[str, Any]) -> None:
        sound_id = action.get("sound_id")
        print(f"[sound] play={sound_id}")

    async def _handle_overlay(self, action: Dict[str, Any]) -> None:
        overlay_payload = action.get("payload", {})
        print(f"[overlay] payload={overlay_payload}")
