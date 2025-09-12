# Twilio WhatsApp Sandbox Setup

## Sandbox Configuration

Your Twilio sandbox is configured with these webhook URLs:

### Incoming Messages
- **URL:** `https://37c483b4112c.ngrok-free.app/webhook`
- **Method:** `POST`

### Status Callback (Optional)  
- **URL:** `https://37c483b4112c.ngrok-free.app/webhook`
- **Method:** `POST`

## Required Environment Variables

Add these to your `.env` file:

```bash
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_NUMBER=+14155238886

# Webhook verification (keep existing)
WEBHOOK_VERIFY_TOKEN=your_webhook_token

# Optional: Enhanced security
TWILIO_WEBHOOK_AUTH_ENABLED=false
```

## Testing the Integration

1. **Start your application:**
   ```bash
   uv run python -m app.main
   ```

2. **Ensure ngrok is running:**
   ```bash
   ngrok http 8080
   ```

3. **Join the Twilio Sandbox:**
   - Send `join <your-sandbox-code>` to `+1 415 523 8886` from WhatsApp
   - Example: `join <sandbox-name>`

4. **Test messaging:**
   - Send any message to the Twilio sandbox number
   - Check your application logs for webhook data

## Webhook Data Format

Twilio sends webhook data as form-encoded POST requests with these fields:

```
MessageSid: SM1234567890abcdef
From: whatsapp:+1234567890  
To: whatsapp:+14155238886
Body: Hello World
MessageStatus: received
```

## Key Differences from Meta API

| Feature | Meta WhatsApp | Twilio WhatsApp |
|---------|---------------|-----------------|
| Data Format | JSON | Form-encoded |
| Interactive Messages | Native buttons/lists | Text with numbered options |
| Message ID | Custom format | Twilio SID format |
| Webhook Verification | GET with challenge | Optional signature validation |

## Troubleshooting

1. **Webhook not receiving data:**
   - Verify ngrok URL is publicly accessible
   - Check Twilio console webhook configuration
   - Ensure your app is running on correct port

2. **Messages not sending:**
   - Verify TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN
   - Check Twilio console for error logs
   - Ensure WhatsApp number format includes country code

3. **Interactive messages not working:**
   - Twilio requires pre-approved templates for buttons
   - Current implementation uses numbered text options instead

## Production Setup

For production deployment:

1. Replace ngrok URL with your production domain
2. Enable webhook authentication: `TWILIO_WEBHOOK_AUTH_ENABLED=true`
3. Apply for Twilio WhatsApp Business API approval
4. Configure approved message templates for interactive content

## Support

- [Twilio WhatsApp API Documentation](https://www.twilio.com/docs/whatsapp)
- [Twilio Console](https://console.twilio.com/)
- [WhatsApp Business API Guidelines](https://developers.facebook.com/docs/whatsapp/overview)