# SPDX-License-Identifier: MIT

from __future__ import annotations

import contextlib
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from . import enums, utils
from .asset import Asset
from .auto_moderation import AutoModerationAction, AutoModerationTriggerMetadata
from .colour import Colour
from .invite import Invite
from .mixins import Hashable
from .object import Object
from .permissions import PermissionOverwrite, Permissions

__all__ = (
    "AuditLogChanges",
    "AuditLogDiff",
    "AuditLogEntry",
)


if TYPE_CHECKING:
    import datetime

    from . import abc
    from .auto_moderation import AutoModerationRule
    from .emoji import Emoji
    from .guild import Guild
    from .member import Member
    from .role import Role
    from .stage_instance import StageInstance
    from .sticker import GuildSticker
    from .threads import Thread
    from .types.audit_log import (
        AuditLogChange as AuditLogChangePayload,
        AuditLogEntry as AuditLogEntryPayload,
    )
    from .types.auto_moderation import (
        AutoModerationAction as AutoModerationActionPayload,
        AutoModerationTriggerMetadata as AutoModerationTriggerMetadataPayload,
    )
    from .types.channel import PermissionOverwrite as PermissionOverwritePayload
    from .types.role import Role as RolePayload
    from .types.snowflake import Snowflake
    from .user import User

    AuditTarget = Union[
        Guild,
        abc.GuildChannel,
        Member,
        User,
        Role,
        Invite,
        Emoji,
        StageInstance,
        GuildSticker,
        Thread,
        Object,
        AutoModerationRule,
        None,
    ]


def _transform_permissions(_entry: AuditLogEntry, data: str) -> Permissions:
    return Permissions(int(data))


def _transform_color(_entry: AuditLogEntry, data: int) -> Colour:
    return Colour(data)


def _transform_snowflake(_entry: AuditLogEntry, data: Snowflake) -> int:
    return int(data)


def _transform_channel(
    entry: AuditLogEntry, data: Optional[Snowflake]
) -> Optional[Union[abc.GuildChannel, Object]]:
    if data is None:
        return None
    return entry.guild.get_channel(int(data)) or Object(id=data)


def _transform_member_id(
    entry: AuditLogEntry, data: Optional[Snowflake]
) -> Union[Member, User, None]:
    if data is None:
        return None
    return entry._get_member(int(data))


def _transform_guild_id(entry: AuditLogEntry, data: Optional[Snowflake]) -> Optional[Guild]:
    if data is None:
        return None
    return entry._state._get_guild(int(data))


def _transform_overwrites(
    entry: AuditLogEntry, data: List[PermissionOverwritePayload]
) -> List[Tuple[Object, PermissionOverwrite]]:
    overwrites = []
    for elem in data:
        allow = Permissions(int(elem["allow"]))
        deny = Permissions(int(elem["deny"]))
        ow = PermissionOverwrite.from_pair(allow, deny)

        ow_type = elem["type"]
        ow_id = int(elem["id"])
        target = None
        if str(ow_type) == "0":
            target = entry.guild.get_role(ow_id)
        elif str(ow_type) == "1":
            target = entry._get_member(ow_id)

        if target is None:
            target = Object(id=ow_id)

        overwrites.append((target, ow))

    return overwrites


def _transform_icon(entry: AuditLogEntry, data: Optional[str]) -> Optional[Asset]:
    if data is None:
        return None
    return Asset._from_guild_icon(entry._state, entry.guild.id, data)


def _transform_avatar(entry: AuditLogEntry, data: Optional[str]) -> Optional[Asset]:
    if data is None:
        return None
    return Asset._from_avatar(entry._state, entry._target_id, data)  # type: ignore


def _guild_hash_transformer(path: str) -> Callable[[AuditLogEntry, Optional[str]], Optional[Asset]]:
    def _transform(entry: AuditLogEntry, data: Optional[str]) -> Optional[Asset]:
        if data is None:
            return None
        return Asset._from_guild_image(entry._state, entry.guild.id, data, path=path)

    return _transform


T = TypeVar("T")
E = TypeVar("E", bound=enums.Enum)


