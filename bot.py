import asyncio
import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, unquote

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv


# =========================
# Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("image_approval_bot")


# =========================
# Load .env
# =========================

load_dotenv()


def parse_id_list(value: Optional[str]) -> set[int]:
    if not value:
        return set()

    ids: set[int] = set()

    for item in value.split(","):
        item = item.strip()
        if not item:
            continue

        try:
            ids.add(int(item))
        except ValueError:
            logger.warning("Invalid ID in env list: %s", item)

    return ids


def parse_source_to_destination_map(value: Optional[str]) -> dict[int, int]:
    mapping: dict[int, int] = {}

    if not value:
        return mapping

    pairs = value.split(",")

    for pair in pairs:
        pair = pair.strip()

        if not pair:
            continue

        if ":" not in pair:
            logger.warning("Invalid TEAM_DESTINATION_MAP pair, missing colon: %s", pair)
            continue

        source_id_raw, destination_id_raw = pair.split(":", 1)

        try:
            source_id = int(source_id_raw.strip())
            destination_id = int(destination_id_raw.strip())
            mapping[source_id] = destination_id

        except ValueError:
            logger.warning("Invalid source/destination ID pair: %s", pair)

    return mapping


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

SOURCE_CHANNEL_IDS = parse_id_list(os.getenv("SOURCE_CHANNEL_IDS"))

ADMIN_APPROVAL_CHANNEL_ID = int(os.getenv("ADMIN_APPROVAL_CHANNEL_ID", "0"))

TEAM_DESTINATION_MAP = parse_source_to_destination_map(
    os.getenv("TEAM_DESTINATION_MAP")
)

APPROVAL_EMOJI = os.getenv("APPROVAL_EMOJI", "✅").strip()

REJECTION_EMOJI = os.getenv("REJECTION_EMOJI", "❌").strip()

REJECTED_CHANNEL_ID = int(os.getenv("REJECTED_CHANNEL_ID", "0"))

APPROVAL_ROLE_IDS = parse_id_list(os.getenv("APPROVAL_ROLE_IDS"))

GOOGLE_APPS_SCRIPT_WEBHOOK_URL = os.getenv("GOOGLE_APPS_SCRIPT_WEBHOOK_URL")

REJECTION_REASON_TIMEOUT_SECONDS = int(
    os.getenv("REJECTION_REASON_TIMEOUT_SECONDS", "900")
)


if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

if not SOURCE_CHANNEL_IDS:
    raise RuntimeError("Missing SOURCE_CHANNEL_IDS in .env")

if not ADMIN_APPROVAL_CHANNEL_ID:
    raise RuntimeError("Missing ADMIN_APPROVAL_CHANNEL_ID in .env")

if not TEAM_DESTINATION_MAP:
    raise RuntimeError("Missing TEAM_DESTINATION_MAP in .env")

if not REJECTED_CHANNEL_ID:
    raise RuntimeError("Missing REJECTED_CHANNEL_ID in .env")

if not GOOGLE_APPS_SCRIPT_WEBHOOK_URL:
    raise RuntimeError("Missing GOOGLE_APPS_SCRIPT_WEBHOOK_URL in .env")


missing_team_mappings = SOURCE_CHANNEL_IDS.difference(TEAM_DESTINATION_MAP.keys())

if missing_team_mappings:
    raise RuntimeError(
        "These source channels are missing from TEAM_DESTINATION_MAP: "
        f"{missing_team_mappings}"
    )


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
}

CATEGORY_OPTIONS = [
    "Zalcano Shards",
    "Gauntlet Seeds",
    "Spirit Shields",
    "Yama Uniques",
    "DK Rings",
    "Nightmare Uniques",
    "Godsword Shards",
    "Zulrah Uniques",
    "Nex Uniques",
    "Barrows and Moons",
    "Raid Purples",
    "Dragon Pickaxes",
    "Virtus Pieces",
    "Vorkath Heads",
    "Unique Pets/Jars",
    "Tome of Fire",
    "Tome of Water",
    "Tome of Earth",
    "Blessings",
    "Venator Shards",
    "Doom Uniques",
    "Elemental Staff Crowns",
]


# =========================
# Discord Intents
# =========================

intents = discord.Intents.default()

intents.guilds = True
intents.messages = True
intents.guild_messages = True
intents.dm_messages = True
intents.reactions = True
intents.guild_reactions = True
intents.members = True
intents.message_content = True


bot = commands.Bot(command_prefix="!", intents=intents)


