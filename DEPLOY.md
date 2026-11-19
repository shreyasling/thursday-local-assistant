# Thursday on Dokploy

## Build settings

- Build type: Dockerfile
- Dockerfile path: `Dockerfile`
- Build context: repository root (`.`)
- Container port: `5005`

## Persistent volumes

Create named volumes and mount them as follows:

- `/data` — memory database and logs
- `/workspace` — assistant workspace files

## Environment variables

Set these in Dokploy's Environment section. Never commit API keys or tokens.

- `OPENAI_API_KEY` — your OpenAI API key
- `LLM_PROVIDER=openai`
- `LLM_MODEL=gpt-6.2-sol`
- `LLM_API_MODE=auto`
- `THURSDAY_API_TOKEN` — unique random secret, at least 32 characters

The Docker entrypoint refuses to start if `THURSDAY_API_TOKEN` is missing.

## Domain and security

Attach a domain in Dokploy and enable HTTPS. Do not expose port 5005 directly to the public internet or forward it from your router. Keep the API token private.

The included server config disables shell execution, desktop/Hyprland integration, and voice by default. File access is limited to `/workspace` and `/data`.

## Notes

This Dockerfile has not yet been built on the target server. Inspect Dokploy build logs and test authentication before sharing the domain.