def _enum_transformer(enum: Type[E]) -> Callable[[AuditLogEntry, int], E]:
    def _transform(_entry: AuditLogEntry, data: int) -> E:
        return enums.try_enum(enum, data)

    return _transform


def _transform_type(entry: AuditLogEntry, data: int) -> Union[enums.ChannelType, enums.StickerType]:
    if entry.action.name.startswith("sticker_"):
        return enums.try_enum(enums.StickerType, data)
    return enums.try_enum(enums.ChannelType, data)


def _list_transformer(
    func: Callable[[AuditLogEntry, Any], T]
) -> Callable[[AuditLogEntry, Any], List[T]]:
    def _transform(entry: AuditLogEntry, data: Any) -> List[T]:
        if not data:
            return []
        return [func(entry, value) for value in data if value is not None]

    return _transform


def _transform_auto_moderation_action(
    _entry: AuditLogEntry, data: Optional[AutoModerationActionPayload]
) -> Optional[AutoModerationAction]:
    if data is None:
        return None
    return AutoModerationAction.from_data(data)


def _transform_auto_moderation_trigger_metadata(
    _entry: AuditLogEntry, data: Optional[AutoModerationTriggerMetadataPayload]
) -> Optional[AutoModerationTriggerMetadata]:
    if data is None:
        return None
    return AutoModerationTriggerMetadata.from_data(data)


def _transform_role(
    entry: AuditLogEntry, data: Optional[Snowflake]
) -> Optional[Union[Role, Object]]:
    if data is None:
        return None
    role = entry.guild.get_role(int(data))
    return role or Object(id=data)


class AuditLogDiff:
    def __len__(self) -> int:
        return len(self.__dict__)

    def __iter__(self) -> Generator[Tuple[str, Any], None, None]:
        yield from self.__dict__.items()

    def __repr__(self) -> str:
        values = " ".join("%s=%r" % item for item in self.__dict__.items())
        return f"<AuditLogDiff {values}>"

    if TYPE_CHECKING:

        def __getattr__(self, item: str) -> Any: ...

        def __setattr__(self, key: str, value: Any) -> Any: ...


Transformer = Callable[["AuditLogEntry", Any], Any]


