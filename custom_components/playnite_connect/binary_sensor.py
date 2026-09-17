"""Connectivity entity for the Playnite Connect desktop plugin."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_LIBRARY, DOMAIN
from .connect_library import PlayniteConnectLibrary


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Add the Playnite connection-status entity."""
    async_add_entities([PlayniteAvailabilityBinarySensor(hass, entry)])


class PlayniteAvailabilityBinarySensor(BinarySensorEntity):
    """Show whether the Playnite Connect plugin can receive MQTT commands."""

    _attr_has_entity_name = True
    _attr_name = "Available"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the push-updated availability entity."""
        self.hass = hass
        self._entry = entry
        self._library: PlayniteConnectLibrary = hass.data[DOMAIN][
            entry.entry_id
        ][DATA_LIBRARY]
        self._attr_unique_id = f"{entry.entry_id}_available"

    @property
    def device_info(self):
        """Attach this entity to the configured Playnite Connect device."""
        device = self.hass.data[DOMAIN][self._entry.entry_id]["device"]
        return {"identifiers": device.identifiers}

    @property
    def is_on(self) -> bool:
        """Return the retained MQTT presence state.

        The entity intentionally remains available while the integration is
        loaded: an offline plugin is a useful `off` automation condition, not
        an unavailable Home Assistant entity.
        """
        return self._library.available

    async def async_added_to_hass(self) -> None:
        """Write the state whenever the retained presence value changes."""
        self.async_on_remove(
            self._library.async_add_listener(self.async_write_ha_state)
        )