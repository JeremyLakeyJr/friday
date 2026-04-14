"""
Home Assistant tools — interact with a local Home Assistant server via its REST API.

Requires in .env:
  HA_URL   = http://homeassistant.local:8123  (or your HA IP/hostname)
  HA_TOKEN = <long-lived access token from HA profile page>
"""

import json
import httpx
from friday.config import config

_TIMEOUT = 10


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.HA_TOKEN}",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return config.HA_URL.rstrip("/")


def _not_configured() -> str | None:
    if not config.HA_TOKEN:
        return "HA_TOKEN not set in .env — get a long-lived token from your HA profile page."
    return None


def register(mcp):

    @mcp.tool()
    async def ha_get_states(domain: str) -> str:
        """
        List Home Assistant entity states, optionally filtered by domain.
        domain examples: 'light', 'switch', 'climate', 'sensor', 'media_player', 'automation'.
        Pass empty string to list ALL entities (may be long).
        """
        err = _not_configured()
        if err:
            return err
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.get(f"{_base()}/api/states", headers=_headers())
                r.raise_for_status()
                states = r.json()
            except Exception as e:
                return f"HA error: {e}"

        if domain.strip():
            prefix = domain.strip().lower() + "."
            states = [s for s in states if s["entity_id"].startswith(prefix)]

        if not states:
            return f"No entities found for domain '{domain}'."

        lines = []
        for s in states:
            attrs = s.get("attributes", {})
            friendly = attrs.get("friendly_name", "")
            extra = ""
            # Include useful extra attrs per domain
            if "brightness" in attrs:
                extra = f", brightness={attrs['brightness']}"
            elif "temperature" in attrs:
                extra = f", temp={attrs.get('temperature')}°"
            elif "current_temperature" in attrs:
                extra = f", current={attrs.get('current_temperature')}°"
            elif "volume_level" in attrs:
                extra = f", vol={attrs.get('volume_level')}"
            name = f" ({friendly})" if friendly and friendly != s["entity_id"] else ""
            lines.append(f"{s['entity_id']}{name}: {s['state']}{extra}")

        return "\n".join(lines)

    @mcp.tool()
    async def ha_get_state(entity_id: str) -> str:
        """
        Get the full state and attributes of a single Home Assistant entity.
        entity_id example: 'light.living_room', 'switch.fan', 'sensor.temperature'
        """
        err = _not_configured()
        if err:
            return err
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.get(
                    f"{_base()}/api/states/{entity_id}", headers=_headers()
                )
                if r.status_code == 404:
                    return f"Entity '{entity_id}' not found."
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                return f"HA error: {e}"

        attrs = data.get("attributes", {})
        attr_str = json.dumps(attrs, indent=2) if attrs else "{}"
        return (
            f"entity_id: {data['entity_id']}\n"
            f"state: {data['state']}\n"
            f"last_changed: {data.get('last_changed', 'unknown')}\n"
            f"attributes:\n{attr_str}"
        )

    @mcp.tool()
    async def ha_call_service(domain: str, service: str, entity_id: str, service_data: str) -> str:
        """
        Call any Home Assistant service.
        domain: e.g. 'light', 'switch', 'climate', 'script', 'automation', 'media_player'
        service: e.g. 'turn_on', 'turn_off', 'toggle', 'set_temperature'
        entity_id: e.g. 'light.living_room' — pass empty string to target all in domain
        service_data: JSON string of extra params, e.g. '{"brightness": 128}' or '{}' for none

        Common examples:
          ha_call_service("light", "turn_on", "light.living_room", "{\"brightness\": 200}")
          ha_call_service("switch", "toggle", "switch.fan", "{}")
          ha_call_service("climate", "set_temperature", "climate.thermostat", "{\"temperature\": 22}")
          ha_call_service("media_player", "volume_set", "media_player.tv", "{\"volume_level\": 0.5}")
          ha_call_service("script", "turn_on", "script.good_morning", "{}")
          ha_call_service("automation", "trigger", "automation.sunrise", "{}")
        """
        err = _not_configured()
        if err:
            return err

        try:
            data: dict = json.loads(service_data) if service_data.strip() else {}
        except json.JSONDecodeError as e:
            return f"Invalid service_data JSON: {e}"

        if entity_id.strip():
            data["entity_id"] = entity_id.strip()

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.post(
                    f"{_base()}/api/services/{domain}/{service}",
                    headers=_headers(),
                    json=data,
                )
                r.raise_for_status()
                result = r.json()
            except Exception as e:
                return f"HA error: {e}"

        if not result:
            return f"OK — {domain}.{service} called on '{entity_id or 'all'}'."

        # Return affected entity states
        affected = [f"{s['entity_id']}: {s['state']}" for s in result]
        return "OK — affected entities:\n" + "\n".join(affected)

    @mcp.tool()
    async def ha_list_domains() -> str:
        """
        List all entity domains available in Home Assistant (light, switch, sensor, etc.)
        and how many entities each domain has. Useful for exploring what's available.
        """
        err = _not_configured()
        if err:
            return err
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                r = await client.get(f"{_base()}/api/states", headers=_headers())
                r.raise_for_status()
                states = r.json()
            except Exception as e:
                return f"HA error: {e}"

        from collections import Counter
        counts = Counter(s["entity_id"].split(".")[0] for s in states)
        lines = [f"{domain}: {count} entities" for domain, count in sorted(counts.items())]
        return "\n".join(lines) if lines else "No entities found."
