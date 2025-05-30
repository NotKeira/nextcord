# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import io
import re
from array import array
from os import PathLike
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    overload,
)

from . import utils
from .components import _component_factory
from .embeds import Embed
from .emoji import Emoji
from .enums import ChannelType, IntegrationType, MessageReferenceType, MessageType, try_enum
from .errors import HTTPException, InvalidArgument
from .file import File
from .flags import AttachmentFlags, MessageFlags
from .guild import Guild
from .member import Member
from .mixins import Hashable
from .object import Object
from .partial_emoji import PartialEmoji
from .reaction import Reaction
from .sticker import StickerItem
from .threads import Thread
from .user import User
from .utils import MISSING, escape_mentions

if TYPE_CHECKING:
    from typing_extensions import Self

    from .abc import (
        GuildChannel,
        Messageable,
        MessageableChannel,
        PartialMessageableChannel,
        Snowflake,
    )
    from .channel import TextChannel
    from .components import Component
    from .mentions import AllowedMentions
    from .role import Role
    from .state import ConnectionState
    from .types.components import Component as ComponentPayload
    from .types.embed import Embed as EmbedPayload
    from .types.interactions import (
        MessageInteraction as MessageInteractionPayload,
        MessageInteractionMetadata as MessageInteractionMetadataPayload,
    )
    from .types.member import Member as MemberPayload, UserWithMember as UserWithMemberPayload
    from .types.message import (
        Attachment as AttachmentPayload,
        Message as MessagePayload,
        MessageActivity as MessageActivityPayload,
        MessageApplication as MessageApplicationPayload,
        MessageReference as MessageReferencePayload,
        MessageSnapshot as MessageSnapshotPayload,
        Reaction as ReactionPayload,
        RoleSubscriptionData as RoleSubscriptionDataPayload,
    )
    from .types.threads import Thread as ThreadPayload, ThreadArchiveDuration
    from .types.user import User as UserPayload
    from .ui.view import View
    from .user import User

    EmojiInputType = Union[Emoji, PartialEmoji, str]

__all__ = (
    "Attachment",
    "Message",
    "PartialMessage",
    "MessageReference",
    "DeletedReferencedMessage",
    "MessageInteraction",
    "MessageInteractionMetadata",
    "MessageSnapshot",
    "MessageRoleSubscription",
)


def convert_emoji_reaction(emoji):
    if isinstance(emoji, Reaction):
        emoji = emoji.emoji

    if isinstance(emoji, Emoji):
        return f"{emoji.name}:{emoji.id}"
    if isinstance(emoji, PartialEmoji):
        return emoji._as_reaction()
    if isinstance(emoji, str):
        # Reactions can be in :name:id format, but not <:name:id>.
        # No existing emojis have <> in them, so this should be okay.
        return emoji.strip("<>")

    raise InvalidArgument(
        f"emoji argument must be str, Emoji, or Reaction not {emoji.__class__.__name__}."
    )


class Attachment(Hashable):
    """Represents an attachment from Discord.

    .. container:: operations

        .. describe:: str(x)

            Returns the URL of the attachment.

        .. describe:: x == y

            Checks if the attachment is equal to another attachment.

        .. describe:: x != y

            Checks if the attachment is not equal to another attachment.

        .. describe:: hash(x)

            Returns the hash of the attachment.

    .. versionchanged:: 1.7
        Attachment can now be casted to :class:`str` and is hashable.

    Attributes
    ----------
    id: :class:`int`
        The attachment ID.
    size: :class:`int`
        The attachment size in bytes.
    height: Optional[:class:`int`]
        The attachment's height, in pixels. Only applicable to images and videos.
    width: Optional[:class:`int`]
        The attachment's width, in pixels. Only applicable to images and videos.
    filename: :class:`str`
        The attachment's filename.
    url: :class:`str`
        The attachment URL. If the message this attachment was attached
        to is deleted, then this will 404.
    proxy_url: :class:`str`
        The proxy URL. This is a cached version of the :attr:`~Attachment.url` in the
        case of images. When the message is deleted, this URL might be valid for a few
        minutes or not valid at all.
    content_type: Optional[:class:`str`]
        The attachment's `media type <https://en.wikipedia.org/wiki/Media_type>`_

        .. versionadded:: 1.7
    description: Optional[:class:`str`]
        The attachment's description. This is used for alternative text in the Discord client.

        .. versionadded:: 2.0
    duration_secs: Optional[:class:`float`]
        The duration of the audio file (currently for voice messages).

        .. versionadded:: 3.0
    """

    __slots__ = (
        "id",
        "size",
        "height",
        "width",
        "filename",
        "url",
        "proxy_url",
        "_http",
        "content_type",
        "description",
        "duration_secs",
        "_waveform",
        "_cs_waveform",
        "_flags",
    )

    def __init__(self, *, data: AttachmentPayload, state: ConnectionState) -> None:
        self.id: int = int(data["id"])
        self.size: int = data["size"]
        self.height: Optional[int] = data.get("height")
        self.width: Optional[int] = data.get("width")
        self.filename: str = data["filename"]
        self.url: str = data.get("url")
        self.proxy_url: str = data.get("proxy_url")
        self._http = state.http
        self.content_type: Optional[str] = data.get("content_type")
        self.description: Optional[str] = data.get("description")
        self.duration_secs: Optional[float] = data.get("duration_secs")
        self._waveform: Optional[str] = data.get("waveform")
        self._flags: int = data.get("flags", 0)

    def is_spoiler(self) -> bool:
        """:class:`bool`: Whether this attachment contains a spoiler."""
        return self.filename.startswith("SPOILER_")

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} filename={self.filename!r} url={self.url!r}>"

    def __str__(self) -> str:
        return self.url or ""

    async def save(
        self,
        fp: Union[io.BufferedIOBase, PathLike, str],
        *,
        seek_begin: bool = True,
        use_cached: bool = False,
    ) -> int:
        """|coro|

        Saves this attachment into a file-like object.

        Parameters
        ----------
        fp: Union[:class:`io.BufferedIOBase`, :class:`os.PathLike`, :class:`str`]
            The file-like object to save this attachment to or the filename
            to use. If a filename is passed then a file is created with that
            filename and used instead.
        seek_begin: :class:`bool`
            Whether to seek to the beginning of the file after saving is
            successfully done.
        use_cached: :class:`bool`
            Whether to use :attr:`proxy_url` rather than :attr:`url` when downloading
            the attachment. This will allow attachments to be saved after deletion
            more often, compared to the regular URL which is generally deleted right
            after the message is deleted. Note that this can still fail to download
            deleted attachments if too much time has passed and it does not work
            on some types of attachments.

        Raises
        ------
        HTTPException
            Saving the attachment failed.
        NotFound
            The attachment was deleted.

        Returns
        -------
        :class:`int`
            The number of bytes written.
        """
        data = await self.read(use_cached=use_cached)
        if isinstance(fp, io.BufferedIOBase):
            written = fp.write(data)
            if seek_begin:
                fp.seek(0)
            return written

        with open(fp, "wb") as f:  # noqa: ASYNC230
            return f.write(data)

    async def read(self, *, use_cached: bool = False) -> bytes:
        """|coro|

        Retrieves the content of this attachment as a :class:`bytes` object.

        .. versionadded:: 1.1

        Parameters
        ----------
        use_cached: :class:`bool`
            Whether to use :attr:`proxy_url` rather than :attr:`url` when downloading
            the attachment. This will allow attachments to be saved after deletion
            more often, compared to the regular URL which is generally deleted right
            after the message is deleted. Note that this can still fail to download
            deleted attachments if too much time has passed and it does not work
            on some types of attachments.

        Raises
        ------
        HTTPException
            Downloading the attachment failed.
        Forbidden
            You do not have permissions to access this attachment
        NotFound
            The attachment was deleted.

        Returns
        -------
        :class:`bytes`
            The contents of the attachment.
        """
        url = self.proxy_url if use_cached else self.url
        return await self._http.get_from_cdn(url)

    async def to_file(
        self,
        *,
        filename: Optional[str] = MISSING,
        description: Optional[str] = MISSING,
        use_cached: bool = False,
        spoiler: bool = False,
        force_close: bool = True,
    ) -> File:
        """|coro|

        Converts the attachment into a :class:`File` suitable for sending via
        :meth:`abc.Messageable.send`.

        .. versionadded:: 1.3

        Parameters
        ----------
        filename: Optional[:class:`str`]
            The filename to use for the file. If not specified then the filename
            of the attachment is used instead.

            .. versionadded:: 2.0
        description: Optional[:class:`str`]
            The description to use for the file. If not specified then the
            description of the attachment is used instead.

            .. versionadded:: 2.0
        use_cached: :class:`bool`
            Whether to use :attr:`proxy_url` rather than :attr:`url` when downloading
            the attachment. This will allow attachments to be saved after deletion
            more often, compared to the regular URL which is generally deleted right
            after the message is deleted. Note that this can still fail to download
            deleted attachments if too much time has passed and it does not work
            on some types of attachments.

            .. versionadded:: 1.4
        spoiler: :class:`bool`
            Whether the file is a spoiler.

            .. versionadded:: 1.4
        force_close: :class:`bool`
            Whether to forcibly close the bytes used to create the file
            when ``.close()`` is called.
            This will also make the file bytes unusable by flushing it from
            memory after it is sent or used once.
            Keep this enabled if you don't wish to reuse the same bytes.

           .. versionadded:: 2.2

        Raises
        ------
        HTTPException
            Downloading the attachment failed.
        Forbidden
            You do not have permissions to access this attachment
        NotFound
            The attachment was deleted.

        Returns
        -------
        :class:`File`
            The attachment as a file suitable for sending.
        """

        data = await self.read(use_cached=use_cached)
        file_filename = filename if filename is not MISSING else self.filename
        file_description = description if description is not MISSING else self.description
        return File(
            io.BytesIO(data),
            filename=file_filename,
            description=file_description,
            spoiler=spoiler,
            force_close=force_close,
        )

    def to_dict(self) -> AttachmentPayload:
        result: AttachmentPayload = {
            "filename": self.filename,
            "id": self.id,
            "proxy_url": self.proxy_url,
            "size": self.size,
            "url": self.url,
            "spoiler": self.is_spoiler(),
        }
        if self.height:
            result["height"] = self.height
        if self.width:
            result["width"] = self.width
        if self.content_type:
            result["content_type"] = self.content_type
        if self.description:
            result["description"] = self.description
        if self.duration_secs:
            result["duration_secs"] = self.duration_secs
        if self._waveform:
            result["waveform"] = self._waveform
        return result

    @utils.cached_slot_property("_cs_waveform")
    def waveform(self) -> Optional[array[int]]:
        """Optional[array[:class:`int`]]: The base64 decoded data representing a sampled waveform
        (currently for voice messages).

        .. versionadded:: 3.0
        """
        if self._waveform is not None:
            return array("B", base64.b64decode(self._waveform))
        return None

    def flags(self) -> AttachmentFlags:
        """Optional[:class:`AttachmentFlags`]: The avaliable flags that the attachment has.

        .. versionadded:: 2.6
        """
        return AttachmentFlags._from_value(self._flags)

    def is_remix(self) -> bool:
        """:class:`bool`: Whether the attachment is remixed."""
        return self.flags.is_remix


