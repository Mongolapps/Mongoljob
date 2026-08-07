# Railway deployment checklist

1. Create a Railway service from this repository.
2. Add a persistent volume mounted at `/data`.
3. Add these variables:
   - `BOT_TOKEN`: the current token from BotFather
   - `ADMIN_ID`: the administrator's numeric Telegram ID
   - `CHANNEL_ID`: `@servigomgl` or the channel's numeric ID
   - `PREMIUM_CONTACT`: `bayanburd` without `@`
   - `DATABASE_PATH`: `/data/servigo.db`
   - `LOG_LEVEL`: `INFO`
4. Add the bot to the channel as an administrator with permission to post messages.
5. Keep exactly one Railway replica active. Stop Termux, VPS, and older Railway services using the same token.
6. Deploy and confirm the log contains `ServiGo started`.
7. In Telegram, test `/start`, seeker registration, business approval, job approval, channel publishing, and both sides of Match.

## Common crash messages

- `BOT_TOKEN тохируулаагүй`: the variable is missing.
- `BOT_TOKEN буруу форматтай`: the value is not a BotFather token.
- `ADMIN_ID-д ... numeric ID`: use digits only, without `@`.
- `Conflict: terminated by other getUpdates request`: another bot instance is polling with the same token.
- `Forbidden: bot is not a member of the channel chat`: add the bot to the channel and grant posting permission.
