# ServiGo Telegram Bot

## Local ажиллуулах

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

`.env` файлд `BOT_TOKEN`, `ADMIN_ID`, `CHANNEL_ID`, `PREMIUM_CONTACT` утгуудыг тохируулна.

## Railway

1. Файлуудаа GitHub repository руу push хийнэ.
2. Railway дээр repository-г холбоно.
3. Variables хэсэгт `.env.example`-ийн хувьсагчдыг нэмнэ.
4. Start command: `python bot.py`.
5. Bot-оо channel-ийн admin болгож, post/edit message эрх өгнө.

`servigo.db` файл автоматаар үүснэ. Байнгын өгөгдөл хадгалах бол Railway Volume холбоно.
