# Discord Image Approval Bot

A Discord bot that automates image submission approval and rejection workflows using reactions.

## Features

- Approve images with ✅ reaction
- Reject images with ❌ reaction + required reason
- Reposts approved images to team and admin channels
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
