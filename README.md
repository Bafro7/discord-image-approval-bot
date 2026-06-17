# Discord Image Approval Bot

A Discord bot that automates image submission approval and rejection workflows using reactions.

## Features

- Approve images with ✅ reaction
- Reject images with ❌ reaction + required reason
- Reposts approved images to team and admin channels
- Deletes images in "to-be-done" channels after verification of copying/reposting in approved channels
- Logs approvals to Google Sheets
- Category dropdown tagging (admin only)
- Handles attachments and embed images
- Extracts submitter info automatically

## Tech Stack

- Python
- discord.py
- aiohttp
- Google Apps Script webhook

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt

## System Workflow

The bot operates as an event-driven moderation pipeline built around Discord reactions and asynchronous processing.

---

### 1. Submission Phase

- Users submit images (attachments or embeds) in designated source channels.
- The bot does not actively poll messages; it reacts only to Discord events.

---

### 2. Trigger Phase (Reaction Listener)

- Staff react to a message with:
  - ✅ for approval
  - ❌ for rejection
- The bot listens via `on_raw_reaction_add` to capture reactions even on uncached messages.

---

### 3. Validation Layer

When a reaction is detected, the bot performs a series of checks:

- Verifies the reaction comes from an allowed source channel
- Confirms the emoji matches configured approval/rejection rules
- Validates the user has moderation permissions (role-based or admin)
- Prevents duplicate processing using a lock + message tracking

---

### 4. Image Extraction Layer

The bot determines the image source:

- Priority 1: Direct message attachments
- Priority 2: Embedded images (proxy URL or thumbnail fallback)

This allows compatibility with both user uploads and bot-generated embeds.

---

### 5. Approval Pipeline

If approved (✅):

- Image is downloaded asynchronously
- Submitter metadata is extracted (user or bot-originated)
- Image is reposted to:
  - Team channel (primary storage)
  - Admin review channel (audit trail)
- A structured embed is generated containing:
  - Approver identity
  - Submitter identity
  - Source channel metadata
  - Timestamp tracking (Discord snowflake time)
- Event is logged to Google Sheets via webhook
- Original message is deleted after successful processing

---

### 6. Rejection Pipeline

If rejected (❌):

- Moderator is prompted via DM to provide a rejection reason
- The bot waits for structured input with timeout protection
- Image is downloaded and reposted to a rejection archive channel
- Embed includes:
  - Rejector identity
  - Reason for rejection
  - Original submission metadata
- Original message is deleted after successful processing

---

### 7. External Integration Layer

The bot integrates with Google Sheets through a webhook:

- Logs approvals with:
  - submitter
  - approver
  - timestamp
  - destination message URL
- Enables external auditing and tracking outside Discord

---

### 8. Concurrency & Safety Controls

To prevent race conditions:

- Per-message processing lock (`asyncio.Lock`)
- In-memory message tracking set
- Graceful failure handling with cleanup rollback
- Permission validation before destructive actions

---

## Architecture Summary

## Setup & Configuration

This project requires a small amount of local configuration to connect the bot to Discord and external services.

---

### 1. Environment Variables

Create a `.env` file in the project root.

This file stores all sensitive credentials and environment-specific configuration.

```env
DISCORD_TOKEN=your_discord_bot_token

SOURCE_CHANNEL_IDS=123456789,987654321
ADMIN_APPROVAL_CHANNEL_ID=123456789
REJECTED_CHANNEL_ID=123456789

TEAM_DESTINATION_MAP=source_channel_id:team_channel_id

GOOGLE_APPS_SCRIPT_WEBHOOK_URL=your_google_apps_script_url