class DeletedReferencedMessage:
    """A special sentinel type that denotes whether the
    resolved message referenced message had since been deleted.

    The purpose of this class is to separate referenced messages that could not be
    fetched and those that were previously fetched but have since been deleted.

    .. versionadded:: 1.6
    """

    __slots__ = ("_parent",)

    def __init__(self, parent: MessageReference) -> None:
        self._parent: MessageReference = parent

    def __repr__(self) -> str:
        return f"<DeletedReferencedMessage id={self.id} channel_id={self.channel_id} guild_id={self.guild_id!r}>"

    @property
    def id(self) -> int:
        """:class:`int`: The message ID of the deleted referenced message."""
        # the parent's message id won't be None here
        return self._parent.message_id  # type: ignore

    @property
    def channel_id(self) -> int:
        """:class:`int`: The channel ID of the deleted referenced message."""
        return self._parent.channel_id

    @property
    def guild_id(self) -> Optional[int]:
        """Optional[:class:`int`]: The guild ID of the deleted referenced message."""
        return self._parent.guild_id


class MessageReference:
    """Represents a reference to a :class:`~nextcord.Message`.

    .. versionadded:: 1.5

    .. versionchanged:: 1.6
        This class can now be constructed by users.

    Attributes
    ----------
    message_id: Optional[:class:`int`]
        The id of the message referenced.
    channel_id: :class:`int`
        The channel id of the message referenced.
    guild_id: Optional[:class:`int`]
        The guild id of the message referenced.
    fail_if_not_exists: :class:`bool`
        Whether replying to the referenced message should raise :class:`HTTPException`
        if the message no longer exists or Discord could not fetch the message.

        .. versionadded:: 1.7

    resolved: Optional[Union[:class:`Message`, :class:`DeletedReferencedMessage`]]
        The message that this reference resolved to. If this is ``None``
        then the original message was not fetched either due to the Discord API
        not attempting to resolve it or it not being available at the time of creation.
        If the message was resolved at a prior point but has since been deleted then
        this will be of type :class:`DeletedReferencedMessage`.

        Currently, this is mainly the replied to message when a user replies to a message.

        .. versionadded:: 1.6
    type: :class:`~nextcord.MessageReferenceType`
        The type of reference that the message is. Defaults to a reply.

        .. versionadded:: 3.0
    """

    __slots__ = (
        "message_id",
        "channel_id",
        "guild_id",
        "fail_if_not_exists",
        "resolved",
        "_state",
        "type",
    )

    def __init__(
        self,
        *,
        message_id: int,
        channel_id: int,
        type: MessageReferenceType = MessageReferenceType.default,
        guild_id: Optional[int] = None,
        fail_if_not_exists: bool = True,
    ) -> None:
        self._state: Optional[ConnectionState] = None
        self.type: MessageReferenceType = type
        self.resolved: Optional[Union[Message, DeletedReferencedMessage]] = None
        self.message_id: Optional[int] = message_id
        self.channel_id: int = channel_id
        self.guild_id: Optional[int] = guild_id
        self.fail_if_not_exists: bool = fail_if_not_exists

    @classmethod
    def with_state(cls, state: ConnectionState, data: MessageReferencePayload) -> Self:
        self = cls.__new__(cls)
        self.type = MessageReferenceType(data.get("type", 0))
        self.message_id = utils.get_as_snowflake(data, "message_id")
        self.channel_id = int(data.pop("channel_id"))
        self.guild_id = utils.get_as_snowflake(data, "guild_id")
        self.fail_if_not_exists = data.get("fail_if_not_exists", True)
        self._state = state
        self.resolved = None
        return self

    @classmethod
    def from_message(
        cls,
        message: Message,
        *,
        type: MessageReferenceType = MessageReferenceType.default,
        fail_if_not_exists: bool = True,
    ) -> Self:
        """Creates a :class:`MessageReference` from an existing :class:`~nextcord.Message`.

        .. versionadded:: 1.6

        Parameters
        ----------
        message: :class:`~nextcord.Message`
            The message to be converted into a reference.
        type: :class:`~nextcord.MessageReferenceType`
            The type of reference that the message is. Defaults to the ``reply`` type  if not provided.

            .. versionadded:: 3.0
        fail_if_not_exists: :class:`bool`
            Whether replying to the referenced message should raise :class:`HTTPException`
            if the message no longer exists or Discord could not fetch the message.

            .. versionadded:: 1.7

        Returns
        -------
        :class:`MessageReference`
            A reference to the message.
        """
        self = cls(
            type=type,
            message_id=message.id,
            channel_id=message.channel.id,
            guild_id=getattr(message.guild, "id", None),
            fail_if_not_exists=fail_if_not_exists,
        )
        self._state = message._state
        return self

    @property
    def cached_message(self) -> Optional[Message]:
        """Optional[:class:`~nextcord.Message`]: The cached message, if found in the internal message cache."""
        return self._state and self._state._get_message(self.message_id)

    @property
    def jump_url(self) -> str:
        """:class:`str`: Returns a URL that allows the client to jump to the referenced message.

        .. versionadded:: 1.7
        """
        guild_id = self.guild_id if self.guild_id is not None else "@me"
        return f"https://discord.com/channels/{guild_id}/{self.channel_id}/{self.message_id}"

    def __repr__(self) -> str:
        return f"<MessageReference message_id={self.message_id!r} channel_id={self.channel_id!r} guild_id={self.guild_id!r}>"

    def to_dict(self) -> MessageReferencePayload:
        result: MessageReferencePayload = (
            {"message_id": self.message_id} if self.message_id is not None else {}
        )
        result["type"] = self.type.value
        result["channel_id"] = self.channel_id
        result["fail_if_not_exists"] = self.fail_if_not_exists
        if self.guild_id is not None:
            result["guild_id"] = self.guild_id
        return result

    to_message_reference_dict = to_dict


def flatten_handlers(cls):
    prefix = len("_handle_")
    handlers = [
        (key[prefix:], value)
        for key, value in cls.__dict__.items()
        if key.startswith("_handle_") and key != "_handle_member"
    ]

    # store _handle_member last
    handlers.append(("member", cls._handle_member))
    cls._HANDLERS = handlers
    cls._CACHED_SLOTS = [attr for attr in cls.__slots__ if attr.startswith("_cs_")]
    return cls


