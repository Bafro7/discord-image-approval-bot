# Discord Image Approval Bot

A configurable Discord bot that automates image submission moderation using emoji reactions. Supports multi-channel routing, role-based permissions, rejection workflows with DM-collected reasons, parallel reposting to designated channels, Google Sheets logging via webhook, and interactive category tagging via dropdown UI.

---

## How It Works

1. A user posts an image in a monitored channel
2. An authorized moderator reacts with an approval or rejection emoji
3. **On approval** — the image is reposted to configured destination channels and logged to Google Sheets
4. **On rejection** — the bot DMs the moderator for a reason, notifies the submitter, and archives the image to a dedicated channel
5. A moderator selects a category from a dropdown — the bot updates Google Sheets and cleans up the admin post

---

## Features

- Emoji-based approval and rejection workflow
- Rejection reason collected via DM before any action is taken
- Parallel reposting to team and admin review channels
- Google Sheets logging via Google Apps Script webhook
- Category tagging via interactive dropdown (role-gated)
- Handles both file attachments and embed-based images
- Extracts submitter identity from bot-generated embeds and resolves to Discord members
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

# Comma-separated channel IDs where users post images
SOURCE_CHANNEL_IDS=111111111111,222222222222

# Channel where admin review reposts are sent
ADMIN_APPROVAL_CHANNEL_ID=333333333333

# Channel where rejected images are archived
REJECTED_CHANNEL_ID=444444444444

# Maps each source channel to a destination channel: sourceId:destId,...
TEAM_DESTINATION_MAP=111111111111:555555555555,222222222222:666666666666

# Emoji used for approval and rejection
APPROVAL_EMOJI=✅
REJECTION_EMOJI=❌

# Comma-separated role IDs allowed to approve, reject, and categorize
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
| Send Messages | Post to destination and archived channels |
| Manage Messages | Delete original messages after approval or rejection |
| Embed Links | Send approval and rejection embeds |
| Attach Files | Repost images to destination channels |
| Read Message History | Fetch original messages on reaction |
| Members Intent | Resolve submitter identity from embed-based posts |

Enable the following **Privileged Gateway Intents** in the Discord Developer Portal:
- `SERVER MEMBERS INTENT`
- `MESSAGE CONTENT INTENT`

---

## Google Sheets Integration

The bot calls a Google Apps Script webhook with two action types.

**On approval:**
```json
{
  "messageSentAt": "<ISO 8601 timestamp>",
  "Admin": "<approver display name>",
  "originalAuthor": "<submitter display name>",
  "sourceChannelName": "<channel name>",
  "newMessageUrl": "<destination channel message URL>",
  "category": ""
}
```

**On category selection:**
```json
{
  "action": "updateCategory",
  "newMessageUrl": "<destination channel message URL>",
  "category": "<selected category>"
}
```

Your Apps Script should handle both payloads and update the corresponding row by matching on `newMessageUrl`.

---

## Customization

**Categories** — Edit the `CATEGORY_OPTIONS` list in `bot.py` to match your use case. These populate the dropdown shown on admin review posts.

**Emoji** — Any standard or custom server emoji can be used for approval and rejection by setting `APPROVAL_EMOJI` and `REJECTION_EMOJI` in `.env`.

**Channel routing** — Each source channel maps independently to a destination channel via `TEAM_DESTINATION_MAP`, allowing different teams or workflows to share the same bot instance.

---

## License

MIT
