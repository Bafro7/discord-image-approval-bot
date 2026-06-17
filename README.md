# Discord Image Approval Bot

A Discord bot for OSRS clans that automates drop screenshot approvals and rejections using emoji reactions. Approved screenshots are reposted to team and admin channels, logged to Google Sheets, and tagged by category via an interactive dropdown.

---

## How It Works

1. A member posts a drop screenshot in a configured source channel
2. An authorized staff member reacts with ✅ or ❌
3. **On approval** — the bot reposts the image to the team channel and admin review channel, then logs the entry to Google Sheets
4. **On rejection** — the bot DMs the staff member asking for a reason, then posts the image to the rejected channel and notifies the submitter
5. An admin selects a loot category from the dropdown on the admin post (e.g. *Raid Purples*, *Zulrah Uniques*) — the bot updates Google Sheets and deletes the admin post

---

## Features

- Emoji-based approval and rejection workflow
- Rejection reason collected via DM before any action is taken
- Parallel reposting to team channel and admin review channel
- Google Sheets logging via Google Apps Script webhook
- Category tagging via interactive dropdown (admin-only)
- Handles both file attachments and embed-based images (Dink / Captain Hook bot support)
- Extracts in-game player names from bot embeds and resolves them to Discord members
- Processing lock to prevent duplicate handling of the same message
- Automatic cleanup of reposted messages on workflow failure

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| Discord API | [discord.py](https://github.com/Rapptz/discord.py) |
| HTTP client | [aiohttp](https://docs.aiohttp.org/) |
| Logging | Google Apps Script webhook → Google Sheets |
| Config | `.env` via `python-dotenv` |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/your-repo.git
cd your-repo
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in the values:

```env
DISCORD_TOKEN=your_bot_token

# Comma-separated channel IDs where members post screenshots
SOURCE_CHANNEL_IDS=111111111111,222222222222

# Channel where admin review reposts are sent
ADMIN_APPROVAL_CHANNEL_ID=333333333333

# Channel where rejected screenshots are posted
REJECTED_CHANNEL_ID=444444444444

# Maps each source channel to a team destination channel: sourceId:destId,...
TEAM_DESTINATION_MAP=111111111111:555555555555,222222222222:666666666666

# Emoji used for approval and rejection
APPROVAL_EMOJI=✅
REJECTION_EMOJI=❌

# Comma-separated role IDs allowed to approve/reject/categorize
APPROVAL_ROLE_IDS=777777777777,888888888888

# Google Apps Script web app URL
GOOGLE_APPS_SCRIPT_WEBHOOK_URL=https://script.google.com/macros/s/.../exec

# Seconds to wait for a rejection reason via DM (default: 900)
REJECTION_REASON_TIMEOUT_SECONDS=900
```

### 4. Run the bot

```bash
python bot.py
```

---

## Required Bot Permissions

| Permission | Reason |
|---|---|
| Read Messages / View Channels | Monitor source channels |
| Send Messages | Post to team, admin, and rejected channels |
| Manage Messages | Delete original messages after approval/rejection |
| Embed Links | Send approval/rejection embeds |
| Attach Files | Repost images |
| Add Reactions | (optional) Reaction feedback |
| Read Message History | Fetch original messages |
| Members Intent | Resolve player names to Discord members |

Enable the following **Privileged Gateway Intents** in the Discord Developer Portal:
- `SERVER MEMBERS INTENT`
- `MESSAGE CONTENT INTENT`

---

## Google Sheets Integration

The bot calls a Google Apps Script webhook with two action types:

**On approval:**
```json
{
  "messageSentAt": "<ISO 8601 timestamp>",
  "Admin": "<approver display name>",
  "originalAuthor": "<submitter display name>",
  "sourceChannelName": "<channel name>",
  "newMessageUrl": "<team channel message URL>",
  "category": ""
}
```

**On category selection:**
```json
{
  "action": "updateCategory",
  "newMessageUrl": "<team channel message URL>",
  "category": "<selected category>"
}
```

Your Apps Script should handle both payloads and update the corresponding row.

---

## Supported Drop Categories

<details>
<summary>View all categories</summary>

Zalcano Shards · Gauntlet Seeds · Spirit Shields · Yama Uniques · DK Rings · Nightmare Uniques · Godsword Shards · Zulrah Uniques · Nex Uniques · Barrows and Moons · Raid Purples · Dragon Pickaxes · Virtus Pieces · Vorkath Heads · Unique Pets/Jars · Tome of Fire · Tome of Water · Tome of Earth · Blessings · Venator Shards · Doom Uniques · Elemental Staff Crowns

</details>

---

## License

MIT