class MessageSnapshot:
    """Represents a message reference snapshot.

    .. versionadded:: 3.0

    Attributes
    ----------
    type: :class:`MessageType`
        The type of message.
    content: :class:`str`
        The message's content.
    embeds: List[:class:`Embed`]
        The embeds the message contains.
    attachments: List[:class:`Attachment`]
        The attachments the message contains.
    timestamp: :class:`datetime.datetime`
        The timestamp when the message was sent.
    edited_timestamp: Optional[:class:`datetime.datetime`]
        The timestamp when the message was last edited.
        Returns ``None`` if it has not been edited.
    flags: :class:`MessageFlags`
        The message's flags.
    mentions: List[:class:`User`]
        A list of users that the message has mentioned.
    mention_roles: List[:class:`Object`]
        A list of role IDs that the message has mentioned.
    sticker_items: List[:class:`StickerItem`]
        A list of stickers packs that the message contains.
    components: List[:class:`Component`]
        A list of components that the message contains.
    """

    def __init__(self, *, data: MessageSnapshotPayload, state: ConnectionState) -> None:
        self._message = data["message"]
        self._state = state

        self.type: MessageType = MessageType(self._message["type"])
        self.content: str = self._message["content"]
        self.embeds: List[Embed] = [Embed.from_dict(d) for d in self._message.get("embeds", [])]
        self.attachments: List[Attachment] = [
            Attachment(data=a, state=self._state) for a in self._message.get("attachments", [])
        ]
        self.timestamp: datetime.datetime = utils.parse_time(self._message["timestamp"])
        self.edited_timestamp: datetime.datetime | None = utils.parse_time(
            self._message.get("edited_timestamp")
        )
        self.flags: MessageFlags = MessageFlags._from_value(self._message.get("flags", 0))
        self.mentions: List[User] = [
            User(state=self._state, data=u) for u in self._message.get("mentions", [])
        ]
        self.mention_roles: List[Object] = [
            Object(r) for r in self._message.get("mention_roles", [])
        ]
        self.sticker_items: List[StickerItem] = [
            StickerItem(state=self._state, data=s) for s in self._message.get("sticker_items", [])
        ]
        self.components: List[Component] = [
            _component_factory(c) for c in self._message.get("components", [])
        ]


class MessageInteraction(Hashable):
    """Represents a message's interaction data.

    A message's interaction data is a property of a message when the message
    is a response to an interaction from any bot.

    .. versionadded:: 2.1

    .. container:: operations

        .. describe:: x == y

            Checks if two message interactions are equal.

        .. describe:: x != y

            Checks if two interaction messages are not equal.

        .. describe:: hash(x)

            Returns the message interaction's hash.

    Attributes
    ----------
    data: Dict[:class:`str`, Any]
        The raw data from the interaction.
    id: :class:`int`
        The interaction's ID.
    type: :class:`InteractionType`
        The interaction type.
    name: :class:`str`
        The name of the application command.
    user: Union[:class:`User`, :class:`Member`]
        The :class:`User` who invoked the interaction or :class:`Member` if the interaction
        occurred in a guild.

    .. warning::
        This class is deprecated, use :attr:`Message.interaction_metadata` instead.
    .. deprecated:: 3.0
    """

    __slots__ = (
        "_state",
        "data",
        "id",
        "type",
        "name",
        "user",
    )

    def __init__(
        self, *, data: MessageInteractionPayload, guild: Optional[Guild], state: ConnectionState
    ) -> None:
        self._state: ConnectionState = state

        self.data: MessageInteractionPayload = data
        self.id: int = int(data["id"])
        self.type: int = data["type"]
        self.name: str = data["name"]
        if "member" in data and guild is not None:
            self.user = Member(
                state=self._state, guild=guild, data={**data["member"], "user": data["user"]}
            )
        else:
            self.user = self._state.create_user(data=data["user"])

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id} type={self.type} name={self.name} user={self.user!r}>"

    @property
    def created_at(self) -> datetime.datetime:
        """:class:`datetime.datetime`: The interaction's creation time in UTC."""
        return utils.snowflake_time(self.id)


class MessageRoleSubscription:
    """Represents a message's role subscription information.

    This is accessed through the :attr:`Message.role_subscription` attribute if the :attr:`Message.type` is :attr:`MessageType.role_subscription_purchase`.

    .. versionadded:: 3.2

    Attributes
    ----------
    role_subscription_listing_id: :class:`int`
        The ID of the SKU and listing that the user is subscribed to.
    tier_name: :class:`str`
        The name of the tier that the user is subscribed to.
    total_months_subscribed: :class:`int`
        The cumulative number of months that the user has been subscribed for.
    is_renewal: :class:`bool`
        Whether this notification is for a renewal rather than a new purchase.
    """

    __slots__ = (
        "role_subscription_listing_id",
        "tier_name",
        "total_months_subscribed",
        "is_renewal",
    )

    def __init__(self, data: RoleSubscriptionDataPayload) -> None:
        self.role_subscription_listing_id: int = int(data["role_subscription_listing_id"])
        self.tier_name: str = data["tier_name"]
        self.total_months_subscribed: int = data["total_months_subscribed"]
        self.is_renewal: bool = data["is_renewal"]


class MessageInteractionMetadata(Hashable):
    """Represents a message's interaction metadata.

    A message's interaction metadata is a property of a message when the message
    is a response to an interaction from any bot.

    .. versionadded:: 3.0

    .. container:: operations

        .. describe:: x == y

            Checks if two message interactions are equal.

        .. describe:: x != y

            Checks if two interaction messages are not equal.

        .. describe:: hash(x)

            Returns the message interaction's hash.

    Attributes
    ----------
    data: Dict[:class:`str`, Any]
        The raw data from the interaction metadata.
    id: :class:`int`
        The interaction's ID.
    type: :class:`InteractionType`
        The interaction type.
    user: Union[:class:`User`, :class:`Member`]
        The :class:`User` who invoked the interaction or :class:`Member` if the interaction
        occurred in a guild and that member is cached.
    authorizing_integration_owners: Dict[:class:`IntegrationType`, :class:`str`]
        Mapping of installation contexts that the interaction was authorized for to related user or guild IDs.
        You can find out about this field in the `official Discord documentation`__.

        .. _integration_owners_docs: https://discord.com/developers/docs/interactions/receiving-and-responding#interaction-object-authorizing-integration-owners-object

        __ integration_owners_docs_

        .. versionadded:: 3.0
    name: Optional[:class:`str`]
        The name of the application command.
    original_response_message_id: Optional[:class:`int`]
        The ID of the original response message, present only on follow-up messages.
    interacted_message_id: Optional[:class:`int`]
        The ID of the message that contained the interactive component, present only on messages created from component interactions.
    triggering_interaction_metadata: Optional[:class:`MessageInteractionMetadata`]
        Metadata for the interaction that was used to open the modal, present only on modal submit interactions.
    """

    __slots__ = (
        "_state",
        "data",
        "id",
        "type",
        "user",
        "authorizing_integration_owners",
        "name",
        "original_response_message_id",
        "interacted_message_id",
        "triggering_interaction_metadata",
    )

    def __init__(
        self,
        *,
        data: MessageInteractionMetadataPayload,
        guild: Optional[Guild],
        state: ConnectionState,
    ) -> None:
        self._state: ConnectionState = state

        self.data: MessageInteractionMetadataPayload = data
        self.id: int = int(data["id"])
        self.type: int = data["type"]

        # No member data is provided, retrieve from cache if possible
        self.user = None if guild is None else guild.get_member(int(data["user"]["id"]))
        if self.user is None:
            self.user = self._state.create_user(data=data["user"])

        self.authorizing_integration_owners: Dict[IntegrationType, int] = {
            IntegrationType(int(integration_type)): int(details)
            for integration_type, details in data["authorizing_integration_owners"].items()
        }

        self.name: Optional[str] = data.get("name")
        self.original_response_message_id: Optional[int] = (
            int(data["original_response_message_id"])
            if "original_response_message_id" in data
            else None
        )
        self.interacted_message_id: Optional[int] = (
            int(data["interacted_message_id"]) if "interacted_message_id" in data else None
        )
        self.triggering_interaction_metadata: Optional[MessageInteractionMetadata] = (
            MessageInteractionMetadata(
                data=data["triggering_interaction_metadata"], guild=guild, state=state
            )
            if "triggering_interaction_metadata" in data
            else None
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id} type={self.type} user={self.user!r} name={self.name!r}>"

    @property
    def created_at(self) -> datetime.datetime:
        """:class:`datetime.datetime`: The interaction's creation time in UTC."""
        return utils.snowflake_time(self.id)

    @property
    def cached_original_response_message(self) -> Optional[Message]:
        """Optional[:class:`~nextcord.Message`]: The original response message, if found in the internal message cache."""
        return self._state._get_message(self.original_response_message_id)

    @property
    def cached_interacted_message(self) -> Optional[Message]:
        """Optional[:class:`~nextcord.Message`]: The interacted message, if found in the internal message cache."""
        return self._state._get_message(self.interacted_message_id)


