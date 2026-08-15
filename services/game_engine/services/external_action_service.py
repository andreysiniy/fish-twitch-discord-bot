from domain.schemas.external_actions import ExternalActionRequest, ExternalActionResponse
from infrastructure.models import ChannelIntegration, EconomyOperation, OutboxEvent, UserProgress
from infrastructure.repositories.channel_repo import ChannelRepository


class ExternalActionService:
    def __init__(self, channel_repo: ChannelRepository):
        self.channel_repo = channel_repo
        self.db = channel_repo.db

    def queue(self, data: ExternalActionRequest, idempotency_key: str) -> ExternalActionResponse:
        existing = (
            self.db.query(EconomyOperation)
            .filter(EconomyOperation.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            status = "completed" if existing.state == "completed" else "queued"
            return ExternalActionResponse(status=status, operation_id=existing.id)

        channel = self.channel_repo.get_by_twitch_id(data.channel_id)
        if not channel:
            raise ValueError("Channel not found")
        integration = (
            self.db.query(ChannelIntegration)
            .filter(
                ChannelIntegration.channel_id == channel.id,
                ChannelIntegration.provider == "streamelements",
                ChannelIntegration.status.in_(("connected", "degraded")),
            )
            .first()
        )
        if not integration:
            raise ValueError("StreamElements integration is not configured")
        user = (
            self.db.query(UserProgress)
            .filter(
                UserProgress.channel_id == channel.id,
                UserProgress.username == data.target_username,
            )
            .first()
        )
        if not user:
            raise ValueError("Target user not found")

        operation = EconomyOperation(
            idempotency_key=idempotency_key,
            operation_type="reward_points",
            channel_id=channel.id,
            user_id=user.id,
            twitch_username=data.target_username,
            integration_id=integration.id,
            provider_channel_id_snapshot=integration.provider_channel_id,
            mass_delta=0,
            points_delta=data.amount,
            state="pending",
        )
        self.db.add(operation)
        self.db.flush()
        self.db.add(
            OutboxEvent(
                idempotency_key=f"economy:{operation.id}",
                topic="streamelements.points",
                payload={"operation_id": operation.id},
            )
        )
        self.db.flush()
        return ExternalActionResponse(status="queued", operation_id=operation.id)