class AuditLogChanges:
    # fmt: off
    TRANSFORMERS: ClassVar[Dict[str, Tuple[Optional[str], Optional[Transformer]]]] = {
        "verification_level":            (None, _enum_transformer(enums.VerificationLevel)),
        "explicit_content_filter":       (None, _enum_transformer(enums.ContentFilter)),
        "allow":                         (None, _transform_permissions),
        "deny":                          (None, _transform_permissions),
        "permissions":                   (None, _transform_permissions),
        "id":                            (None, _transform_snowflake),
        "color":                         ("colour", _transform_color),
        "owner_id":                      ("owner", _transform_member_id),
        "inviter_id":                    ("inviter", _transform_member_id),
        "channel_id":                    ("channel", _transform_channel),
        "afk_channel_id":                ("afk_channel", _transform_channel),
        "system_channel_id":             ("system_channel", _transform_channel),
        "widget_channel_id":             ("widget_channel", _transform_channel),
        "rules_channel_id":              ("rules_channel", _transform_channel),
        "public_updates_channel_id":     ("public_updates_channel", _transform_channel),
        "permission_overwrites":         ("overwrites", _transform_overwrites),
        "splash_hash":                   ("splash", _guild_hash_transformer("splashes")),
        "banner_hash":                   ("banner", _guild_hash_transformer("banners")),
        "discovery_splash_hash":         ("discovery_splash", _guild_hash_transformer("discovery-splashes")),
        "icon_hash":                     ("icon", _transform_icon),
        "avatar_hash":                   ("avatar", _transform_avatar),
        "rate_limit_per_user":           ("slowmode_delay", None),
        "guild_id":                      ("guild", _transform_guild_id),
        "tags":                          ("emoji", None),
        "default_message_notifications": ("default_notifications", _enum_transformer(enums.NotificationLevel)),
        "region":                        (None, _enum_transformer(enums.VoiceRegion)),
        "rtc_region":                    (None, _enum_transformer(enums.VoiceRegion)),
        "video_quality_mode":            (None, _enum_transformer(enums.VideoQualityMode)),
        "privacy_level":                 (None, _enum_transformer(enums.StagePrivacyLevel)),
        "format_type":                   (None, _enum_transformer(enums.StickerFormatType)),
        "entity_type":                   (None, _enum_transformer(enums.ScheduledEventEntityType)),
        "type":                          (None, _transform_type),
        "trigger_type":                  (None, _enum_transformer(enums.AutoModerationTriggerType)),
        "event_type":                    (None, _enum_transformer(enums.AutoModerationEventType)),
        "actions":                       (None, _list_transformer(_transform_auto_moderation_action)),
        "trigger_metadata":              (None, _transform_auto_moderation_trigger_metadata),
        "exempt_roles":                  (None, _list_transformer(_transform_role)),
        "exempt_channels":               (None, _list_transformer(_transform_channel)),
    }
    # fmt: on

    def __init__(self, entry: AuditLogEntry, data: List[AuditLogChangePayload]) -> None:
        self.before = AuditLogDiff()
        self.after = AuditLogDiff()

        for elem in data:
            attr = elem["key"]

            # special cases for role add/remove
            if attr == "$add":
                self._handle_role(self.before, self.after, entry, elem["new_value"])  # type: ignore
                continue
            if attr == "$remove":
                self._handle_role(self.after, self.before, entry, elem["new_value"])  # type: ignore
                continue

            try:
                key, transformer = self.TRANSFORMERS[attr]
            except (ValueError, KeyError):
                transformer = None
            else:
                if key:
                    attr = key

            transformer: Optional[Transformer]

            try:
                before = elem["old_value"]
            except KeyError:
                before = None
            else:
                if transformer:
                    before = transformer(entry, before)

            setattr(self.before, attr, before)

            try:
                after = elem["new_value"]
            except KeyError:
                after = None
            else:
                if transformer:
                    after = transformer(entry, after)

            setattr(self.after, attr, after)

        # add an alias
        if hasattr(self.after, "colour"):
            self.after.color = self.after.colour
            self.before.color = self.before.colour
        if hasattr(self.after, "expire_behavior"):
            self.after.expire_behaviour = self.after.expire_behavior
            self.before.expire_behaviour = self.before.expire_behavior

    def __repr__(self) -> str:
        return f"<AuditLogChanges before={self.before!r} after={self.after!r}>"

    def _handle_role(
        self,
        first: AuditLogDiff,
        second: AuditLogDiff,
        entry: AuditLogEntry,
        elem: List[RolePayload],
    ) -> None:
        if not hasattr(first, "roles"):
            first.roles = []

        data = []
        g: Guild = entry.guild

        for e in elem:
            role_id = int(e["id"])
            role = g.get_role(role_id)

            if role is None:
                role = Object(id=role_id)
                role.name = e["name"]  # type: ignore

            data.append(role)

        second.roles = data


class _AuditLogProxyMemberPrune:
    delete_member_days: int
    members_removed: int


class _AuditLogProxyMemberMoveOrMessageDelete:
    channel: abc.GuildChannel
    count: int


class _AuditLogProxyMemberDisconnect:
    count: int


class _AuditLogProxyPinAction:
    channel: abc.GuildChannel
    message_id: int


class _AuditLogProxyStageInstanceAction:
    channel: abc.GuildChannel


class _AuditLogProxyAutoModerationBlockMessage:
    channel: abc.GuildChannel
    rule_name: str
    rule_trigger_type: enums.AutoModerationTriggerType