@flatten_handlers
class Message(Hashable):
    r"""Represents a message from Discord.

    .. container:: operations

        .. describe:: x == y

            Checks if two messages are equal.

        .. describe:: x != y

            Checks if two messages are not equal.

        .. describe:: hash(x)

            Returns the message's hash.

    Attributes
    ----------
    tts: :class:`bool`
        Specifies if the message was done with text-to-speech.
        This can only be accurately received in :func:`on_message` due to
        a discord limitation.
    type: :class:`MessageType`
        The type of message. In most cases this should not be checked, but it is helpful
        in cases where it might be a system message for :attr:`system_content`.
    author: Union[:class:`Member`, :class:`abc.User`]
        A :class:`Member` that sent the message. If :attr:`channel` is a
        private channel or the user has the left the guild, then it is a :class:`User` instead.
    content: :class:`str`
        The actual contents of the message.
    nonce: Optional[Union[:class:`str`, :class:`int`]]
        The value used by the discord guild and the client to verify that the message is successfully sent.
        This is not stored long term within Discord's servers and is only used ephemerally.
    embeds: List[:class:`Embed`]
        A list of embeds the message has.
    channel: Union[:class:`TextChannel`, :class:`Thread`, :class:`DMChannel`, :class:`GroupChannel`, :class:`PartialMessageable`]
        The :class:`TextChannel` or :class:`Thread` that the message was sent from.
        Could be a :class:`DMChannel` or :class:`GroupChannel` if it's a private message.
    reference: Optional[:class:`~nextcord.MessageReference`]
        The message that this message references. This is only applicable to messages of
        type :attr:`MessageType.pins_add`, crossposted messages created by a
        followed channel integration, or message replies.

        .. versionadded:: 1.5

    mention_everyone: :class:`bool`
        Specifies if the message mentions everyone.

        .. note::

            This does not check if the ``@everyone`` or the ``@here`` text is in the message itself.
            Rather this boolean indicates if either the ``@everyone`` or the ``@here`` text is in the message
            **and** it did end up mentioning.
    mentions: List[:class:`abc.User`]
        A list of :class:`Member` that were mentioned. If the message is in a private message
        then the list will be of :class:`User` instead. For messages that are not of type
        :attr:`MessageType.default`\, this array can be used to aid in system messages.
        For more information, see :attr:`system_content`.

        .. warning::

            The order of the mentions list is not in any particular order so you should
            not rely on it. This is a Discord limitation, not one with the library.
    channel_mentions: List[:class:`abc.GuildChannel`]
        A list of :class:`abc.GuildChannel` that were mentioned. If the message is in a private message
        then the list is always empty.
    role_mentions: List[:class:`Role`]
        A list of :class:`Role` that were mentioned. If the message is in a private message
        then the list is always empty.
    id: :class:`int`
        The message ID.
    webhook_id: Optional[:class:`int`]
        If this message was sent by a webhook, then this is the webhook ID's that sent this
        message.
    attachments: List[:class:`Attachment`]
        A list of attachments given to a message.
    pinned: :class:`bool`
        Specifies if the message is currently pinned.
    flags: :class:`MessageFlags`
        Extra features of the message.

        .. versionadded:: 1.3

    reactions : List[:class:`Reaction`]
        Reactions to a message. Reactions can be either custom emoji or standard unicode emoji.
    activity: Optional[:class:`dict`]
        The activity associated with this message. Sent with Rich-Presence related messages that for
        example, request joining, spectating, or listening to or with another member.

        It is a dictionary with the following optional keys:

        - ``type``: An integer denoting the type of message activity being requested.
        - ``party_id``: The party ID associated with the party.
    application: Optional[:class:`dict`]
        The rich presence enabled application associated with this message.

        It is a dictionary with the following keys:

        - ``id``: A string representing the application's ID.
        - ``name``: A string representing the application's name.
        - ``description``: A string representing the application's description.
        - ``icon``: A string representing the icon ID of the application.
        - ``cover_image``: A string representing the embed's image asset ID.
    stickers: List[:class:`StickerItem`]
        A list of sticker items given to the message.

        .. versionadded:: 1.6
    components: List[:class:`Component`]
        A list of components in the message.

        .. versionadded:: 2.0
    guild: Optional[:class:`Guild`]
        The guild that the message belongs to, if applicable.
    interaction: Optional[:class:`MessageInteraction`]
        The interaction data of a message, if applicable.

        .. warning::
            This field is deprecated, use ``interaction_metadata`` instead.
        .. deprecated:: 3.0
    interaction_metadata: Optional[:class:`MessageInteractionMetadata`]
        The interaction metadata of a message. Present if the message is sent as a result of an interaction.

        .. versionadded:: 3.0
    snapshots: List[:class:`MessageSnapshot`]
        A list of message snapshots that the message contains.

        .. versionadded:: 3.0
    role_subscription: Optional[:class:`MessageRoleSubscription`]
        The role subscription data of a message, if applicable.

        .. versionadded:: 3.2
    """

    __slots__ = (
        "_state",
        "_edited_timestamp",
        "_cs_channel_mentions",
        "_cs_raw_mentions",
        "_cs_clean_content",
        "_cs_raw_channel_mentions",
        "_cs_raw_role_mentions",
        "_cs_system_content",
        "tts",
        "content",
        "channel",
        "webhook_id",
        "mention_everyone",
        "embeds",
        "id",
        "interaction",
        "interaction_metadata",
        "mentions",
        "author",
        "attachments",
        "nonce",
        "pinned",
        "role_mentions",
        "type",
        "flags",
        "reactions",
        "reference",
        "application",
        "activity",
        "stickers",
        "components",
        "_background_tasks",
        "guild",
        "snapshots",
        "role_subscription",
    )

    if TYPE_CHECKING:
        _HANDLERS: ClassVar[List[Tuple[str, Callable[..., None]]]]
        _CACHED_SLOTS: ClassVar[List[str]]
        guild: Optional[Guild]
        reference: Optional[MessageReference]
        mentions: List[Union[User, Member]]
        author: Union[User, Member]
        role_mentions: List[Role]

    def __init__(
        self,
        *,
        state: ConnectionState,
        channel: MessageableChannel,
        data: MessagePayload,
    ) -> None:
        self._state: ConnectionState = state
        self.id: int = int(data["id"])
        self.webhook_id: Optional[int] = utils.get_as_snowflake(data, "webhook_id")
        self.reactions: List[Reaction] = [
            Reaction(message=self, data=d) for d in data.get("reactions", [])
        ]
        self.attachments: List[Attachment] = [
            Attachment(data=a, state=self._state) for a in data["attachments"]
        ]
        self.embeds: List[Embed] = [Embed.from_dict(a) for a in data["embeds"]]
        self.application: Optional[MessageApplicationPayload] = data.get("application")
        self.activity: Optional[MessageActivityPayload] = data.get("activity")
        self.channel: MessageableChannel = channel
        self._edited_timestamp: Optional[datetime.datetime] = utils.parse_time(
            data["edited_timestamp"]
        )
        self.type: MessageType = try_enum(MessageType, data["type"])
        self.pinned: bool = data["pinned"]
        self.flags: MessageFlags = MessageFlags._from_value(data.get("flags", 0))
        self.mention_everyone: bool = data["mention_everyone"]
        self.tts: bool = data["tts"]
        self.content: str = data["content"]
        self.nonce: Optional[Union[int, str]] = data.get("nonce")
        self.stickers: List[StickerItem] = [
            StickerItem(data=d, state=state) for d in data.get("sticker_items", [])
        ]
        self.components: List[Component] = [
            _component_factory(d) for d in data.get("components", [])
        ]
        self._background_tasks: Set[asyncio.Task[None]] = set()

        try:
            # if the channel doesn't have a guild attribute, we handle that
            self.guild = channel.guild  # type: ignore
        except AttributeError:
            if getattr(channel, "type", None) not in (ChannelType.group, ChannelType.private):
                self.guild = state._get_guild(utils.get_as_snowflake(data, "guild_id"))
            else:
                self.guild = None

        if (
            (thread_data := data.get("thread"))
            and not self.thread
            and isinstance(self.guild, Guild)
        ):
            self.guild._store_thread(thread_data)

        self.snapshots: List[MessageSnapshot] = [
            MessageSnapshot(state=self._state, data=s) for s in data.get("message_snapshots", [])
        ]

        self.reference = None
        if ref := data.get("message_reference"):
            self.reference = ref = MessageReference.with_state(state, ref)

            if "referenced_message" in data:
                resolved = data["referenced_message"]
                if resolved is None:
                    ref.resolved = DeletedReferencedMessage(ref)
                else:
                    # Right now the channel IDs match but maybe in the future they won't.
                    if ref.channel_id == channel.id:
                        chan = channel
                    else:
                        chan, _ = state._get_guild_channel(resolved)

                    # the channel will be the correct type here
                    ref.resolved = self.__class__(channel=chan, data=resolved, state=state)  # type: ignore

        for handler in ("author", "member", "mentions", "mention_roles"):
            if handler in data:
                # Even after this check, pyright believes this may error out.
                getattr(self, f"_handle_{handler}")(data[handler])  # pyright: ignore

        self.interaction: Optional[MessageInteraction] = (
            MessageInteraction(data=data["interaction"], guild=self.guild, state=self._state)
            if "interaction" in data
            else None
        )
        self.interaction_metadata: Optional[MessageInteractionMetadata] = (
            MessageInteractionMetadata(
                data=data["interaction_metadata"], guild=self.guild, state=self._state
            )
            if "interaction_metadata" in data
            else None
        )
        self.role_subscription: Optional[MessageRoleSubscription] = (
            MessageRoleSubscription(data=data["role_subscription_data"])
            if "role_subscription_data" in data
            else None
        )

    def __repr__(self) -> str:
        name = self.__class__.__name__
        return f"<{name} id={self.id} channel={self.channel!r} type={self.type!r} author={self.author!r} flags={self.flags!r}>"

    def _try_patch(self, data, key, transform=None) -> None:
        try:
            value = data[key]
        except KeyError:
            pass
        else:
            if transform is None:
                setattr(self, key, value)
            else:
                setattr(self, key, transform(value))

    def _add_reaction(self, data, emoji: Emoji | PartialEmoji | str, user_id) -> Reaction:
        finder: Callable[[Reaction], bool] = lambda r: r.emoji == emoji
        reaction = utils.find(finder, self.reactions)
        is_me = data["me"] = user_id == self._state.self_id

        if reaction is None:
            reaction = Reaction(message=self, data=data, emoji=emoji)
            self.reactions.append(reaction)
        else:
            reaction.count += 1
            if is_me:
                reaction.me = is_me

        return reaction

    def _remove_reaction(
        self, data: ReactionPayload, emoji: EmojiInputType, user_id: int
    ) -> Reaction:
        reaction = utils.find(lambda r: r.emoji == emoji, self.reactions)

        if reaction is None:
            # already removed?
            raise ValueError("Emoji already removed?")

        # if reaction isn't in the list, we crash. This means discord
        # sent bad data, or we stored improperly
        reaction.count -= 1

        if user_id == self._state.self_id:
            reaction.me = False
        if reaction.count == 0:
            # this raises ValueError if something went wrong as well.
            self.reactions.remove(reaction)

        return reaction

    def _clear_emoji(self, emoji) -> Optional[Reaction]:
        to_check = str(emoji)
        for index, reaction in enumerate(self.reactions):  # noqa: B007
            if str(reaction.emoji) == to_check:
                break
        else:
            # didn't find anything so just return
            return None

        del self.reactions[index]
        return reaction

    def _update(self, data) -> None:
        # In an update scheme, 'author' key has to be handled before 'member'
        # otherwise they overwrite each other which is undesirable.
        # Since there's no good way to do this we have to iterate over every
        # handler rather than iterating over the keys which is a little slower
        for key, handler in self._HANDLERS:
            try:
                value = data[key]
            except KeyError:
                continue
            else:
                handler(self, value)

        # clear the cached properties
        for attr in self._CACHED_SLOTS:
            with contextlib.suppress(AttributeError):
                delattr(self, attr)

    def _handle_edited_timestamp(self, value: str) -> None:
        self._edited_timestamp = utils.parse_time(value)

    def _handle_pinned(self, value: bool) -> None:
        self.pinned = value

    def _handle_flags(self, value: int) -> None:
        self.flags = MessageFlags._from_value(value)

    def _handle_application(self, value: MessageApplicationPayload) -> None:
        self.application = value

    def _handle_activity(self, value: MessageActivityPayload) -> None:
        self.activity = value

    def _handle_mention_everyone(self, value: bool) -> None:
        self.mention_everyone = value

    def _handle_tts(self, value: bool) -> None:
        self.tts = value

    def _handle_type(self, value: int) -> None:
        self.type = try_enum(MessageType, value)

    def _handle_content(self, value: str) -> None:
        self.content = value

    def _handle_attachments(self, value: List[AttachmentPayload]) -> None:
        self.attachments = [Attachment(data=a, state=self._state) for a in value]

    def _handle_embeds(self, value: List[EmbedPayload]) -> None:
        self.embeds = [Embed.from_dict(data) for data in value]

    def _handle_nonce(self, value: Union[str, int]) -> None:
        self.nonce = value

    def _handle_author(self, author: UserPayload) -> None:
        self.author = self._state.store_user(author)
        if isinstance(self.guild, Guild):
            found = self.guild.get_member(self.author.id)
            if found is not None:
                self.author = found

    def _handle_member(self, member: MemberPayload) -> None:
        # The gateway now gives us full Member objects sometimes with the following keys
        # deaf, mute, joined_at, roles
        # For the sake of performance I'm going to assume that the only
        # field that needs *updating* would be the joined_at field.
        # If there is no Member object (for some strange reason), then we can upgrade
        # ourselves to a more "partial" member object.
        author = self.author
        try:
            # Update member reference
            author._update_from_message(member)  # type: ignore
        except AttributeError:
            # It's a user here
            # TODO: consider adding to cache here
            self.author = Member._from_message(message=self, data=member)

    def _handle_mentions(self, mentions: List[UserWithMemberPayload]) -> None:
        self.mentions = r = []
        guild = self.guild
        state = self._state
        if not isinstance(guild, Guild):
            self.mentions = [state.store_user(m) for m in mentions]
            return

        for mention in filter(None, mentions):
            id_search = int(mention["id"])
            member = guild.get_member(id_search)
            if member is not None:
                r.append(member)
            else:
                r.append(Member._try_upgrade(data=mention, guild=guild, state=state))

    def _handle_mention_roles(self, role_mentions: List[int]) -> None:
        self.role_mentions = []
        if isinstance(self.guild, Guild):
            for role_id in map(int, role_mentions):
                role = self.guild.get_role(role_id)
                if role is not None:
                    self.role_mentions.append(role)

    def _handle_components(self, components: List[ComponentPayload]) -> None:
        self.components = [_component_factory(d) for d in components]

    def _handle_thread(self, thread: Optional[ThreadPayload]) -> None:
        if thread:
            self.guild._store_thread(thread)  # type: ignore

    def _rebind_cached_references(
        self, new_guild: Guild, new_channel: Union[TextChannel, Thread]
    ) -> None:
        self.guild = new_guild
        self.channel = new_channel

    @utils.cached_slot_property("_cs_raw_mentions")
    def raw_mentions(self) -> List[int]:
        """List[:class:`int`]: A property that returns an array of user IDs matched with
        the syntax of ``<@user_id>`` in the message content.

        This allows you to receive the user IDs of mentioned users
        even in a private message context.
        """
        return utils.parse_raw_mentions(self.content)

    @utils.cached_slot_property("_cs_raw_channel_mentions")
    def raw_channel_mentions(self) -> List[int]:
        """List[:class:`int`]: A property that returns an array of channel IDs matched with
        the syntax of ``<#channel_id>`` in the message content.
        """
        return utils.parse_raw_channel_mentions(self.content)

    @utils.cached_slot_property("_cs_raw_role_mentions")
    def raw_role_mentions(self) -> List[int]:
        """List[:class:`int`]: A property that returns an array of role IDs matched with
        the syntax of ``<@&role_id>`` in the message content.
        """
        return utils.parse_raw_role_mentions(self.content)

    @utils.cached_slot_property("_cs_channel_mentions")
    def channel_mentions(self) -> List[GuildChannel]:
        if self.guild is None:
            return []
        it = filter(None, map(self.guild.get_channel, self.raw_channel_mentions))
        return utils.unique(it)

    @utils.cached_slot_property("_cs_clean_content")
    def clean_content(self) -> str:
        """:class:`str`: A property that returns the content in a "cleaned up"
        manner. This basically means that mentions are transformed
        into the way the client shows it. e.g. ``<#id>`` will transform
        into ``#name``.

        This will also transform @everyone and @here mentions into
        non-mentions.

        .. note::

            This *does not* affect markdown. If you want to escape
            or remove markdown then use :func:`utils.escape_markdown` or :func:`utils.remove_markdown`
            respectively, along with this function.
        """

        transformations = {
            re.escape(f"<#{channel.id}>"): "#" + channel.name for channel in self.channel_mentions
        }

        mention_transforms = {
            re.escape(f"<@{member.id}>"): "@" + member.display_name for member in self.mentions
        }

        # add the <@!user_id> cases as well..
        second_mention_transforms = {
            re.escape(f"<@!{member.id}>"): "@" + member.display_name for member in self.mentions
        }

        transformations.update(mention_transforms)
        transformations.update(second_mention_transforms)

        if self.guild is not None:
            role_transforms = {
                re.escape(f"<@&{role.id}>"): "@" + role.name for role in self.role_mentions
            }
            transformations.update(role_transforms)

        def repl(obj):
            return transformations.get(re.escape(obj.group(0)), "")

        pattern = re.compile("|".join(transformations.keys()))
        result = pattern.sub(repl, self.content)
        return escape_mentions(result)

    @property
    def created_at(self) -> datetime.datetime:
        """:class:`datetime.datetime`: The message's creation time in UTC."""
        return utils.snowflake_time(self.id)

    @property
    def edited_at(self) -> Optional[datetime.datetime]:
        """Optional[:class:`datetime.datetime`]: An aware UTC datetime object containing the edited time of the message."""
        return self._edited_timestamp

    @property
    def jump_url(self) -> str:
        """:class:`str`: Returns a URL that allows the client to jump to this message."""
        guild_id = getattr(self.guild, "id", "@me")
        return f"https://discord.com/channels/{guild_id}/{self.channel.id}/{self.id}"

    @property
    def thread(self) -> Optional[Thread]:
        """Optional[:class:`Thread`]: The thread started from this message. None if no thread was started."""
        if not isinstance(self.guild, Guild):
            return None

        return self.guild.get_thread(self.id)

    def is_system(self) -> bool:
        """:class:`bool`: Whether the message is a system message.

        A system message is a message that is constructed entirely by the Discord API
        in response to something.

        .. versionadded:: 1.3
        """
        return self.type not in (
            MessageType.default,
            MessageType.reply,
            MessageType.chat_input_command,
            MessageType.context_menu_command,
            MessageType.thread_starter_message,
        )

    @utils.cached_slot_property("_cs_system_content")
    def system_content(self):
        r""":class:`str`: A property that returns the content that is rendered
        regardless of the :attr:`Message.type`.

        In the case of :attr:`MessageType.default` and :attr:`MessageType.reply`\,
        this just returns the regular :attr:`Message.content`. Otherwise this
        returns an English message denoting the contents of the system message.
        """

        if self.type is MessageType.default:
            return self.content

        if self.type is MessageType.recipient_add:
            if self.channel.type is ChannelType.group:
                return f"{self.author.name} added {self.mentions[0].name} to the group."
            return f"{self.author.name} added {self.mentions[0].name} to the thread."

        if self.type is MessageType.recipient_remove:
            if self.channel.type is ChannelType.group:
                return f"{self.author.name} removed {self.mentions[0].name} from the group."
            return f"{self.author.name} removed {self.mentions[0].name} from the thread."

        if self.type is MessageType.channel_name_change:
            return f"{self.author.name} changed the channel name: **{self.content}**"

        if self.type is MessageType.channel_icon_change:
            return f"{self.author.name} changed the channel icon."

        if self.type is MessageType.pins_add:
            return f"{self.author.name} pinned a message to this channel."

        if self.type is MessageType.new_member:
            formats = [
                "{0} joined the party.",
                "{0} is here.",
                "Welcome, {0}. We hope you brought pizza.",
                "A wild {0} appeared.",
                "{0} just landed.",
                "{0} just slid into the server.",
                "{0} just showed up!",
                "Welcome {0}. Say hi!",
                "{0} hopped into the server.",
                "Everyone welcome {0}!",
                "Glad you're here, {0}.",
                "Good to see you, {0}.",
                "Yay you made it, {0}!",
            ]

            created_at_ms = int(self.created_at.timestamp() * 1000)
            return formats[created_at_ms % len(formats)].format(self.author.name)

        if self.type is MessageType.premium_guild_subscription:
            if not self.content:
                return f"{self.author.name} just boosted the server!"
            return f"{self.author.name} just boosted the server **{self.content}** times!"

        if self.type is MessageType.premium_guild_tier_1:
            if not self.content:
                return f"{self.author.name} just boosted the server! {self.guild} has achieved **Level 1!**"
            return f"{self.author.name} just boosted the server **{self.content}** times! {self.guild} has achieved **Level 1!**"

        if self.type is MessageType.premium_guild_tier_2:
            if not self.content:
                return f"{self.author.name} just boosted the server! {self.guild} has achieved **Level 2!**"
            return f"{self.author.name} just boosted the server **{self.content}** times! {self.guild} has achieved **Level 2!**"

        if self.type is MessageType.premium_guild_tier_3:
            if not self.content:
                return f"{self.author.name} just boosted the server! {self.guild} has achieved **Level 3!**"
            return f"{self.author.name} just boosted the server **{self.content}** times! {self.guild} has achieved **Level 3!**"

        if self.type is MessageType.channel_follow_add:
            return f"{self.author.name} has added {self.content} to this channel"

        if self.type is MessageType.guild_stream:
            # the author will be a Member
            return f"{self.author.name} is live! Now streaming {self.author.activity.name}"  # type: ignore

        if self.type is MessageType.guild_discovery_disqualified:
            return "This server has been removed from Server Discovery because it no longer passes all the requirements. Check Server Settings for more details."

        if self.type is MessageType.guild_discovery_requalified:
            return "This server is eligible for Server Discovery again and has been automatically relisted!"

        if self.type is MessageType.guild_discovery_grace_period_initial_warning:
            return "This server has failed Discovery activity requirements for 1 week. If this server fails for 4 weeks in a row, it will be automatically removed from Discovery."

        if self.type is MessageType.guild_discovery_grace_period_final_warning:
            return "This server has failed Discovery activity requirements for 3 weeks in a row. If this server fails for 1 more week, it will be removed from Discovery."

        if self.type is MessageType.thread_created:
            return f"{self.author.name} started a thread: **{self.content}**. See all **threads**."

        if self.type is MessageType.reply:
            return self.content

        if self.type is MessageType.thread_starter_message:
            if self.reference is None or self.reference.resolved is None:
                return "Sorry, we couldn't load the first message in this thread"

            # the resolved message for the reference will be a Message
            return self.reference.resolved.content  # type: ignore

        if self.type is MessageType.guild_invite_reminder:
            return "Wondering who to invite?\nStart by inviting anyone who can help you build the server!"

        if (
            self.type is MessageType.role_subscription_purchase
            and self.role_subscription is not None
        ):
            tier_name = self.role_subscription.tier_name
            total_months_subscribed = self.role_subscription.total_months_subscribed
            months = f"{total_months_subscribed} month{'s' if total_months_subscribed != 1 else ''}"
            if self.role_subscription.is_renewal:
                return f"{self.author.name} renewed {tier_name} and has been a subscriber of {self.guild} for {months}!"

            return f"{self.author.name} joined {tier_name} and has been a subscriber of {self.guild} for {months}!"

        if self.type is MessageType.stage_start:
            return f"{self.author.display_name} started {self.content}"

        if self.type is MessageType.stage_end:
            return f"{self.author.display_name} ended {self.content}"

        if self.type is MessageType.stage_speaker:
            return f"{self.author.display_name} is now a speaker."

        if self.type is MessageType.stage_topic:
            return f"{self.author.display_name} changed the Stage topic: {self.content}"

        return None

    async def delete(self, *, delay: Optional[float] = None) -> None:
        """|coro|

        Deletes the message.

        Your own messages could be deleted without any proper permissions. However to
        delete other people's messages, you need the :attr:`~Permissions.manage_messages`
        permission.

        .. versionchanged:: 1.1
            Added the new ``delay`` keyword-only parameter.

        Parameters
        ----------
        delay: Optional[:class:`float`]
            If provided, the number of seconds to wait in the background
            before deleting the message. If the deletion fails then it is silently ignored.

        Raises
        ------
        Forbidden
            You do not have proper permissions to delete the message.
        NotFound
            The message was deleted already
        HTTPException
            Deleting the message failed.
        """
        if delay is not None:

            async def delete(delay: float) -> None:
                await asyncio.sleep(delay)
                with contextlib.suppress(HTTPException):
                    await self._state.http.delete_message(self.channel.id, self.id)

            task = asyncio.create_task(delete(delay))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            await self._state.http.delete_message(self.channel.id, self.id)

    @overload
    async def edit(
        self,
        *,
        content: Optional[str] = ...,
        embed: Optional[Embed] = ...,
        attachments: List[Attachment] = ...,
        suppress: bool = ...,
        delete_after: Optional[float] = ...,
        allowed_mentions: Optional[AllowedMentions] = ...,
        view: Optional[View] = ...,
        file: Optional[File] = ...,
    ) -> Message: ...

    @overload
    async def edit(
        self,
        *,
        content: Optional[str] = ...,
        embeds: List[Embed] = ...,
        attachments: List[Attachment] = ...,
        suppress: bool = ...,
        delete_after: Optional[float] = ...,
        allowed_mentions: Optional[AllowedMentions] = ...,
        view: Optional[View] = ...,
        file: Optional[File] = ...,
    ) -> Message: ...

    @overload
    async def edit(
        self,
        *,
        content: Optional[str] = ...,
        embed: Optional[Embed] = ...,
        attachments: List[Attachment] = ...,
        suppress: bool = ...,
        delete_after: Optional[float] = ...,
        allowed_mentions: Optional[AllowedMentions] = ...,
        view: Optional[View] = ...,
        files: Optional[List[File]] = ...,
    ) -> Message: ...

    @overload
    async def edit(
        self,
        *,
        content: Optional[str] = ...,
        embeds: List[Embed] = ...,
        attachments: List[Attachment] = ...,
        suppress: bool = ...,
        delete_after: Optional[float] = ...,
        allowed_mentions: Optional[AllowedMentions] = ...,
        view: Optional[View] = ...,
        files: Optional[List[File]] = ...,
    ) -> Message: ...

    async def edit(
        self,
        content: Optional[str] = MISSING,
        embed: Optional[Embed] = MISSING,
        embeds: List[Embed] = MISSING,
        attachments: List[Attachment] = MISSING,
        suppress: bool = MISSING,
        delete_after: Optional[float] = None,
        allowed_mentions: Optional[AllowedMentions] = MISSING,
        view: Optional[View] = MISSING,
        file: Optional[File] = MISSING,
        files: Optional[List[File]] = MISSING,
    ) -> Message:
        """|coro|

        Edits the message.

        The content must be able to be transformed into a string via ``str(content)``.

        .. versionchanged:: 1.3
            The ``suppress`` keyword-only parameter was added.

        Parameters
        ----------
        content: Optional[:class:`str`]
            The new content to replace the message with.
            Could be ``None`` to remove the content.
        embed: Optional[:class:`Embed`]
            The new embed to replace the original with.
            Could be ``None`` to remove the embed.
        embeds: List[:class:`Embed`]
            The new embeds to replace the original with. Must be a maximum of 10.
            To remove all embeds ``[]`` should be passed.

            .. versionadded:: 2.0
        attachments: List[:class:`Attachment`]
            A list of attachments to keep in the message. To keep all existing attachments,
            pass ``message.attachments``.
        suppress: :class:`bool`
            Whether to suppress embeds for the message. This removes
            all the embeds if set to ``True``. If set to ``False``
            this brings the embeds back if they were suppressed.
            Using this parameter requires :attr:`~.Permissions.manage_messages`.
        delete_after: Optional[:class:`float`]
            If provided, the number of seconds to wait in the background
            before deleting the message we just edited. If the deletion fails,
            then it is silently ignored.
        allowed_mentions: Optional[:class:`~nextcord.AllowedMentions`]
            Controls the mentions being processed in this message. If this is
            passed, then the object is merged with :attr:`~nextcord.Client.allowed_mentions`.
            The merging behaviour only overrides attributes that have been explicitly passed
            to the object, otherwise it uses the attributes set in :attr:`~nextcord.Client.allowed_mentions`.
            If no object is passed at all then the defaults given by :attr:`~nextcord.Client.allowed_mentions`
            are used instead.

            .. versionadded:: 1.4
        view: Optional[:class:`~nextcord.ui.View`]
            The updated view to update this message with. If ``None`` is passed then
            the view is removed.
        file: Optional[:class:`File`]
            If provided, a new file to add to the message.

            .. versionadded:: 2.0
        files: Optional[List[:class:`File`]]
            If provided, a list of new files to add to the message.

            .. versionadded:: 2.0

        Raises
        ------
        NotFound
            The message was not found.
        HTTPException
            Editing the message failed.
        Forbidden
            Tried to suppress a message without permissions or
            edited a message's content or embed that isn't yours.
        InvalidArgument
            You specified both ``embed`` and ``embeds`` or ``file`` and ``files``.

        Returns
        -------
        :class:`Message`
            The edited message.
        """

        payload: Dict[str, Any] = {}
        if content is not MISSING:
            if content is not None:
                payload["content"] = str(content)
            else:
                payload["content"] = None

        if embed is not MISSING and embeds is not MISSING:
            raise InvalidArgument("Cannot pass both embed and embeds parameter to edit()")
        if file is not MISSING and files is not MISSING:
            raise InvalidArgument("Cannot pass both file and files parameter to edit()")

        if embed is not MISSING:
            if embed is None:
                payload["embeds"] = []
            else:
                payload["embeds"] = [embed.to_dict()]
        elif embeds is not MISSING:
            payload["embeds"] = [e.to_dict() for e in embeds]

        if suppress is not MISSING:
            flags = MessageFlags._from_value(self.flags.value)
            flags.suppress_embeds = suppress
            payload["flags"] = flags.value

        if allowed_mentions is MISSING:
            if self._state.allowed_mentions is not None and self.author.id == self._state.self_id:
                payload["allowed_mentions"] = self._state.allowed_mentions.to_dict()
        elif allowed_mentions is not None:
            if self._state.allowed_mentions is not None:
                payload["allowed_mentions"] = self._state.allowed_mentions.merge(
                    allowed_mentions
                ).to_dict()
            else:
                payload["allowed_mentions"] = allowed_mentions.to_dict()

        if attachments is not MISSING:
            payload["attachments"] = [a.to_dict() for a in attachments]

        if view is not MISSING:
            self._state.prevent_view_updates_for(self.id)
            if view:
                payload["components"] = view.to_components()
            else:
                payload["components"] = []

        if file is not MISSING:
            payload["files"] = [file]
        elif files is not MISSING:
            payload["files"] = files

        data = await self._state.http.edit_message(self.channel.id, self.id, **payload)
        message = Message(state=self._state, channel=self.channel, data=data)

        if view and not view.is_finished() and view.prevent_update:
            self._state.store_view(view, self.id)

        if delete_after is not None:
            await self.delete(delay=delete_after)

        return message

    async def publish(self) -> None:
        """|coro|

        Publishes this message to your announcement channel.

        You must have the :attr:`~Permissions.send_messages` permission to do this.

        If the message is not your own then the :attr:`~Permissions.manage_messages`
        permission is also needed.

        Raises
        ------
        Forbidden
            You do not have the proper permissions to publish this message.
        HTTPException
            Publishing the message failed.
        """

        await self._state.http.publish_message(self.channel.id, self.id)

    async def pin(self, *, reason: Optional[str] = None) -> None:
        """|coro|

        Pins the message.

        You must have the :attr:`~Permissions.manage_messages` permission to do
        this in a non-private channel context.

        Parameters
        ----------
        reason: Optional[:class:`str`]
            The reason for pinning the message. Shows up on the audit log.

            .. versionadded:: 1.4

        Raises
        ------
        Forbidden
            You do not have permissions to pin the message.
        NotFound
            The message or channel was not found or deleted.
        HTTPException
            Pinning the message failed, probably due to the channel
            having more than 50 pinned messages.
        """

        await self._state.http.pin_message(self.channel.id, self.id, reason=reason)
        self.pinned = True

    async def unpin(self, *, reason: Optional[str] = None) -> None:
        """|coro|

        Unpins the message.

        You must have the :attr:`~Permissions.manage_messages` permission to do
        this in a non-private channel context.

        Parameters
        ----------
        reason: Optional[:class:`str`]
            The reason for unpinning the message. Shows up on the audit log.

            .. versionadded:: 1.4

        Raises
        ------
        Forbidden
            You do not have permissions to unpin the message.
        NotFound
            The message or channel was not found or deleted.
        HTTPException
            Unpinning the message failed.
        """

        await self._state.http.unpin_message(self.channel.id, self.id, reason=reason)
        self.pinned = False

    async def add_reaction(self, emoji: EmojiInputType) -> None:
        """|coro|

        Add a reaction to the message.

        The emoji may be a unicode emoji or a custom guild :class:`Emoji`.

        You must have the :attr:`~Permissions.read_message_history` permission
        to use this. If nobody else has reacted to the message using this
        emoji, the :attr:`~Permissions.add_reactions` permission is required.

        Parameters
        ----------
        emoji: Union[:class:`Emoji`, :class:`Reaction`, :class:`PartialEmoji`, :class:`str`]
            The emoji to react with.

        Raises
        ------
        HTTPException
            Adding the reaction failed.
        Forbidden
            You do not have the proper permissions to react to the message.
        NotFound
            The emoji you specified was not found.
        InvalidArgument
            The emoji parameter is invalid.
        """

        emoji = convert_emoji_reaction(emoji)
        await self._state.http.add_reaction(self.channel.id, self.id, emoji)

    async def remove_reaction(
        self, emoji: Union[EmojiInputType, Reaction], member: Snowflake
    ) -> None:
        """|coro|

        Remove a reaction by the member from the message.

        The emoji may be a unicode emoji or a custom guild :class:`Emoji`.

        If the reaction is not your own (i.e. ``member`` parameter is not you) then
        the :attr:`~Permissions.manage_messages` permission is needed.

        The ``member`` parameter must represent a member and meet
        the :class:`abc.Snowflake` abc.

        Parameters
        ----------
        emoji: Union[:class:`Emoji`, :class:`Reaction`, :class:`PartialEmoji`, :class:`str`]
            The emoji to remove.
        member: :class:`abc.Snowflake`
            The member for which to remove the reaction.

        Raises
        ------
        HTTPException
            Removing the reaction failed.
        Forbidden
            You do not have the proper permissions to remove the reaction.
        NotFound
            The member or emoji you specified was not found.
        InvalidArgument
            The emoji parameter is invalid.
        """

        emoji = convert_emoji_reaction(emoji)

        if member.id == self._state.self_id:
            await self._state.http.remove_own_reaction(self.channel.id, self.id, emoji)
        else:
            await self._state.http.remove_reaction(self.channel.id, self.id, emoji, member.id)

    async def clear_reaction(self, emoji: Union[EmojiInputType, Reaction]) -> None:
        """|coro|

        Clears a specific reaction from the message.

        The emoji may be a unicode emoji or a custom guild :class:`Emoji`.

        You need the :attr:`~Permissions.manage_messages` permission to use this.

        .. versionadded:: 1.3

        Parameters
        ----------
        emoji: Union[:class:`Emoji`, :class:`Reaction`, :class:`PartialEmoji`, :class:`str`]
            The emoji to clear.

        Raises
        ------
        HTTPException
            Clearing the reaction failed.
        Forbidden
            You do not have the proper permissions to clear the reaction.
        NotFound
            The emoji you specified was not found.
        InvalidArgument
            The emoji parameter is invalid.
        """

        emoji = convert_emoji_reaction(emoji)
        await self._state.http.clear_single_reaction(self.channel.id, self.id, emoji)

    async def clear_reactions(self) -> None:
        """|coro|

        Removes all the reactions from the message.

        You need the :attr:`~Permissions.manage_messages` permission to use this.

        Raises
        ------
        HTTPException
            Removing the reactions failed.
        Forbidden
            You do not have the proper permissions to remove all the reactions.
        """
        await self._state.http.clear_reactions(self.channel.id, self.id)

    async def create_thread(
        self, *, name: str, auto_archive_duration: ThreadArchiveDuration = MISSING
    ) -> Thread:
        """|coro|

        Creates a public thread from this message.

        You must have :attr:`~nextcord.Permissions.create_public_threads` in order to
        create a public thread from a message.

        The channel this message belongs in must be a :class:`TextChannel`.

        .. versionadded:: 2.0

        Parameters
        ----------
        name: :class:`str`
            The name of the thread.
        auto_archive_duration: :class:`int`
            The duration in minutes before a thread is automatically archived for inactivity.
            If not provided, the channel's default auto archive duration is used.

        Raises
        ------
        Forbidden
            You do not have permissions to create a thread.
        HTTPException
            Creating the thread failed.
        InvalidArgument
            This message does not have guild info attached.

        Returns
        -------
        :class:`.Thread`
            The created thread.
        """
        if self.guild is None:
            raise InvalidArgument("This message does not have guild info attached.")

        default_auto_archive_duration: ThreadArchiveDuration = getattr(
            self.channel, "default_auto_archive_duration", 1440
        )
        data = await self._state.http.start_thread_with_message(
            self.channel.id,
            self.id,
            name=name,
            auto_archive_duration=auto_archive_duration or default_auto_archive_duration,
        )
        return Thread(guild=self.guild, state=self._state, data=data)

    async def reply(self, content: Optional[str] = None, **kwargs) -> Message:
        """|coro|

        A shortcut method to :meth:`.abc.Messageable.send` to reply to the
        :class:`.Message`.

        .. versionadded:: 1.6

        Raises
        ------
        ~nextcord.HTTPException
            Sending the message failed.
        ~nextcord.Forbidden
            You do not have the proper permissions to send the message.
        ~nextcord.InvalidArgument
            The ``files`` list is not of the appropriate size or
            you specified both ``file`` and ``files``.

        Returns
        -------
        :class:`.Message`
            The message that was sent.
        """

        return await self.channel.send(content, reference=self, **kwargs)

    async def forward(self, channel: Messageable) -> Message:
        """Forward this message to a channel.

        .. note::
            It is not possible to forward messages through interactions.
            It is only possible to forward a message to a channel as a message.

        Parameters
        ----------
        channel: :class:`~nextcord.Messageable`
            The channel to forward this message.

        Raises
        ------
        ~nextcord.HTTPException
            Forwarding/sending the message failed.
        ~nextcord.Forbidden
            You do not have the proper permissions to send the message.

        .. versionadded:: 3.0
        """
        return await channel.send(
            reference=MessageReference.from_message(self, type=MessageReferenceType.forward),
        )

    def to_reference(self, *, fail_if_not_exists: bool = True) -> MessageReference:
        """Creates a :class:`~nextcord.MessageReference` from the current message.

        .. versionadded:: 1.6

        Parameters
        ----------
        fail_if_not_exists: :class:`bool`
            Whether replying using the message reference should raise :class:`HTTPException`
            if the message no longer exists or Discord could not fetch the message.

            .. versionadded:: 1.7

        Returns
        -------
        :class:`~nextcord.MessageReference`
            The reference to this message.
        """

        return MessageReference.from_message(self, fail_if_not_exists=fail_if_not_exists)

    def to_message_reference_dict(self) -> MessageReferencePayload:
        data: MessageReferencePayload = {
            "message_id": self.id,
            "channel_id": self.channel.id,
        }

        if self.guild is not None:
            data["guild_id"] = self.guild.id

        return data