processing_message_ids: set[int] = set()
processing_lock = asyncio.Lock()


# =========================
# Data Classes
# =========================

@dataclass
class ImageSource:
    kind: str
    filename: str
    attachment: Optional[discord.Attachment] = None
    url: Optional[str] = None


@dataclass
class SubmitterInfo:
    display_name: str
    username: str
    discord_id: Optional[int]
    mention_text: str
    is_bot_source: bool


# =========================
# Helper Functions
# =========================

def discord_timestamp(dt: datetime, style: str = "F") -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    unix_timestamp = int(dt.timestamp())
    return f"<t:{unix_timestamp}:{style}>"


def emoji_matches(payload_emoji: discord.PartialEmoji, configured_emoji: str) -> bool:
    configured = configured_emoji.strip()
    configured_without_colons = configured.strip(":")

    logger.info("Emoji comparison:")
    logger.info("  Payload emoji str: %s", str(payload_emoji))
    logger.info("  Payload emoji name: %s", payload_emoji.name)
    logger.info("  Payload emoji id: %s", payload_emoji.id)
    logger.info("  Configured emoji: %s", configured)

    if str(payload_emoji) == configured:
        return True

    if payload_emoji.name == configured:
        return True

    if payload_emoji.name == configured_without_colons:
        return True

    if payload_emoji.id and str(payload_emoji.id) == configured:
        return True

    return False


def is_image_attachment(attachment: discord.Attachment) -> bool:
    logger.info(
        "Checking attachment: filename=%s content_type=%s size=%s url=%s",
        attachment.filename,
        attachment.content_type,
        attachment.size,
        attachment.url,
    )

    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True

    filename = attachment.filename.lower()
    return any(filename.endswith(ext) for ext in IMAGE_EXTENSIONS)


def filename_from_url(url: str, fallback: str = "approved-image.png") -> str:
    try:
        path = urlparse(url).path
        name = unquote(path.split("/")[-1])

        if name and "." in name:
            return name

    except Exception:
        pass

    return fallback


def get_first_valid_image_source(message: discord.Message) -> Optional[ImageSource]:
    logger.info(
        "Message %s has %s attachment(s) and %s embed(s).",
        message.id,
        len(message.attachments),
        len(message.embeds),
    )

    # Human/user uploads usually land here.
    for attachment in message.attachments:
        if is_image_attachment(attachment):
            logger.info("Selected image attachment: %s", attachment.filename)

            return ImageSource(
                kind="attachment",
                filename=attachment.filename or "approved-image.png",
                attachment=attachment,
            )

    # Dink/Captain Hook style posts usually land here.
    for index, embed in enumerate(message.embeds):
        image_url = None

        if embed.image and embed.image.url:
            image_url = embed.image.proxy_url or embed.image.url

        elif embed.thumbnail and embed.thumbnail.url:
            image_url = embed.thumbnail.proxy_url or embed.thumbnail.url

        if image_url:
            filename = filename_from_url(
                image_url,
                fallback=f"embed-image-{message.id}-{index}.png",
            )

            logger.info("Selected embed image URL: %s", image_url)

            return ImageSource(
                kind="embed",
                filename=filename,
                url=image_url,
            )

    return None


async def download_image_source(image_source: ImageSource) -> tuple[bytes, str]:
    if image_source.kind == "attachment" and image_source.attachment:
        logger.info("Downloading attachment: %s", image_source.attachment.url)

        try:
            file_bytes = await image_source.attachment.read(use_cached=True)
            logger.info("Downloaded attachment successfully: %s bytes", len(file_bytes))
            return file_bytes, image_source.filename

        except discord.HTTPException as exc:
            raise RuntimeError(
                f"Failed to download attachment {image_source.attachment.id}"
            ) from exc

    if image_source.kind == "embed" and image_source.url:
        logger.info("Downloading embed image: %s", image_source.url)

        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(image_source.url) as response:
                if response.status < 200 or response.status >= 300:
                    text = await response.text()
                    raise RuntimeError(
                        f"Failed to download embed image. "
                        f"Status={response.status}, Body={text[:500]}"
                    )

                file_bytes = await response.read()
                logger.info("Downloaded embed image successfully: %s bytes", len(file_bytes))
                return file_bytes, image_source.filename

    raise RuntimeError("Invalid image source.")


