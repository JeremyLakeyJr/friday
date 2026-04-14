# Skill: Home Assistant

Control and query your local Home Assistant server.

Requires `.env` config:
```
HA_URL=http://homeassistant.local:8123   # or your HA IP
HA_TOKEN=<long-lived access token>       # HA profile → Security → Long-Lived Access Tokens
```

---

## ha_list_domains()
List all entity domains (light, switch, sensor, climate, etc.) and how many entities each has.
Use this first to explore what's available.

```
ha_list_domains()
```

---

## ha_get_states(domain)
List entities and their current states, filtered by domain.
Pass `""` to get ALL entities (may be long — prefer filtering by domain).

```
ha_get_states("light")          # all lights
ha_get_states("switch")         # all switches
ha_get_states("climate")        # thermostats
ha_get_states("sensor")         # sensors (temp, humidity, etc.)
ha_get_states("media_player")   # TVs, speakers
ha_get_states("automation")     # automations
ha_get_states("")               # everything
```

---

## ha_get_state(entity_id)
Get full state + all attributes of one entity.

```
ha_get_state("light.living_room")
ha_get_state("sensor.outdoor_temperature")
ha_get_state("climate.thermostat")
```

---

## ha_call_service(domain, service, entity_id, service_data)
Call any Home Assistant service. `service_data` is a JSON string of extra params — use `"{}"` if none needed.

### Lights
```
ha_call_service("light", "turn_on",  "light.living_room", "{}")
ha_call_service("light", "turn_off", "light.living_room", "{}")
ha_call_service("light", "toggle",   "light.living_room", "{}")
ha_call_service("light", "turn_on",  "light.living_room", "{\"brightness\": 200}")
ha_call_service("light", "turn_on",  "light.living_room", "{\"brightness\": 128, \"color_temp\": 300}")
ha_call_service("light", "turn_on",  "light.living_room", "{\"rgb_color\": [255, 0, 0]}")
```

### Switches
```
ha_call_service("switch", "turn_on",  "switch.fan", "{}")
ha_call_service("switch", "turn_off", "switch.fan", "{}")
ha_call_service("switch", "toggle",   "switch.fan", "{}")
```

### Climate / Thermostat
```
ha_call_service("climate", "set_temperature", "climate.thermostat", "{\"temperature\": 22}")
ha_call_service("climate", "set_hvac_mode",   "climate.thermostat", "{\"hvac_mode\": \"heat\"}")
ha_call_service("climate", "turn_off",        "climate.thermostat", "{}")
```

### Media Player
```
ha_call_service("media_player", "volume_set",    "media_player.tv", "{\"volume_level\": 0.5}")
ha_call_service("media_player", "media_play",    "media_player.tv", "{}")
ha_call_service("media_player", "media_pause",   "media_player.tv", "{}")
ha_call_service("media_player", "media_next_track", "media_player.tv", "{}")
```

### Scripts & Automations
```
ha_call_service("script",     "turn_on", "script.good_morning",   "{}")
ha_call_service("automation", "trigger", "automation.sunrise",     "{}")
ha_call_service("automation", "turn_off","automation.away_mode",   "{}")
```

### All entities in a domain (leave entity_id empty)
```
ha_call_service("light", "turn_off", "", "{}")   # turn off ALL lights
```

---

## Workflow tips
- Don't know entity names? → `ha_list_domains()` then `ha_get_states("light")`
- Want full details on one thing? → `ha_get_state("light.living_room")`
- User says "turn on the kitchen light"? → `ha_get_states("light")` to find the entity_id, then `ha_call_service`
- Always confirm success by reading the affected entities returned by `ha_call_service`