class PartialMessage(Hashable):
    """Represents a partial message to aid with working messages when only
    a message and channel ID are present.

    There are two ways to construct this class. The first one is through
    the constructor itself, and the second is via the following:

    - :meth:`TextChannel.get_partial_message`
    - :meth:`Thread.get_partial_message`
    - :meth:`DMChannel.get_partial_message`

    Note that this class is trimmed down and has no rich attributes.

    .. versionadded:: 1.6

    .. container:: operations

        .. describe:: x == y

            Checks if two partial messages are equal.

        .. describe:: x != y

            Checks if two partial messages are not equal.

        .. describe:: hash(x)

            Returns the partial message's hash.

    Attributes
    ----------
    channel: Union[:class:`TextChannel`, :class:`Thread`, :class:`DMChannel`]
        The channel associated with this partial message.
    id: :class:`int`
        The message ID.
    """

    __slots__ = ("channel", "id", "_cs_guild", "_state")

    jump_url: str = Message.jump_url  # type: ignore
    delete = Message.delete
    publish = Message.publish
    pin = Message.pin
    unpin = Message.unpin
    add_reaction = Message.add_reaction
    remove_reaction = Message.remove_reaction
    clear_reaction = Message.clear_reaction
    clear_reactions = Message.clear_reactions
    reply = Message.reply
    to_reference = Message.to_reference
    to_message_reference_dict = Message.to_message_reference_dict

    def __init__(self, *, channel: PartialMessageableChannel, id: int) -> None:
        if channel.type not in (
            ChannelType.text,
            ChannelType.news,
            ChannelType.private,
            ChannelType.news_thread,
            ChannelType.public_thread,
            ChannelType.private_thread,
        ):
            raise TypeError(f"Expected TextChannel, DMChannel or Thread not {type(channel)!r}")

        self.channel: PartialMessageableChannel = channel
        self._state: ConnectionState = channel._state
        self.id: int = id

    def _update(self, data) -> None:
        # This is used for duck typing purposes.
        # Just do nothing with the data.
        pass

    # Also needed for duck typing purposes
    # n.b. not exposed
    pinned = property(None, lambda _, __: None)

    def __repr__(self) -> str:
        return f"<PartialMessage id={self.id} channel={self.channel!r}>"

    @property
    def created_at(self) -> datetime.datetime:
        """:class:`datetime.datetime`: The partial message's creation time in UTC."""
        return utils.snowflake_time(self.id)

    @utils.cached_slot_property("_cs_guild")
    def guild(self) -> Optional[Guild]:
        """Optional[:class:`Guild`]: The guild that the partial message belongs to, if applicable."""
        return getattr(self.channel, "guild", None)

    async def fetch(self) -> Message:
        """|coro|

        Fetches the partial message to a full :class:`Message`.

        Raises
        ------
        NotFound
            The message was not found.
        Forbidden
            You do not have the permissions required to get a message.
        HTTPException
            Retrieving the message failed.

        Returns
        -------
        :class:`Message`
            The full message.
        """

        data = await self._state.http.get_message(self.channel.id, self.id)
        return self._state.create_message(channel=self.channel, data=data)

    async def edit(self, **fields: Any) -> Optional[Message]:
        """|coro|

        Edits the message.

        The content must be able to be transformed into a string via ``str(content)``.

        .. versionchanged:: 1.7
            :class:`nextcord.Message` is returned instead of ``None`` if an edit took place.

        Parameters
        ----------
        content: Optional[:class:`str`]
            The new content to replace the message with.
            Could be ``None`` to remove the content.
        embed: Optional[:class:`Embed`]
            The new embed to replace the original with.
            Could be ``None`` to remove the embed.
        embeds: List[:class:`Embed`]
            The new embeds to replace the original with. Must be a maximum of 10.
            To remove all embeds ``[]`` should be passed.

            .. versionadded:: 2.0
        suppress: :class:`bool`
            Whether to suppress embeds for the message. This removes
            all the embeds if set to ``True``. If set to ``False``
            this brings the embeds back if they were suppressed.
            Using this parameter requires :attr:`~.Permissions.manage_messages`.
        delete_after: Optional[:class:`float`]
            If provided, the number of seconds to wait in the background
            before deleting the message we just edited. If the deletion fails,
            then it is silently ignored.
        allowed_mentions: Optional[:class:`~nextcord.AllowedMentions`]
            Controls the mentions being processed in this message. If this is
            passed, then the object is merged with :attr:`~nextcord.Client.allowed_mentions`.
            The merging behaviour only overrides attributes that have been explicitly passed
            to the object, otherwise it uses the attributes set in :attr:`~nextcord.Client.allowed_mentions`.
            If no object is passed at all then the defaults given by :attr:`~nextcord.Client.allowed_mentions`
            are used instead.
        view: Optional[:class:`~nextcord.ui.View`]
            The updated view to update this message with. If ``None`` is passed then
            the view is removed.

            .. versionadded:: 2.0

        Raises
        ------
        NotFound
            The message was not found.
        HTTPException
            Editing the message failed.
        Forbidden
            Tried to suppress a message without permissions or
            edited a message's content or embed that isn't yours.
        ~nextcord.InvalidArgument
            You specified both ``embed`` and ``embeds``.

        Returns
        -------
        Optional[:class:`Message`]
            The message that was edited.
        """

        try:
            content = fields["content"]
        except KeyError:
            pass
        else:
            if content is not None:
                fields["content"] = str(content)

        if "embed" in fields and "embeds" in fields:
            raise InvalidArgument("Cannot pass both embed and embeds parameter to edit()")

        if "embed" in fields:
            embed = fields.pop("embed")
            fields["embeds"] = [embed.to_dict()] if embed is not None else []

        elif "embeds" in fields:
            fields["embeds"] = [embed.to_dict() for embed in fields["embeds"]]

        try:
            suppress: bool = fields.pop("suppress")
        except KeyError:
            pass
        else:
            flags = MessageFlags._from_value(0)
            flags.suppress_embeds = suppress
            fields["flags"] = flags.value

        delete_after = fields.pop("delete_after", None)

        try:
            allowed_mentions = fields.pop("allowed_mentions")
        except KeyError:
            pass
        else:
            if allowed_mentions is not None:
                if self._state.allowed_mentions is not None:
                    allowed_mentions = self._state.allowed_mentions.merge(
                        allowed_mentions
                    ).to_dict()
                else:
                    allowed_mentions = allowed_mentions.to_dict()
                fields["allowed_mentions"] = allowed_mentions

        try:
            view = fields.pop("view")
        except KeyError:
            # To check for the view afterwards
            view = None
        else:
            self._state.prevent_view_updates_for(self.id)
            if view:
                fields["components"] = view.to_components()
            else:
                fields["components"] = []

        if fields:
            data = await self._state.http.edit_message(self.channel.id, self.id, **fields)

        if delete_after is not None:
            await self.delete(delay=delete_after)

        if fields:
            # data isn't unbound
            msg = self._state.create_message(channel=self.channel, data=data)
            if view and not view.is_finished() and view.prevent_update:
                self._state.store_view(view, self.id)
            return msg
        return None