def extract_dink_player_name(message: discord.Message) -> Optional[str]:
    """
    Attempts to extract the in-game player name from Dink/Captain Hook embeds.

    Common examples:
    - embed.author.name = "Dovadova"
    - embed.description contains "Dovadova has looted:"
    """

    for embed in message.embeds:
        if embed.author and embed.author.name:
            name = embed.author.name.strip()

            if name:
                logger.info("Extracted Dink player from embed author: %s", name)
                return name

        if embed.description:
            description = embed.description.strip()

            marker = " has looted"
            lowered = description.lower()

            if marker in lowered:
                index = lowered.find(marker)
                name = description[:index].strip()

                if name:
                    logger.info("Extracted Dink player from embed description: %s", name)
                    return name

    return None


def find_member_by_name(guild: Optional[discord.Guild], name: str) -> Optional[discord.Member]:
    if guild is None:
        return None

    cleaned = name.strip().lower()

    if not cleaned:
        return None

    for member in guild.members:
        possible_names = {
            member.name.lower(),
            member.display_name.lower(),
        }

        if member.global_name:
            possible_names.add(member.global_name.lower())

        if cleaned in possible_names:
            return member

    return None


def get_submitter_info(message: discord.Message) -> SubmitterInfo:
    """
    For normal user messages:
      submitter = message.author

    For Dink/Captain Hook bot messages:
      submitter = extracted RuneScape name if possible.
    """

    if message.author.bot:
        player_name = extract_dink_player_name(message)

        if player_name:
            matching_member = find_member_by_name(message.guild, player_name)

            if matching_member:
                return SubmitterInfo(
                    display_name=matching_member.display_name,
                    username=str(matching_member),
                    discord_id=matching_member.id,
                    mention_text=matching_member.mention,
                    is_bot_source=True,
                )

            return SubmitterInfo(
                display_name=player_name,
                username=player_name,
                discord_id=None,
                mention_text=f"@{player_name}",
                is_bot_source=True,
            )

    return SubmitterInfo(
        display_name=getattr(message.author, "display_name", message.author.name),
        username=str(message.author),
        discord_id=message.author.id,
        mention_text=message.author.mention,
        is_bot_source=message.author.bot,
    )


async def get_member_from_payload(payload: discord.RawReactionActionEvent) -> Optional[discord.Member]:
    if isinstance(payload.member, discord.Member):
        logger.info("Resolved approver/rejector from payload.member: %s", payload.member)
        return payload.member

    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None

    if not guild:
        logger.warning("Could not get guild from payload.guild_id=%s", payload.guild_id)
        return None

    try:
        member = await guild.fetch_member(payload.user_id)
        logger.info("Fetched member: %s", member)
        return member

    except discord.NotFound:
        logger.warning("Reacting member not found: %s", payload.user_id)

    except discord.Forbidden:
        logger.exception("Missing permission to fetch member: %s", payload.user_id)

    except discord.HTTPException:
        logger.exception("Failed to fetch member: %s", payload.user_id)

    return None


def user_can_moderate(member: discord.Member) -> bool:
    logger.info("Checking moderation permissions for %s (%s)", member, member.id)
    logger.info("  Is administrator: %s", member.guild_permissions.administrator)

    if member.guild_permissions.administrator:
        return True

    member_role_ids = {role.id for role in member.roles}

    logger.info("  Member role IDs: %s", member_role_ids)
    logger.info("  Allowed approval role IDs: %s", APPROVAL_ROLE_IDS)

    allowed = bool(member_role_ids.intersection(APPROVAL_ROLE_IDS))

    logger.info("  Can approve/reject/categorize: %s", allowed)

    return allowed


async def fetch_text_channel(channel_id: int, label: str) -> Optional[discord.TextChannel]:
    logger.info("Fetching %s channel: %s", label, channel_id)

    channel = bot.get_channel(channel_id)

    if channel is None:
        logger.info("%s channel not cached. Fetching from Discord API.", label)

        try:
            channel = await bot.fetch_channel(channel_id)

        except discord.NotFound:
            logger.error("%s channel not found: %s", label, channel_id)
            return None

        except discord.Forbidden:
            logger.exception("Missing permission to fetch %s channel: %s", label, channel_id)
            return None

        except discord.HTTPException:
            logger.exception("Failed to fetch %s channel: %s", label, channel_id)
            return None

    if not isinstance(channel, discord.TextChannel):
        logger.error("%s channel is not a text channel: %s", label, channel_id)
        return None

    return channel