class AuditLogEntry(Hashable):
    r"""Represents an Audit Log entry.

    You retrieve these via :meth:`Guild.audit_logs`.

    .. container:: operations

        .. describe:: x == y

            Checks if two entries are equal.

        .. describe:: x != y

            Checks if two entries are not equal.

        .. describe:: hash(x)

            Returns the entry's hash.

    .. versionchanged:: 1.7
        Audit log entries are now comparable and hashable.

    Attributes
    ----------
    guild: :class:`Guild`
        The guild to which the audit log belongs.
    action: :class:`AuditLogAction`
        The action that was done.
    user: :class:`abc.User`
        The user who initiated this action. Usually a :class:`Member`\, unless gone
        then it's a :class:`User`.
    id: :class:`int`
        The entry ID.
    reason: Optional[:class:`str`]
        The reason this action was done.
    extra: Any
        Extra information that this entry has that might be useful.
        For most actions, this is ``None``. However, in some cases it
        contains extra information. See :class:`AuditLogAction` for
        which actions have this field filled out.
    """

    extra: Union[
        _AuditLogProxyMemberPrune,
        _AuditLogProxyMemberMoveOrMessageDelete,
        _AuditLogProxyMemberDisconnect,
        _AuditLogProxyPinAction,
        _AuditLogProxyStageInstanceAction,
        _AuditLogProxyAutoModerationBlockMessage,
        Member,
        User,
        None,
        Role,
    ]

    def __init__(
        self,
        *,
        auto_moderation_rules: Dict[int, AutoModerationRule],
        users: Dict[int, User],
        data: AuditLogEntryPayload,
        guild: Guild,
    ) -> None:
        self._state = guild._state
        self.guild = guild
        self._auto_moderation_rules = auto_moderation_rules
        self._users = users
        self._from_data(data)

    def _from_data(self, data: AuditLogEntryPayload) -> None:
        self.action = enums.try_enum(enums.AuditLogAction, data["action_type"])
        self.id = int(data["id"])

        # this key is technically not usually present
        self.reason = data.get("reason")
        self.extra = data.get("options", {})  # type: ignore
        # I gave up trying to fix this

        elems: Dict[str, Any] = {}
        channel_id = int(self.extra["channel_id"]) if self.extra.get("channel_id", None) else None  # type: ignore

        if isinstance(self.action, enums.AuditLogAction) and self.extra:
            if self.action is enums.AuditLogAction.member_prune:
                # member prune has two keys with useful information
                self.extra = type(  # type: ignore
                    "_AuditLogProxy", (), {k: int(v) for k, v in self.extra.items()}  # type: ignore
                )()
            elif (
                self.action is enums.AuditLogAction.member_move
                or self.action is enums.AuditLogAction.message_delete
            ):
                elems = {
                    "count": int(self.extra["count"]),  # type: ignore
                }
            elif self.action is enums.AuditLogAction.member_disconnect:
                # The member disconnect action has a dict with some information
                elems = {
                    "count": int(self.extra["count"]),  # type: ignore
                }
            elif self.action.name.endswith("pin"):
                # the pin actions have a dict with some information
                elems = {
                    "message_id": int(self.extra["message_id"]),  # type: ignore
                }
            elif self.action.name.startswith("overwrite_"):
                # the overwrite_ actions have a dict with some information
                instance_id = int(self.extra["id"])  # type: ignore
                the_type = self.extra.get("type")  # type: ignore
                if the_type == "1":
                    self.extra = self._get_member(instance_id)
                elif the_type == "0":
                    role = self.guild.get_role(instance_id)
                    if role is None:
                        role = Object(id=instance_id)
                        role.name = self.extra.get("role_name")  # type: ignore
                    self.extra = role  # type: ignore
            elif self.action.name.startswith("stage_instance"):
                channel_id = int(self.extra["channel_id"])  # type: ignore
                elems = {"channel": self.guild.get_channel(channel_id) or Object(id=channel_id)}
            elif (
                self.action is enums.AuditLogAction.auto_moderation_block_message
                or self.action is enums.AuditLogAction.auto_moderation_flag_to_channel
                or self.action is enums.AuditLogAction.auto_moderation_user_communication_disabled
            ):
                elems = {
                    "rule_name": self.extra["auto_moderation_rule_name"],  # type: ignore
                    "rule_trigger_type": enums.try_enum(
                        enums.AutoModerationTriggerType,
                        int(self.extra["auto_moderation_rule_trigger_type"]),  # type: ignore
                    ),
                }

        # this just gets automatically filled in if present, this way prevents crashes if channel_id is None
        if channel_id and self.action:
            elems["channel"] = self.guild.get_channel_or_thread(channel_id) or Object(id=channel_id)

        if type(self.extra) is dict:  # type: ignore
            self.extra = type("_AuditLogProxy", (), elems)()  # type: ignore

        # this key is not present when the above is present, typically.
        # It's a list of { new_value: a, old_value: b, key: c }
        # where new_value and old_value are not guaranteed to be there depending
        # on the action type, so let's just fetch it for now and only turn it
        # into meaningful data when requested
        self._changes = data.get("changes", [])

        self.user = self._get_member(utils.get_as_snowflake(data, "user_id"))  # type: ignore
        self._target_id = utils.get_as_snowflake(data, "target_id")

    def _get_member(self, user_id: int) -> Union[Member, User, None]:
        return self.guild.get_member(user_id) or self._users.get(user_id)

    def __repr__(self) -> str:
        return f"<AuditLogEntry id={self.id} action={self.action} user={self.user!r}>"

    @utils.cached_property
    def created_at(self) -> datetime.datetime:
        """:class:`datetime.datetime`: Returns the entry's creation time in UTC."""
        return utils.snowflake_time(self.id)

    @utils.cached_property
    def target(self) -> AuditTarget:
        """Any: The target that got changed.
        The exact type of this depends on the action being done.
        """
        try:
            converter = getattr(self, "_convert_target_" + str(self.action.target_type))
        except AttributeError:
            if self._target_id is None:
                return None

            return Object(id=self._target_id)
        else:
            return converter(self._target_id)

    @utils.cached_property
    def category(self) -> Optional[enums.AuditLogActionCategory]:
        """Optional[:class:`AuditLogActionCategory`]: The category of the action, if applicable."""
        return self.action.category

    @utils.cached_property
    def changes(self) -> AuditLogChanges:
        """:class:`AuditLogChanges`: The list of changes this entry has."""
        obj = AuditLogChanges(self, self._changes)
        del self._changes
        return obj

    @utils.cached_property
    def before(self) -> AuditLogDiff:
        """:class:`AuditLogDiff`: The target's prior state."""
        return self.changes.before

    @utils.cached_property
    def after(self) -> AuditLogDiff:
        """:class:`AuditLogDiff`: The target's subsequent state."""
        return self.changes.after

    def _convert_target_guild(self, target_id: int) -> Guild:
        return self.guild

    def _convert_target_channel(self, target_id: int) -> Union[abc.GuildChannel, Object]:
        return self.guild.get_channel(target_id) or Object(id=target_id)

    def _convert_target_user(self, target_id: int) -> Union[Member, User, None]:
        return self._get_member(target_id)

    def _convert_target_role(self, target_id: int) -> Union[Role, Object]:
        return self.guild.get_role(target_id) or Object(id=target_id)

    def _convert_target_invite(self, target_id: int) -> Invite:
        # invites have target_id set to null
        # so figure out which change has the full invite data
        changeset = self.before if self.action is enums.AuditLogAction.invite_delete else self.after

        fake_payload = {
            "max_age": changeset.max_age,
            "max_uses": changeset.max_uses,
            "code": changeset.code,
            "temporary": changeset.temporary,
            "uses": changeset.uses,
        }

        obj = Invite(state=self._state, data=fake_payload, guild=self.guild, channel=changeset.channel)  # type: ignore
        with contextlib.suppress(AttributeError):
            obj.inviter = changeset.inviter

        return obj

    def _convert_target_emoji(self, target_id: int) -> Union[Emoji, Object]:
        return self._state.get_emoji(target_id) or Object(id=target_id)

    def _convert_target_message(self, target_id: int) -> Union[Member, User, None]:
        return self._get_member(target_id)

    def _convert_target_stage_instance(self, target_id: int) -> Union[StageInstance, Object]:
        return self.guild.get_stage_instance(target_id) or Object(id=target_id)

    def _convert_target_sticker(self, target_id: int) -> Union[GuildSticker, Object]:
        return self._state.get_sticker(target_id) or Object(id=target_id)

    def _convert_target_thread(self, target_id: int) -> Union[Thread, Object]:
        return self.guild.get_thread(target_id) or Object(id=target_id)

    def _convert_target_auto_moderation_rule(
        self, rule_id: int
    ) -> Union[AutoModerationRule, Object]:
        return self._auto_moderation_rules.get(rule_id) or Object(id=rule_id)