async def fetch_message(channel_id: int, message_id: int) -> Optional[discord.Message]:
    logger.info("Fetching message %s from channel %s", message_id, channel_id)

    channel = await fetch_text_channel(channel_id, "source")

    if channel is None:
        return None

    try:
        message = await channel.fetch_message(message_id)
        logger.info("Fetched message successfully: %s", message.id)
        logger.info("Message author: %s (%s)", message.author, message.author.id)
        logger.info("Author is bot: %s", message.author.bot)
        logger.info("Message attachments: %s", len(message.attachments))
        logger.info("Message embeds: %s", len(message.embeds))
        return message

    except discord.NotFound:
        logger.warning("Message deleted or inaccessible: %s", message_id)

    except discord.Forbidden:
        logger.exception("Missing permission to read message: %s", message_id)

    except discord.HTTPException:
        logger.exception("Failed to fetch message: %s", message_id)

    return None


async def post_to_google_sheets(payload: dict) -> dict:
    logger.info("Posting payload to Google Sheets webhook.")
    logger.info("Webhook URL starts with: %s", GOOGLE_APPS_SCRIPT_WEBHOOK_URL[:50])

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            GOOGLE_APPS_SCRIPT_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as response:
            text = await response.text()

            logger.info("Google webhook status: %s", response.status)
            logger.info("Google webhook response body: %s", text)

            if response.status < 200 or response.status >= 300:
                raise RuntimeError(
                    f"Google Apps Script webhook failed. "
                    f"Status={response.status}, Body={text}"
                )

            try:
                data = await response.json(content_type=None)
            except Exception:
                data = {}

            if data and data.get("success") is not True:
                raise RuntimeError(
                    f"Google Apps Script returned unsuccessful response: {data}"
                )

            return data


async def update_category_in_google_sheets(new_message_url: str, category: str) -> dict:
    payload = {
        "action": "updateCategory",
        "newMessageUrl": new_message_url,
        "category": category,
    }

    return await post_to_google_sheets(payload)


def make_discord_file(image_bytes: bytes, filename: str) -> discord.File:
    return discord.File(
        fp=io.BytesIO(image_bytes),
        filename=filename,
    )


# =========================
# Dropdown UI
# =========================

class CategorySelect(discord.ui.Select):
    def __init__(self, team_message_url: str):
        self.team_message_url = team_message_url

        options = [
            discord.SelectOption(
                label=category,
                value=category,
            )
            for category in CATEGORY_OPTIONS
        ]

        super().__init__(
            placeholder="Select proof category...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            logger.exception("Failed to defer dropdown interaction.")
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send(
                "Could not verify your permissions.",
                ephemeral=True,
            )
            return

        if not user_can_moderate(interaction.user):
            await interaction.followup.send(
                "You do not have permission to categorize proofs.",
                ephemeral=True,
            )
            return

        category = self.values[0]

        try:
            await update_category_in_google_sheets(
                new_message_url=self.team_message_url,
                category=category,
            )

            await interaction.followup.send(
                f"Category set to: **{category}**",
                ephemeral=True,
            )

            try:
                if interaction.message:
                    await interaction.message.delete()
                    logger.info(
                        "Deleted admin approval post %s after dropdown category update.",
                        interaction.message.id,
                    )
            except discord.Forbidden:
                logger.exception(
                    "Missing Manage Messages permission to delete admin approval post."
                )
            except discord.HTTPException:
                logger.exception("Failed to delete admin approval post.")

        except Exception:
            logger.exception("Failed to update category from dropdown.")

            try:
                await interaction.followup.send(
                    "Failed to update the category in Google Sheets.",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("Failed to send dropdown failure followup.")


class CategoryView(discord.ui.View):
    def __init__(self, team_message_url: str):
        super().__init__(timeout=None)
        self.add_item(CategorySelect(team_message_url))


# =========================
# Embed Builders
# =========================

def submitter_embed_value(submitter: SubmitterInfo) -> str:
    lines = [
        submitter.display_name,
        f"`{submitter.username}`",
    ]

    if submitter.discord_id:
        lines.append(f"`{submitter.discord_id}`")

    if submitter.is_bot_source:
        lines.append("_Extracted from bot/embed post_")

    return "\n".join(lines)


def build_approval_embed(
    approver: discord.Member,
    submitter: SubmitterInfo,
    source_channel: discord.TextChannel,
    original_message_sent_at: datetime,
    approved_at: datetime,
    destination_label: str,
    team_message_url: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="Image Approved",
        color=discord.Color.green(),
        timestamp=approved_at,
    )

    embed.add_field(
        name="Posted to",
        value=destination_label,
        inline=False,
    )

    if team_message_url:
        embed.add_field(
            name="Team proof URL",
            value=team_message_url,
            inline=False,
        )

    embed.add_field(
        name="Original submission time",
        value=(
            f"{discord_timestamp(original_message_sent_at, 'F')}\n"
            f"{discord_timestamp(original_message_sent_at, 'R')}"
        ),
        inline=False,
    )

    embed.add_field(
        name="Approved by",
        value=(
            f"{approver.display_name}\n"
            f"`{approver}`\n"
            f"`{approver.id}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Original submitter",
        value=submitter_embed_value(submitter),
        inline=False,
    )

    embed.add_field(
        name="Source channel",
        value=f"{source_channel.mention}\n`{source_channel.id}`",
        inline=False,
    )

    embed.add_field(
        name="Approved at",
        value=(
            f"{discord_timestamp(approved_at, 'F')}\n"
            f"{discord_timestamp(approved_at, 'R')}"
        ),
        inline=False,
    )

    return embed


def build_rejection_embed(
    rejector: discord.Member,
    submitter: SubmitterInfo,
    source_channel: discord.TextChannel,
    original_message_sent_at: datetime,
    rejected_at: datetime,
    reason: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="Screenshot Rejected",
        color=discord.Color.red(),
        timestamp=rejected_at,
    )

    embed.add_field(
        name="Original submission time",
        value=(
            f"{discord_timestamp(original_message_sent_at, 'F')}\n"
            f"{discord_timestamp(original_message_sent_at, 'R')}"
        ),
        inline=False,
    )

    embed.add_field(
        name="Reason",
        value=reason[:1024],
        inline=False,
    )

    embed.add_field(
        name="Rejected by",
        value=(
            f"{rejector.display_name}\n"
            f"`{rejector}`\n"
            f"`{rejector.id}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Original submitter",
        value=submitter_embed_value(submitter),
        inline=False,
    )

    embed.add_field(
        name="Source channel",
        value=f"{source_channel.mention}\n`{source_channel.id}`",
        inline=False,
    )

    embed.add_field(
        name="Rejected at",
        value=(
            f"{discord_timestamp(rejected_at, 'F')}\n"
            f"{discord_timestamp(rejected_at, 'R')}"
        ),
        inline=False,
    )

    embed.set_footer(
        text="If this proof is fixed and resubmitted, staff can use the original submission time above as the official drop time."
    )

    return embed


# =========================
# Posting Helpers
# =========================

async def repost_approved_image(
    channel: discord.TextChannel,
    image_bytes: bytes,
    filename: str,
    approver: discord.Member,
    source_channel: discord.TextChannel,
    submitter: SubmitterInfo,
    original_message_sent_at: datetime,
    approved_at: datetime,
    destination_label: str,
    team_message_url: Optional[str] = None,
) -> discord.Message:
    logger.info("Sending approved repost to %s channel %s", destination_label, channel.id)

    embed = build_approval_embed(
        approver=approver,
        submitter=submitter,
        source_channel=source_channel,
        original_message_sent_at=original_message_sent_at,
        approved_at=approved_at,
        destination_label=destination_label,
        team_message_url=team_message_url,
    )

    content = (
        f"Approved by {approver.mention} "
        f"from {source_channel.mention}\n"
        f"Original submitter: {submitter.mention_text}\n"
        f"Original submission time: {discord_timestamp(original_message_sent_at, 'F')}"
    )

    if team_message_url:
        content += f"\nTeam proof URL: {team_message_url}"

    view = None

    if destination_label == "Admin Approvals" and team_message_url:
        view = CategoryView(team_message_url)

    new_message = await channel.send(
        content=content,
        embed=embed,
        file=make_discord_file(image_bytes, filename),
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    logger.info(
        "Reposted approved image successfully to %s. New message ID: %s",
        destination_label,
        new_message.id,
    )

    if not new_message.attachments:
        raise RuntimeError(
            f"Reposted approved message in {destination_label} channel has no attachment."
        )

    return new_message


async def ask_rejection_reason(
    rejector: discord.Member,
    message: discord.Message,
    submitter: SubmitterInfo,
) -> Optional[str]:
    try:
        dm = await rejector.create_dm()

        await dm.send(
            "You reacted with ❌ to reject a screenshot.\n\n"
            f"Original submitter: `{submitter.display_name}`\n"
            f"Source channel: `#{message.channel.name}`\n"
            f"Original submission time: {discord_timestamp(message.created_at, 'F')} "
            f"({discord_timestamp(message.created_at, 'R')})\n"
            f"Message ID: `{message.id}`\n\n"
            "Reply to this DM with the rejection reason.\n"
            "Type `cancel` to cancel this rejection.\n\n"
            f"You have {REJECTION_REASON_TIMEOUT_SECONDS // 60} minutes."
        )

    except discord.Forbidden:
        logger.exception("Could not DM rejector %s. Rejection cancelled.", rejector.id)
        return None

    except discord.HTTPException:
        logger.exception("Failed to DM rejector %s. Rejection cancelled.", rejector.id)
        return None

    def check(dm_message: discord.Message) -> bool:
        return (
            dm_message.author.id == rejector.id
            and isinstance(dm_message.channel, discord.DMChannel)
            and bool(dm_message.content.strip())
        )

    try:
        reply = await bot.wait_for(
            "message",
            timeout=REJECTION_REASON_TIMEOUT_SECONDS,
            check=check,
        )

    except asyncio.TimeoutError:
        try:
            await dm.send("Rejection timed out. The original screenshot was not deleted.")
        except Exception:
            pass

        logger.info("Rejection reason timed out for message %s", message.id)
        return None

    reason = reply.content.strip()

    if reason.lower() in {"cancel", "cancelled", "canceled", "stop"}:
        try:
            await dm.send("Rejection cancelled. The original screenshot was not deleted.")
        except Exception:
            pass

        logger.info("Rejector cancelled rejection for message %s", message.id)
        return None

    try:
        await dm.send("Got it. Posting the rejection now.")
    except Exception:
        pass

    return reason


async def post_rejected_image(
    channel: discord.TextChannel,
    image_bytes: bytes,
    filename: str,
    rejector: discord.Member,
    source_channel: discord.TextChannel,
    submitter: SubmitterInfo,
    original_message_sent_at: datetime,
    rejected_at: datetime,
    reason: str,
) -> discord.Message:
    logger.info("Sending rejected screenshot to rejected channel %s", channel.id)

    embed = build_rejection_embed(
        rejector=rejector,
        submitter=submitter,
        source_channel=source_channel,
        original_message_sent_at=original_message_sent_at,
        rejected_at=rejected_at,
        reason=reason,
    )

    content = (
        f"{submitter.mention_text} your screenshot was rejected.\n\n"
        f"**Original submission time:** {discord_timestamp(original_message_sent_at, 'F')} "
        f"({discord_timestamp(original_message_sent_at, 'R')})\n"
        f"**Reason:** {reason}\n\n"
        f"If you fix and resubmit this same proof, staff may use the original submission time above "
        f"as the official drop time."
    )

    rejected_message = await channel.send(
        content=content,
        embed=embed,
        file=make_discord_file(image_bytes, filename),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )

    logger.info("Rejected screenshot posted successfully: %s", rejected_message.id)

    if not rejected_message.attachments:
        raise RuntimeError("Rejected message has no attachment.")

    return rejected_message


# =========================
# Events
# =========================

@bot.event
async def on_ready():
    logger.info("========================================")
    logger.info("BOT READY")
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id)
    logger.info("Monitoring source channels: %s", SOURCE_CHANNEL_IDS)
    logger.info("Admin approval channel: %s", ADMIN_APPROVAL_CHANNEL_ID)
    logger.info("Team destination map: %s", TEAM_DESTINATION_MAP)
    logger.info("Rejected channel: %s", REJECTED_CHANNEL_ID)
    logger.info("Approval emoji: %s", APPROVAL_EMOJI)
    logger.info("Rejection emoji: %s", REJECTION_EMOJI)
    logger.info("Approval/rejection/category roles: %s", APPROVAL_ROLE_IDS)
    logger.info("========================================")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    logger.info("========================================")
    logger.info("RAW REACTION DETECTED")
    logger.info("User ID: %s", payload.user_id)
    logger.info("Guild ID: %s", payload.guild_id)
    logger.info("Channel ID: %s", payload.channel_id)
    logger.info("Message ID: %s", payload.message_id)
    logger.info("Emoji raw: %s", payload.emoji)
    logger.info("Emoji name: %s", payload.emoji.name)
    logger.info("Emoji ID: %s", payload.emoji.id)
    logger.info("Configured source channels: %s", SOURCE_CHANNEL_IDS)
    logger.info("Configured approval emoji: %s", APPROVAL_EMOJI)
    logger.info("Configured rejection emoji: %s", REJECTION_EMOJI)
    logger.info("========================================")

    if bot.user and payload.user_id == bot.user.id:
        logger.info("Ignored: bot reacted to something.")
        return

    if payload.guild_id is None:
        logger.info("Ignored: reaction was not in a server.")
        return

    if payload.channel_id not in SOURCE_CHANNEL_IDS:
        logger.info(
            "Ignored: reaction was in channel %s, not one of configured source channels %s",
            payload.channel_id,
            SOURCE_CHANNEL_IDS,
        )
        return

    is_approval = emoji_matches(payload.emoji, APPROVAL_EMOJI)
    is_rejection = emoji_matches(payload.emoji, REJECTION_EMOJI)

    if not is_approval and not is_rejection:
        logger.info("Ignored: emoji did not match approval or rejection emoji.")
        return

    logger.info("Reaction passed source channel and emoji checks.")

    async with processing_lock:
        if payload.message_id in processing_message_ids:
            logger.info("Ignored: message is already processing: %s", payload.message_id)
            return

        processing_message_ids.add(payload.message_id)

    try:
        if is_approval:
            await handle_approval(payload)
        elif is_rejection:
            await handle_rejection(payload)

    finally:
        async with processing_lock:
            processing_message_ids.discard(payload.message_id)


async def handle_approval(payload: discord.RawReactionActionEvent):
    logger.info("Starting approval workflow for message %s", payload.message_id)

    approved_at = datetime.now(timezone.utc)

    approver = await get_member_from_payload(payload)

    if approver is None:
        logger.warning("Could not resolve approver: %s", payload.user_id)
        return

    if not user_can_moderate(approver):
        logger.info(
            "Denied: user %s (%s) tried to approve without permission.",
            approver,
            approver.id,
        )
        return

    message = await fetch_message(payload.channel_id, payload.message_id)

    if message is None:
        logger.warning("Stopping: could not fetch original message.")
        return

    if not isinstance(message.channel, discord.TextChannel):
        logger.warning("Message channel is not a text channel: %s", message.channel.id)
        return

    source_channel = message.channel
    submitter = get_submitter_info(message)

    team_destination_channel_id = TEAM_DESTINATION_MAP.get(source_channel.id)

    if team_destination_channel_id is None:
        logger.error(
            "No team destination configured for source channel %s. "
            "Original message will not be deleted.",
            source_channel.id,
        )
        return

    image_source = get_first_valid_image_source(message)

    if image_source is None:
        logger.info("Stopping: message %s has no valid image source.", message.id)
        return

    admin_channel = await fetch_text_channel(
        ADMIN_APPROVAL_CHANNEL_ID,
        "admin approval",
    )

    if admin_channel is None:
        logger.error("Stopping: could not access admin approval channel.")
        return

    team_channel = await fetch_text_channel(
        team_destination_channel_id,
        "team approval",
    )

    if team_channel is None:
        logger.error("Stopping: could not access team approval channel.")
        return

    admin_message: Optional[discord.Message] = None
    team_message: Optional[discord.Message] = None

    try:
        image_bytes, filename = await download_image_source(image_source)

        team_message = await repost_approved_image(
            channel=team_channel,
            image_bytes=image_bytes,
            filename=filename,
            approver=approver,
            source_channel=source_channel,
            submitter=submitter,
            original_message_sent_at=message.created_at,
            approved_at=approved_at,
            destination_label="Team Approvals",
        )

        admin_message = await repost_approved_image(
            channel=admin_channel,
            image_bytes=image_bytes,
            filename=filename,
            approver=approver,
            source_channel=source_channel,
            submitter=submitter,
            original_message_sent_at=message.created_at,
            approved_at=approved_at,
            destination_label="Admin Approvals",
            team_message_url=team_message.jump_url,
        )

        sheets_payload = {
            "messageSentAt": message.created_at.isoformat(),
            "Admin": approver.display_name,
            "originalAuthor": submitter.display_name,
            "sourceChannelName": source_channel.name,
            "newMessageUrl": team_message.jump_url,
            "category": "",
        }

        await post_to_google_sheets(sheets_payload)

        logger.info("Google Sheets logging succeeded.")
        logger.info("Deleting original message %s", message.id)

        await message.delete()

        logger.info(
            "SUCCESS: Approved original message %s by %s. "
            "Admin repost: %s. Team repost: %s.",
            message.id,
            approver.id,
            admin_message.id,
            team_message.id,
        )

    except discord.Forbidden:
        logger.exception(
            "FAILED: Missing Discord permission while approving message %s. "
            "Original message was not deleted.",
            message.id,
        )

    except discord.HTTPException:
        logger.exception(
            "FAILED: Discord API error while approving message %s. "
            "Original message was not deleted.",
            message.id,
        )

    except Exception:
        logger.exception(
            "FAILED: Approval failed for message %s. "
            "Original message was not deleted.",
            message.id,
        )

        for reposted_message, label in [
            (admin_message, "admin repost"),
            (team_message, "team repost"),
        ]:
            if reposted_message is not None:
                try:
                    logger.info(
                        "Cleaning up %s message %s because approval workflow failed.",
                        label,
                        reposted_message.id,
                    )

                    await reposted_message.delete()

                    logger.info(
                        "Cleaned up %s message %s after failure.",
                        label,
                        reposted_message.id,
                    )

                except Exception:
                    logger.exception(
                        "Failed to clean up %s message %s after approval failure.",
                        label,
                        reposted_message.id,
                    )


async def handle_rejection(payload: discord.RawReactionActionEvent):
    logger.info("Starting rejection workflow for message %s", payload.message_id)

    rejected_at = datetime.now(timezone.utc)

    rejector = await get_member_from_payload(payload)

    if rejector is None:
        logger.warning("Could not resolve rejector: %s", payload.user_id)
        return

    if not user_can_moderate(rejector):
        logger.info(
            "Denied: user %s (%s) tried to reject without permission.",
            rejector,
            rejector.id,
        )
        return

    message = await fetch_message(payload.channel_id, payload.message_id)

    if message is None:
        logger.warning("Stopping: could not fetch original message.")
        return

    if not isinstance(message.channel, discord.TextChannel):
        logger.warning("Message channel is not a text channel: %s", message.channel.id)
        return

    source_channel = message.channel
    submitter = get_submitter_info(message)

    image_source = get_first_valid_image_source(message)

    if image_source is None:
        logger.info("Stopping: message %s has no valid image source.", message.id)
        return

    reason = await ask_rejection_reason(rejector, message, submitter)

    if reason is None:
        logger.info("Stopping: no rejection reason provided.")
        return

    rejected_channel = await fetch_text_channel(
        REJECTED_CHANNEL_ID,
        "rejected",
    )

    if rejected_channel is None:
        logger.error("Stopping: could not access rejected channel.")
        return

    rejected_message: Optional[discord.Message] = None

    try:
        image_bytes, filename = await download_image_source(image_source)

        rejected_message = await post_rejected_image(
            channel=rejected_channel,
            image_bytes=image_bytes,
            filename=filename,
            rejector=rejector,
            source_channel=source_channel,
            submitter=submitter,
            original_message_sent_at=message.created_at,
            rejected_at=rejected_at,
            reason=reason,
        )

        logger.info("Deleting original rejected message %s", message.id)

        await message.delete()

        logger.info(
            "SUCCESS: Rejected original message %s by %s. Rejected post: %s.",
            message.id,
            rejector.id,
            rejected_message.id,
        )

        try:
            await rejector.send(
                f"Rejection posted successfully: {rejected_message.jump_url}"
            )
        except Exception:
            pass

    except discord.Forbidden:
        logger.exception(
            "FAILED: Missing Discord permission while rejecting message %s. "
            "Original message was not deleted.",
            message.id,
        )

    except discord.HTTPException:
        logger.exception(
            "FAILED: Discord API error while rejecting message %s. "
            "Original message was not deleted.",
            message.id,
        )

    except Exception:
        logger.exception(
            "FAILED: Rejection failed for message %s. "
            "Original message was not deleted.",
            message.id,
        )

        if rejected_message is not None:
            try:
                logger.info(
                    "Cleaning up rejected message %s because rejection workflow failed.",
                    rejected_message.id,
                )

                await rejected_message.delete()

                logger.info(
                    "Cleaned up rejected message %s after failure.",
                    rejected_message.id,
                )

            except Exception:
                logger.exception(
                    "Failed to clean up rejected message %s after rejection failure.",
                    rejected_message.id,
                )


# =========================
# Start Bot
# =========================

logger.info("Starting Discord Image Approval Bot...")

bot.run(DISCORD_TOKEN)